"""表記ゆれ正規化（FR-05）。実装設計 §4.2。依存なし・副作用なし。

正規化は以下の順序で適用すること（順序を変えると結果が変わるため
テストで順序を固定する。実装設計 §4.2）:
    1. NFKC 正規化（全角％→%、全角数字→半角、／→/、（）→()、＝→=、＆→&）
    2. NFKC が触らない波ダッシュ・ダッシュ類の ASCII 化（〜/～→~、－/―/–→-）
    3. カ月表記の統一（カ/ヶ/ヵ/か → カ）
    4. 数値内・数値と単位の間に混入した空白の除去
    5. 数値の桁区切りカンマの除去

**桁区切りカンマの終端条件に `\\b` を使ってはならない**（実装設計 §4.2 の
落とし穴）。Python の `re` は CJK 文字を単語構成文字として扱うため、
`4,505億円` の `505` と `億` の間に単語境界が存在せず、`(?=[0-9]{3}\\b)`
は実データで発火しない。`(?=[0-9]{3}(?![0-9]))` を使うこと。このバグは
例外にも未解決行にもならず、カンマ分断された誤った小さい値が
警告なしに observations.json へ蓄積する（例: `1兆4,505億円` を `505.0`
として誤取込み。正しくは `14505.0`）。

テストは implementation-design.md §7.2 T-3（test_normalize_table /
test_jpy_conversion）を参照。tests/test_textnorm.py に対応する。
"""

from __future__ import annotations

import re
import unicodedata

_KA_MONTH_RE = re.compile(r"[ヶヵカか](?=月)")
_SP_IN_NUM_RE = re.compile(r"(?<=[0-9])\s+(?=[0-9])")
_SP_BEFORE_UNIT_RE = re.compile(r"(?<=[0-9])\s+(?=[月%期年日度億兆万円])")
_SP_BEFORE_PCT_RE = re.compile(r"\s+(?=%)")
# 桁区切りカンマ。終端条件に \b を使ってはならない（モジュール docstring の落とし穴）。
# `(?![0-9])` は「3 桁のあとに数字が続かない」= 桁区切りとして正しい位置、を表す。
_THOUSAND_SEP_RE = re.compile(r"(?<=[0-9]),(?=[0-9]{3}(?![0-9]))")


def normalize(s: str) -> str:
    """§4.2 の5段階正規化を適用した文字列を返す。元の文字列は変更しない。

    呼び出し側（parser.py）は正規化後の文字列でのみ値抽出を行う。
    ただし `SourceArticle.title_first_seen` / `title_variants` は
    正規化前の原文で保持すること（実装設計 §4.2「元のタイトルは破棄しない」）。
    """
    # 1) NFKC: 全角％→%、全角数字→半角、／→/、（）→()、＝→=、＆→& を一括で吸収
    s = unicodedata.normalize("NFKC", s)
    # 2) NFKC が触らない波ダッシュ・ダッシュ類を ASCII に寄せる
    s = s.replace("〜", "~").replace("～", "~")
    s = s.replace("－", "-").replace("―", "-").replace("–", "-")
    # 3) カ月表記の統一（カ / ヶ / ヵ / か → カ）
    s = _KA_MONTH_RE.sub("カ", s)
    # 4) 数値内・数値と単位の間に混入した空白を除去
    s = _SP_IN_NUM_RE.sub("", s)
    s = _SP_BEFORE_UNIT_RE.sub("", s)
    s = _SP_BEFORE_PCT_RE.sub("", s)
    # 5) 数値の桁区切りカンマを除去（"1兆4,505億円" → "1兆4505億円"）
    #    先読み・後読みはいずれも零幅なので、"12,345,678円" のように
    #    カンマが連なる場合も 1 回の sub で全て除去される（T-3 で固定）。
    s = _THOUSAND_SEP_RE.sub("", s)
    return s
