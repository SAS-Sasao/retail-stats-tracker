"""ダイジェスト走査・表行分解（FR-01 / FR-02）。実装設計 §4.1。

セクション判定と表行分解のみを行う。値の解釈は行わない（parser.py の責務）。
依存先: models, textnorm。catalog には依存しない（対称性のため意図的に分離。
実装設計 §2.3）。

`parse-wbs.py` から移植する部分（実装設計 §2.4）:
    split_table_row() — `|` 分解と前後空白除去。そのまま移植
    is_separator_row() — `^:?-+:?$` によるセパレータ判定。そのまま移植
    detect_header_map() の設計 — 判定条件は差し替え（digest は「記事」と
        「ソース」の両方が揃った時にヘッダ確定。catalog は必須列が全て
        揃った時に確定し、欠けていればエラー停止 = parse-wbs.py と逆）
    見出しでヘッダマップをリセットする走査ループの設計を移植
    HEADER_ALIASES の設計を移植（中身は IF-02 の許容列名に差し替え）
    infer_*_from_*() 系の推測関数は移植しない（本システムは推測禁止、FR-24）

走査規則（実装設計 §4.1）:
    1. `^###\\s+(.+)$` に一致したら、見出しに「決算・統計」を含むかで
       対象フラグを立て直す（章番号 B5 では判定しない、要件 7-1）
    2. `^##\\s+` に一致したら対象フラグを落とす
    3. 対象フラグが立っている間、`|` 開始行を分解する
    4. 区切り行はスキップ
    5. ヘッダ行（「記事」と「ソース」が解決できる行）で列マップを確定する。
       列マップ未確定のデータ行は捨てずに unresolved に落とす（要件 7-12）
    6. 記事セルから `\\[(?P<title>.+?)\\]\\((?P<url>https?://[^\\s)]+)\\)` を
       抽出する。抽出できない行は unresolved（low_confidence 相当）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from retail_stats.models import DigestRow

SECTION_KEYWORD = "決算・統計"

DIGEST_COLUMNS: dict[str, tuple[str, ...]] = {
    "index": ("#", "No", "番号"),
    "article": ("記事", "タイトル", "Article"),
    "source": ("ソース", "出典", "Source"),
    "summary": ("要約", "概要", "Summary"),
}

# ヘッダ確定の必須キー。この 2 つが揃った行だけをヘッダとして採用する
# （parse-wbs.py detect_header_map の判定条件を差し替えたもの）。
REQUIRED_HEADER_KEYS = ("article", "source")

_H2_RE = re.compile(r"^##\s+(.+)$")
_H3_RE = re.compile(r"^###\s+(.+)$")
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
_LINK_RE = re.compile(r"\[(?P<title>.+?)\]\((?P<url>https?://[^\s)]+)\)")
_WS_RE = re.compile(r"\s+")
DATE_FROM_NAME_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass(frozen=True)
class MalformedRow:
    """列マップ未確定・リンク抽出失敗の行（要件 7-12: silent な欠測を防ぐ）。

    `parser.py` に渡って `UnresolvedRow` になる。ここで捨てないことが要点で、
    捨てると「表の形が変わった」ことが誰にも観測されない（§1.2 silent
    accumulation）。
    """

    digest_date: str
    raw_line: str
    reason: str  # no_header_map / no_link


@dataclass(frozen=True)
class FileResult:
    """1 ファイルの走査結果。`runs.json` の統計に使う値をそのまま持つ。"""

    digest_date: str
    has_section: bool  # 決算・統計章の見出しが存在したか
    has_table: bool  # 章の中にヘッダ確定した表があったか
    rows: tuple[DigestRow, ...]
    malformed: tuple[MalformedRow, ...]
    header_variant: tuple[str, ...] | None  # 実測のヘッダ列名（分布確認用）


def split_table_row(line: str) -> list[str]:
    """`|` 分解 + 前後空白除去（parse-wbs.py split_table_row の移植）。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [cell.strip() for cell in s.split("|")]


def is_separator_row(cells: list[str]) -> bool:
    """`^:?-+:?$` によるセパレータ行判定（parse-wbs.py is_separator_row の移植）。"""
    return bool(cells) and all(_SEPARATOR_CELL_RE.match(cell) for cell in cells)


def detect_header_map(cells: list[str]) -> dict[str, int] | None:
    """許容名リストで canonical → index を作る。

    必須キー（`記事` / `ソース`）が揃ったときのみヘッダとして確定する。
    揃わなければ None を返し、呼び出し側はデータ行として扱う。
    parse-wbs.py と同じく「揃った時のみ確定」だが、揃わなかった行を
    **捨てずに** malformed へ落とす点が異なる（要件 7-12）。
    """
    normalized = {_WS_RE.sub("", cell): idx for idx, cell in enumerate(cells)}
    index: dict[str, int] = {}
    for canonical, allowed in DIGEST_COLUMNS.items():
        for name in allowed:
            key = _WS_RE.sub("", name)
            if key in normalized:
                index[canonical] = normalized[key]
                break
    if any(key not in index for key in REQUIRED_HEADER_KEYS):
        return None
    return index


