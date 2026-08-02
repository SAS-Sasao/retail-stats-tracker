#!/usr/bin/env python3
"""カタログ MD の IF-02 スキーマ契約検査（C1〜C12）。

loop-engineering-design.md §2.3 ② `verify-catalog-contract.sh` が呼ぶ本体。
ループ設計 §6 の**段階 0 のゲート**であり、実装着手前にカタログ側の不整合を
出し切ることを目的とする。

    exit 0 = pass / exit 1 = 契約違反あり（stdout に違反一覧）
    exit 2 = 引数エラー / exit 3 = I/O エラー（実装設計 §2.5 の終了コード契約）

`catalog.load()`（V1〜V13）との違い:

| | validate_catalog.py（C1〜C12） | catalog.load()（V1〜V13） |
|---|---|---|
| 目的 | カタログ編集の瞬間に契約違反を返す | パイプラインが読む Catalog を作る |
| 失敗の仕方 | 全件を理由コード付きで列挙して続行 | 段階 1〜3 で即停止 |
| 履歴 | **C10 が `git show HEAD:` と比較する**（load には無い） | — |

列名の許容リスト・単位対応表・発表主体対応表は `retail_stats.catalog` の
定数をそのまま使う。同じ契約を 2 か所に書くと、hook が通してローダが
落ちる（あるいはその逆）という最悪の食い違いが生まれるため。

C4 の必須列に `発表主体` を含める点、および C11 / C12 は、実装時に本リポジトリ
から報告した設計不整合（cc-sier-organization Issue #724）に対する判断が
PR #725 で設計原本に反映されたものである。**現在は設計どおりであり、
実装側の独自判断ではない**（origin.md D-C 参照）。

**なお設計に無い実装上の判断（origin.md D-B B6）**:
- C9 の enum 検査に `種別`（entity_type）と `表示順` を含める。ループ設計
  §2.3 ② の C9 は `値種別` / `方向` / `小数桁` のみを挙げるが、C4 が必須列と
  して要求している列の値を検査しないのは片手落ちのため。理由コードは
  設計どおり `enum_invalid` を共用する。

C12 の実装は `Catalog.validate()` ではなく `catalog.load()` を呼ぶ。
`validate()` は Catalog インスタンスのメソッドであり、それを得るには
どのみち `load()` が要るためで、検査範囲は設計の意図（ローダ自身を通す）と
一致する。C1〜C11 が通っている時点で段階 1〜3 は必ず成功する。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from retail_stats import catalog as cat  # noqa: E402
from retail_stats import config  # noqa: E402
from retail_stats.models import (  # noqa: E402
    DIRECTION_HINTS,
    ENTITY_TYPES,
    ID_RE,
    VALUE_TYPES,
)

HINTS = {
    "segment_heading_ambiguous": (
        "IF-02 見出し検出条件: H2 の見出しテキストに `業態区分` を含むものを"
        " ちょうど 1 個にしてください（番号・語尾は問いません）。"
    ),
    "metric_heading_ambiguous": (
        "IF-02 見出し検出条件: H2 の見出しテキストに `指標定義` / `KPI 定義` /"
        " `KPI定義` のいずれかを含むものをちょうど 1 個にしてください。"
    ),
    "table_missing": (
        "見出しの配下（次の H2 まで）に MD テーブルを 1 つ以上置いてください。"
        " 最初のテーブルを定義表として読みます。"
    ),
    "required_column_missing": (
        "必須列を許容名のいずれかで追加してください（IF-02 列要件）。"
        " 欠損列を既定値で埋めて処理を続行することはしません（FR-24）。"
    ),
    "id_format": "ID は kebab-case（^[a-z0-9]+(-[a-z0-9]+)*$）で記載してください。",
    "id_duplicate": "同一の ID を 2 行以上に書かないでください（IF-02: 一意）。",
    "unit_unmapped": (
        "単位対応表は % / ％ / 億円 / 兆円 のみです。"
        " 複数表記は区切り文字（/・読点・カンマ）で分割して記載してください。"
    ),
    "scope_unmapped": "既定スコープは 既存店 / 全店 / 総供給高 / 該当なし のいずれかにしてください。",
    "enum_invalid": "IF-02 が定める enum 値をそのまま記載してください。",
    "authority_unmapped": (
        "発表主体の先頭トークン（最初の `（` / `／` より前）を IF-02 発表主体対応表に"
        " 追加するか、対応表にある表記に合わせてください。"
    ),
    "id_renamed_or_removed": (
        "既存 ID の改名・削除は禁止（IF-02）。observations の natural key が壊れ、"
        " 過去データが参照不能になります。新 ID を追加し、旧 ID には非推奨マークを"
        " 付ける形で表現してください。"
    ),
    "loader_rejected": (
        "IF-02 の条文検査（C1〜C11）は通りましたが、カタログローダ（V1〜V13）が"
        " 受理しません。この状態のまま実装に渡すと hook は緑でパイプラインが停止します。"
    ),
}


class Violation:
    def __init__(self, code: str, target: str, detail: str):
        self.code = code
        self.target = target
        self.detail = detail

    def render(self) -> str:
        return f"  [{self.code}] {self.target}: {self.detail}\n    → {HINTS[self.code]}"


def _find_h2(lines: list[str], keywords: tuple[str, ...]) -> list[int]:
    hits = []
    for i, line in enumerate(lines):
        m = re.match(r"^##\s+([^#].*)$", line.strip())
        if m and any(kw in re.sub(r"\s+", "", m.group(1)) for kw in keywords):
            hits.append(i)
    return hits


def _first_table(lines: list[str], h2_lineno: int):
    """H2 配下の最初の MD テーブルを (ヘッダ行番号, ヘッダcells, [(行番号, cells)]) で返す。"""
    end = len(lines)
    for i in range(h2_lineno + 1, len(lines)):
        if re.match(r"^##\s+[^#]", lines[i].strip()):
            end = i
            break
    i = h2_lineno + 1
    while i < end:
        if lines[i].strip().startswith("|"):
            if i + 1 < end and cat.is_separator_row(cat.split_table_row(lines[i + 1])):
                rows = []
                j = i + 2
                while j < end and lines[j].strip().startswith("|"):
                    cells = cat.split_table_row(lines[j])
                    if not cat.is_separator_row(cells) and any(c.strip() for c in cells):
                        rows.append((j + 1, cells))
                    j += 1
                return i + 1, cat.split_table_row(lines[i]), rows
        i += 1
    return None


def _resolve_columns(header: list[str], required: dict[str, tuple[str, ...]]):
    """許容名で canonical → index を解決する。返り値は (index, 未解決の列ラベル)。"""
    normalized = {cat.normalize_header(c): idx for idx, c in enumerate(header)}
    index, missing = {}, []
    for canonical, allowed in required.items():
        for name in allowed:
            key = cat.normalize_header(name)
            if key in normalized:
                index[canonical] = normalized[key]
                break
        else:
            missing.append(f"{allowed[0]}（許容名: {' / '.join(allowed)}）")
    return index, missing


def _cell(row: list[str], index: dict, key: str) -> str:
    idx = index.get(key)
    return row[idx] if idx is not None and idx < len(row) else ""


def _check_ids(rows, index, key, label, violations) -> list[str]:
    """C6: kebab-case かつ一意。収集した ID 一覧を返す（C10 で使う）。"""
    ids, seen = [], {}
    for lineno, row in rows:
        identifier = cat.clean_cell(_cell(row, index, key))
        ids.append(identifier)
        if not ID_RE.match(identifier):
            violations.append(
                Violation("id_format", f"{label} 行 {lineno}", f"ID {identifier!r} が kebab-case でない")
            )
        if identifier in seen:
            violations.append(
                Violation(
                    "id_duplicate",
                    f"{label} 行 {lineno}",
                    f"ID {identifier!r} が 行 {seen[identifier]} と重複",
                )
            )
        else:
            seen[identifier] = lineno
    return ids


def _check_enum(value: str, allowed, code, target, column, violations) -> None:
    if value not in allowed:
        violations.append(
            Violation(code, target, f"{column} の値 {value!r} が enum {tuple(allowed)} にない")
        )


def _check_section(lines, keywords, columns, label, code_missing_heading, violations):
    """C1/C2（見出し）+ C3（テーブル）+ C4/C5（必須列）を通す。表と列 index を返す。"""
    hits = _find_h2(lines, keywords)
    if len(hits) != 1:
        found = [lines[i].strip() for i in hits]
        violations.append(
            Violation(
                code_missing_heading,
                label,
                f"条件に一致する H2 が {len(hits)} 個（期待: 1 個）。一致行={found}",
            )
        )
        return None, None
    table = _first_table(lines, hits[0])
    if table is None:
        violations.append(
            Violation("table_missing", label, f"見出し 行 {hits[0] + 1} の配下に MD テーブルが無い")
        )
        return None, None
    header_lineno, header, rows = table
    index, missing = _resolve_columns(header, columns)
    for item in missing:
        violations.append(
            Violation("required_column_missing", f"{label}（ヘッダ 行 {header_lineno}）", item)
        )
    if missing:
        return None, None
    return rows, index


def check_catalog(path: Path, use_git: bool = True) -> list[Violation]:
    """C1〜C12 を全て実行し、違反を列挙して返す（最初の 1 件で打ち切らない）。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    violations: list[Violation] = []

    # --- C1 / C3 / C4 / C6 / C9 / C11: 業態定義表 ---------------------------
    segment_columns = {**cat.SEGMENT_COLUMNS}
    rows, index = _check_section(
        lines, cat.SEGMENT_HEADING_KEYWORDS, segment_columns, "segments",
        "segment_heading_ambiguous", violations,
    )
    segment_ids: list[str] = []
    if rows is not None:
        segment_ids = _check_ids(rows, index, "segment_id", "segments", violations)
        for lineno, row in rows:
            target = f"segments 行 {lineno}"
            _check_enum(
                cat.clean_cell(_cell(row, index, "entity_type")),
                ENTITY_TYPES, "enum_invalid", target, "種別", violations,
            )
            order = cat.clean_cell(_cell(row, index, "display_order"))
            if not order.isdigit():
                violations.append(
                    Violation("enum_invalid", target, f"表示順 の値 {order!r} が非負整数でない")
                )
            authority_cell = _cell(row, index, "source_authority")
            head = cat.cell_head(authority_cell)
            if head not in cat.AUTHORITY_TOKEN_MAP:
                violations.append(
                    Violation(
                        "authority_unmapped",
                        target,
                        f"発表主体の先頭トークン {head!r} が IF-02 発表主体対応表に無い",
                    )
                )

    # --- C2 / C3 / C5 / C6 / C7 / C8 / C9: 指標定義表 -----------------------
    rows, index = _check_section(
        lines, cat.METRIC_HEADING_KEYWORDS, {**cat.METRIC_COLUMNS}, "metrics",
        "metric_heading_ambiguous", violations,
    )
    metric_ids: list[str] = []
    if rows is not None:
        metric_ids = _check_ids(rows, index, "metric_id", "metrics", violations)
        for lineno, row in rows:
            target = f"metrics 行 {lineno}"
            unit_cell = _cell(row, index, "unit_raw")
            tokens = [t.strip() for t in re.split(r"[/／,、]", cat.clean_cell(unit_cell)) if t.strip()]
            unmapped = [t for t in tokens if t not in cat.UNIT_TOKEN_MAP]
            if not tokens or unmapped:
                shown = unmapped or [cat.clean_cell(unit_cell)]
                violations.append(
                    Violation(
                        "unit_unmapped",
                        target,
                        f"単位セル {cat.clean_cell(unit_cell)!r} のトークン {shown} が単位対応表に無い",
                    )
                )
            scope_cell = _cell(row, index, "default_scope_raw")
            if cat.cell_head(scope_cell) not in cat.SCOPE_TOKEN_MAP:
                violations.append(
                    Violation(
                        "scope_unmapped",
                        target,
                        f"既定スコープ {cat.cell_head(scope_cell)!r} がスコープ対応表に無い",
                    )
                )
            _check_enum(
                cat.clean_cell(_cell(row, index, "value_type")),
                VALUE_TYPES, "enum_invalid", target, "値種別", violations,
            )
            _check_enum(
                cat.clean_cell(_cell(row, index, "direction_hint")),
                DIRECTION_HINTS, "enum_invalid", target, "方向", violations,
            )
            precision = cat.clean_cell(_cell(row, index, "precision"))
            if not precision.isdigit():
                violations.append(
                    Violation("enum_invalid", target, f"小数桁 の値 {precision!r} が非負整数でない")
                )

    # --- C10: HEAD からの ID 消滅・改名 -------------------------------------
    if use_git:
        violations.extend(_check_head_ids(path, segment_ids, metric_ids))

    # --- C12: ローダ受理（C1〜C11 が全て通ったときのみ）----------------------
    # 先に違反があるときに走らせるとローダが同じ違反を別の言い回しで
    # 二重報告するため、残余だけを見る。
    if not violations:
        try:
            cat.load(path)
        except cat.CatalogError as exc:
            violations.append(Violation("loader_rejected", "catalog.load()", str(exc)))
    return violations


