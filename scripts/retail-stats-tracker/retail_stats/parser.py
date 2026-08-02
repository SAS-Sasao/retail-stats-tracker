"""決定論パース本体（FR-04 / FR-05 / FR-11）。本システムの中核（実装設計 §4）。

DigestRow + Catalog → Observation[] + UnresolvedRow[]。
依存先: models, textnorm, catalog, period。store には依存しない
（永続化を知らない。実装設計 §2.3 — parser を永続化から切り離すことで
「タイトル文字列 → Observation」の純関数テストとして書ける）。

基本方針（実装設計 §4.3.1）: 節（、・。）で分割してから指標を探す方式は
「指標を含まない節」が混ざると破綻するため不採用。**数値トークンを先に
全て見つけ、各数値から左方向に指標別名を探す**（左窓アンカー方式）。

左窓の定義 = 「直前の数値トークンの終端」または「節区切り」または
「/ の直後」のうち最も右にある位置から、当該数値トークンの開始位置まで。

テストは implementation-design.md §7.2 T-4（複数指標分解）・T-7（発表主体）・
T-8（スコープ分類・主語位置ガード）・T-10h〜j を参照。
tests/test_parser.py に対応する。
"""

from __future__ import annotations

import re
from datetime import date

from retail_stats.models import Catalog, DigestRow, Observation, UnresolvedRow

CONFIDENCE_THRESHOLD = 0.70

# --- 値トークン -----------------------------------------------------------
# 「1.6%減」「29.8%増」「5.3%上昇」（方向語なしも許容）
VALUE_PCT_RE = re.compile(
    r"(?P<num>[0-9]+(?:\.[0-9]+)?)%"
    r"(?P<dir>増加|減少|上昇|下落|増収|減収|増益|減益|増|減|高|安|プラス|マイナス)?"
)

# 「233億円」「1兆4505億円」「4560億1000万円」「1兆円」「31億8500万円」「約1.5兆円」
_JPY_NUM = r"[0-9]+(?:\.[0-9]+)?"
VALUE_JPY_RE = re.compile(
    rf"(?<![0-9.])"
    rf"(?:(?P<cho>{_JPY_NUM})兆)?(?:(?P<oku>{_JPY_NUM})億)?(?:(?P<man>{_JPY_NUM})万)?円"
)

# --- 方向語（値に符号を与える） --------------------------------------------
POSITIVE_DIR = {"増", "増加", "上昇", "高", "プラス", "増収", "増益"}
NEGATIVE_DIR = {"減", "減少", "下落", "安", "マイナス", "減収", "減益"}

# --- 割・半減（カタログ §4.1） ---------------------------------------------
WARI_RE = re.compile(r"(?P<n>[0-9]+(?:\.[0-9]+)?)割(?P<dir>増|減)")
HANGEN_RE = re.compile(r"半減")

# --- 連続記録表現（カタログ §4.1） -----------------------------------------
STREAK_BROKEN_RE = re.compile(r"(?P<n>[0-9]+)カ月ぶり(?:に|の)?(?:前年割れ|前年同月割れ)")

# --- 定性表現のみ（value 化不可、sign_only を立てる） -----------------------
QUALITATIVE_RE = re.compile(r"(?P<a>増収|減収)(?P<b>増益|減益)?|(?P<c>増益|減益)")

# --- 横ばい（値 0.0 + 要出典確認） ------------------------------------------
FLAT_RE = re.compile(r"横ばい")

# --- 節・窓の区切り ---------------------------------------------------------
CLAUSE_SEP_RE = re.compile(r"[、。・/:：]")


def to_jpy_oku(m: re.Match) -> float:
    """兆・億・万を億円単位の float に畳む（実装設計 §4.3.2）。

    1兆 = 10,000億、1万円 = 0.0001億円。旧実装が silent に誤値を返した
    8 パターン（implementation-design.md §7.2 T-3 JPY_CASES）を必ず回帰させる。
    """
    raise NotImplementedError


def resolve_segment(normalized_title: str, catalog: Catalog) -> tuple[object | None, float]:
    """業態を解決する（主語位置ガード込み）。戻り値は (Segment | None, confidence_penalty)。

    実装設計 §4.3.3「主語位置ガード」: カタログの汎用別名がタイトル本文に
    現れても、それが記事の主語（先頭の業態アンカー）でなければ採らない。
    個社決算記事や家計調査記事に含まれる業態語の誤マッチを防ぐ
    （implementation-design.md §7.2 T-8 SEGMENT_FALSE_POSITIVE_CASES）。

    例外: 発表主体名（「経済産業省」等）が主語の場合は、本文中の業態名
    （「小売業」等）を採る（AUTHORITY_HEAD 例外。同 T-8
    test_authority_head_exception_is_preserved、confidence penalty 0.05）。
    """
    raise NotImplementedError


def resolve_authority(window_text: str, source_name: str, segment) -> tuple[str, float]:
    """発表主体を解決する。戻り値は (source_authority, confidence_penalty)。

    記事本文中の発表主体マーカー（例:「経産省調べ」）がカタログ既定値を
    上書きする（implementation-design.md §7.2 T-7
    test_authority_override_by_article）。掲載媒体名（source_name。例: 「流通
    ニュース」）は source_authority に混入させない
    （同 test_source_name_is_not_authority）。
    """
    raise NotImplementedError


def resolve_scope(metric, segment, window_text: str) -> str:
    """既定スコープの上書き規則（実装設計 §3.3。ローダではなくパーサ側に置く）。

    1. window_text に「既存店」を含めば existing_store
    2. co-op × sales-amount-absolute は total_supply に上書き（カタログ §4.5）
    3. それ以外はカタログの既定スコープ（metric.default_scope）
    """
    raise NotImplementedError


def classify_scope(title: str, catalog: Catalog) -> str:
    """記事タイトルを in_scope / no_numeric / no_segment_match / out_of_scope
    のいずれかに分類する（実装設計 §7.2 T-8 SCOPE_CASES / 要件 7-15）。

    判定順序の回帰テスト（T-8 test_authority_marker_evaluated_before_company_rule）:
    発表主体マーカー（総務省等）の判定は個社ルールより先に評価すること。
    総務省の物価統計記事が個社扱いで黙って除外されてはならない。
    """
    raise NotImplementedError


def parse(row: DigestRow, catalog: Catalog) -> tuple[list[Observation], list[UnresolvedRow]]:
    """DigestRow 1 件から Observation[] と UnresolvedRow[] を生成する。

    手順（実装設計 §4.3.1 / §1.3 データフロー図）:
        1. textnorm.normalize(row.title)
        2. classify_scope() で対象内/対象外を判定。out_of_scope なら
           observation を作らず UnresolvedRow(reason_code="out_of_scope") へ
        3. resolve_segment() で業態アンカーを解決（主語位置ガード適用）
        4. VALUE_PCT_RE / VALUE_JPY_RE / WARI_RE 等で数値トークンを列挙
        5. 各数値トークンについて左窓を取り、指標別名を解決
        6. resolve_scope() / period.resolve() / resolve_authority() で
           残りのフィールドを解決し Observation を組み立てる
        7. 1 記事内に複数主体の値が併記される場合（U10）や、業態アンカー内で
           複数指標が衝突する場合は confidence を 0.30 に下げる
           （implementation-design.md §7.2 T-4 test_intra_title_collision_lowers_confidence）
        8. どの段階でも解決できなければ UnresolvedRow に対応する reason_code
           で退避する（silent に捨てない、FR-10）
    """
    raise NotImplementedError("実装設計 §4.3 の決定論パースアルゴリズムを実装する（M3）")