def date_from_filename(path: Path) -> str:
    """`2026-07-25.md` → `2026-07-25`。日付を含まない名前は空文字を返す。

    掲載日はファイル名由来とする（実行時刻を持ち込まない。NFR-06）。
    """
    m = DATE_FROM_NAME_RE.search(Path(path).name)
    return m.group(1) if m else ""


def _cell(row: list[str], index: dict[str, int], key: str) -> str:
    idx = index.get(key)
    return row[idx] if idx is not None and idx < len(row) else ""


def parse_file(path: Path, digest_date: str | None = None) -> FileResult:
    """1 日分の日次ダイジェスト MD から「決算・統計」章の表行を抽出する。

    章が存在しない日は空の結果を返す（例外にしない。要件 7-1、
    `files_without_section` に計上）。値の解釈は一切行わない。
    """
    path = Path(path)
    if digest_date is None:
        digest_date = date_from_filename(path)
    lines = path.read_text(encoding="utf-8").splitlines()

    in_section = False
    has_section = False
    header: dict[str, int] | None = None
    header_variant: tuple[str, ...] | None = None
    rows: list[DigestRow] = []
    malformed: list[MalformedRow] = []

    for line in lines:
        stripped = line.strip()

        # 規則 1: ### 見出しで対象フラグを立て直す。章番号（B5）では判定しない（要件 7-1）
        m3 = _H3_RE.match(stripped)
        if m3:
            in_section = SECTION_KEYWORD in m3.group(1)
            has_section = has_section or in_section
            header = None  # 見出しをまたいだら列マップを持ち越さない
            continue

        # 規則 2: ## 見出しで対象フラグを落とす（章の切り替わり）
        if _H2_RE.match(stripped):
            in_section = False
            header = None
            continue

        if not in_section or not stripped.startswith("|"):
            continue

        cells = split_table_row(line)

        # 規則 4: 区切り行はスキップ
        if is_separator_row(cells):
            continue

        # 規則 5: ヘッダ行で列マップを確定する
        if header is None:
            candidate = detect_header_map(cells)
            if candidate is not None:
                header = candidate
                header_variant = tuple(cells)
                continue
            # 列マップが未確定のデータ行は捨てずに落とす（要件 7-12）
            malformed.append(MalformedRow(digest_date, line.rstrip(), "no_header_map"))
            continue

        # 規則 6: 記事セルからリンクを抽出する
        article_cell = _cell(cells, header, "article")
        link = _LINK_RE.search(article_cell)
        if link is None:
            # 1 つの章に表が 2 つ以上ある場合、2 つ目のヘッダ行はリンクを持たない。
            # 列マップを持ち越したまま読むとヘッダ行を「リンクの無いデータ行」と
            # 誤認する。ヘッダとして解決できるならヘッダとして扱い直す。
            candidate = detect_header_map(cells)
            if candidate is not None:
                header = candidate
                header_variant = tuple(cells)
                continue
            malformed.append(MalformedRow(digest_date, line.rstrip(), "no_link"))
            continue

        raw_index = _cell(cells, header, "index")
        try:
            row_index = int(raw_index)
        except ValueError:
            row_index = len(rows) + 1

        rows.append(
            DigestRow(
                digest_date=digest_date,
                row_index=row_index,
                title=link.group("title"),  # 原文のまま（正規化しない。§4.2）
                url=link.group("url"),
                source_name=_cell(cells, header, "source"),
                summary=_cell(cells, header, "summary"),
                raw_line=line.rstrip(),  # 未解決時の証跡（FR-10）
            )
        )

    return FileResult(
        digest_date=digest_date,
        has_section=has_section,
        has_table=header_variant is not None,
        rows=tuple(rows),
        malformed=tuple(malformed),
        header_variant=header_variant,
    )


def iter_digest_files(digest_dir: Path, since: str | None = None) -> list[Path]:
    """日付順にソートした digest MD の一覧を返す。

    ファイル名から日付を取れないものは対象外（走査順を実行環境の
    ディレクトリ列挙順に依存させないため、必ず日付でソートする）。
    """
    files = [p for p in Path(digest_dir).glob("*.md") if date_from_filename(p)]
    if since:
        files = [p for p in files if date_from_filename(p) >= since]
    return sorted(files, key=date_from_filename)