def _check_head_ids(path: Path, segment_ids: list[str], metric_ids: list[str]) -> list[Violation]:
    """C10: `git show HEAD:<path>` と比較し、既存 ID の消滅・改名を検出する。

    最も重要な検査。カタログは小売ドメイン室の管轄であり、本システムの
    都合を知らないまま改訂されうる。ID の改名は observations の natural key
    を破壊し、過去データが静かに参照不能になる。

    HEAD に当該ファイルが無い（新規追加・git 管理外）場合は比較対象が
    存在しないだけなので違反ではない。その旨は stderr に出す（黙って
    検査を飛ばさない）。
    """
    try:
        repo_root = config.find_repo_root(path.parent)
        relpath = path.resolve().relative_to(repo_root).as_posix()
    except (FileNotFoundError, ValueError):
        print(
            f"[info] C10 をスキップ: {path} のリポジトリ相対パスを解決できません",
            file=sys.stderr,
        )
        return []
    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"HEAD:{relpath}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[info] C10 をスキップ: HEAD に {relpath} がありません", file=sys.stderr)
        return []

    previous = result.stdout.splitlines()
    violations: list[Violation] = []
    for label, keywords, columns, key, current in (
        ("segments", cat.SEGMENT_HEADING_KEYWORDS, cat.SEGMENT_COLUMNS, "segment_id", segment_ids),
        ("metrics", cat.METRIC_HEADING_KEYWORDS, cat.METRIC_COLUMNS, "metric_id", metric_ids),
    ):
        hits = _find_h2(previous, keywords)
        if len(hits) != 1:
            continue
        table = _first_table(previous, hits[0])
        if table is None:
            continue
        _, header, rows = table
        index, missing = _resolve_columns(header, columns)
        if missing:
            continue
        for _, row in rows:
            old_id = cat.clean_cell(_cell(row, index, key))
            if old_id and old_id not in current:
                violations.append(
                    Violation(
                        "id_renamed_or_removed",
                        label,
                        f"{old_id!r} が HEAD に存在するが現版に無い",
                    )
                )
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="カタログ MD の IF-02 スキーマ契約を検査する（C1〜C12）"
    )
    parser.add_argument("path", nargs="?", help="カタログ MD。省略時は config.catalog_path()")
    parser.add_argument("--org", default=config.DEFAULT_ORG, help="組織スラグ（既定: %(default)s）")
    parser.add_argument("--no-git", action="store_true", help="C10（HEAD 比較）を実行しない")
    args = parser.parse_args(argv)

    try:
        path = Path(args.path) if args.path else config.catalog_path(args.org)
    except FileNotFoundError as exc:
        print(f"パス解決に失敗しました: {exc}", file=sys.stderr)
        return 3
    if not path.is_file():
        print(f"カタログが見つかりません: {path}", file=sys.stderr)
        return 3

    try:
        violations = check_catalog(path, use_git=not args.no_git)
    except OSError as exc:
        print(f"カタログの読み込みに失敗しました: {exc}", file=sys.stderr)
        return 3

    if violations:
        print(f"IF-02 カタログ契約に違反しています（{len(violations)} 件）。")
        print(f"対象: {path}")
        print()
        for violation in violations:
            print(violation.render())
        print()
        print("修正後、同じ検査は /retail-stats-verify と CI でも実行されます。")
        return 1

    print(f"IF-02 カタログ契約: pass（C1〜C12） 対象: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
