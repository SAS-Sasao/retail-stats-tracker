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

from pathlib import Path

from retail_stats.models import DigestRow

SECTION_KEYWORD = "決算・統計"

DIGEST_COLUMNS: dict[str, tuple[str, ...]] = {
    "index": ("#", "No", "番号"),
    "article": ("記事", "タイトル", "Article"),
    "source": ("ソース", "出典", "Source"),
    "summary": ("要約", "概要", "Summary"),
}


def split_table_row(line: str) -> list[str]:
    """`|` 分解 + 前後空白除去（parse-wbs.py split_table_row の移植）。"""
    raise NotImplementedError


def is_separator_row(cells: list[str]) -> bool:
    """`^:?-+:?$` によるセパレータ行判定（parse-wbs.py is_separator_row の移植）。"""
    raise NotImplementedError


def parse_file(path: Path, digest_date: str) -> tuple[list[DigestRow], list]:
    """1 日分の日次ダイジェスト MD から「決算・統計」章の表行を抽出する。

    戻り値は (DigestRow のリスト, 未解決行のリスト)。章が存在しない日は
    空リストを返す（例外にしない。要件 7-1、`files_without_section` に計上）。
    """
    raise NotImplementedError("実装設計 §4.1 の走査規則を実装する")
