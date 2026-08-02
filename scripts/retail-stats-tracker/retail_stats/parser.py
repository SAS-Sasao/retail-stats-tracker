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

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from retail_stats import period as period_mod
from retail_stats import textnorm
from retail_stats.models import Catalog, DigestRow, Metric, Observation, Segment, UnresolvedRow

CONFIDENCE_THRESHOLD = 0.70

# --- 値トークン（実装設計 §4.3.2）------------------------------------------
VALUE_PCT_RE = re.compile(
    r"(?P<num>[0-9]+(?:\.[0-9]+)?)%"
    r"(?P<dir>増加|減少|上昇|下落|増収|減収|増益|減益|増|減|高|安|プラス|マイナス)?"
)

# 各部は小数を許容する。整数限定にすると 1.5兆円 の整数部を捨てて 5兆円 に一致する。
_JPY_NUM = r"[0-9]+(?:\.[0-9]+)?"
VALUE_JPY_RE = re.compile(
    rf"(?<![0-9.])"
    rf"(?:(?P<cho>{_JPY_NUM})兆)?(?:(?P<oku>{_JPY_NUM})億)?(?:(?P<man>{_JPY_NUM})万)?円"
)

POSITIVE_DIR = {"増", "増加", "上昇", "高", "プラス", "増収", "増益"}
NEGATIVE_DIR = {"減", "減少", "下落", "安", "マイナス", "減収", "減益"}
# 「売上以外の語彙」で方向を表すものは 0.05 減点（§4.5）
_PLAIN_DIR = {"増", "減", "増加", "減少", "増収", "減収", "増益", "減益"}

WARI_RE = re.compile(r"(?P<n>[0-9]+(?:\.[0-9]+)?)割(?P<dir>増|減)")
HANGEN_RE = re.compile(r"半減")
STREAK_BROKEN_RE = re.compile(r"(?P<n>[0-9]+)カ月ぶり(?:に|の)?(?:前年割れ|前年同月割れ)")
QUALITATIVE_RE = re.compile(r"(?P<a>増収|減収)(?P<b>増益|減益)?|(?P<c>増益|減益)")
FLAT_RE = re.compile(r"横ばい")
CLAUSE_SEP_RE = re.compile(r"[、。・/:：]")

# --- 業態の解決（§4.3.3）---------------------------------------------------
AUTHORITY_HEAD_RE = re.compile(
    r"協会|連合会|組合|生協連|経済産業省|経産省|総務省|農水省|農林水産省|財務省|厚労省|国交省"
)

# --- 指標の解決（§4.3.4）---------------------------------------------------
METRIC_WINDOW_NEAR = 12
METRIC_WINDOW_FAR = 25

# --- 発表主体の解決（§4.3.6 / 要件 IF-02 発表主体対応表）-------------------
AUTHORITY_DETECTION: tuple[tuple[str, str], ...] = (
    ("経済産業省", "meti"),
    ("商業動態統計", "meti"),
    ("経産省調べ", "meti"),
    ("経産省", "meti"),
    ("総務省", "mic"),
    ("日本ショッピングセンター協会", "sc-association"),
    ("日本百貨店協会", "department-store-association"),
    ("日本チェーンストア協会", "chain-store-association"),
    ("日本フードサービス協会", "food-service-association"),
    ("日本生活協同組合連合会", "co-op-union"),
    ("日本生協連", "co-op-union"),
)

# --- スコープ外の分類（§4.3.7 の判定木）------------------------------------
AUTHORITY_MARKER_RE = re.compile(
    r"協会|連合会|組合|経済産業省|経産省|総務省|農水省|農林水産省|財務省|厚労省|国交省|統計|白書"
)
STAT_VOCAB_RE = re.compile(
    r"既存店|売上高|売上|販売額|客数|客単価|営業利益|営業収益|供給高|物価|市場規模|店舗数"
)


# 残余語が**この文字数以上**なら「未解決の残余語」とみなす（実装設計 §4.3.7）。
# 1 文字の取りこぼしを個社判定に使わないための閾値。
RESIDUAL_MIN_LENGTH = 2

# 残余語の判定で無視する助詞・記号（cc-sier #728）。
# これらしか残らなければ「修飾語なし」とみなす。
_FILLER_RE = re.compile(r"[のはがをにでとやもへ、。・：:／/｜|（）()「」\s　＝=~\-—–]")

# **比較基準語**。`前年度比5.8%増` の `前年度比` は「何と比べたか」を示す語であり、
# 主語を別のものに差し替える修飾語ではない。業態名でも指標名でもないため
# 残余語の判定から除く（cc-sier #728 の「不明語」には当たらない）。
# 業態名・指標名ではないので、ここに置いてもカタログ駆動（FR-03）に反しない。
_COMPARISON_BASIS_RE = re.compile(r"前年同月比|前年度比|前年比|前月比|前期比|前年同期比|同月比")


@dataclass(frozen=True)
class ParseResult:
    """1 行のパース結果。observations と unresolved は排他ではない。"""

    observations: tuple[Observation, ...]
    unresolved: tuple[UnresolvedRow, ...]


@dataclass(frozen=True)
class _Value:
    """値トークン 1 つ。左窓の切り出しに位置を使う。"""

    start: int
    end: int
    value: float
    unit: str          # percent_yoy / jpy_oku
    penalty: float
    raw: str


def to_jpy_oku(m: re.Match) -> float:
    """兆・億・万を億円単位の float に畳む。1兆 = 10,000億、1万円 = 0.0001億円。"""
    total = 0.0
    if m.group("cho"):
        total += float(m.group("cho")) * 10000
    if m.group("oku"):
        total += float(m.group("oku"))
    if m.group("man"):
        total += float(m.group("man")) * 0.0001
    return total


def _subject_head(norm_title: str) -> str:
    """主語位置 = 「/」より前。「/」が無ければ最初の読点より前（§4.3.3）。"""
    if "/" in norm_title:
        return norm_title.split("/", 1)[0]
    if "、" in norm_title:
        return norm_title.split("、", 1)[0]
    return norm_title


def resolve_segment(norm_title: str, catalog: Catalog) -> tuple[Segment | None, float]:
    """業態と confidence ペナルティを返す（§4.3.3）。

    **業態別名は主語位置で一致しなければならない。** カタログの別名には
    `外食` `百貨店` `コンビニ` のような汎用語が含まれるため、どこでも一致を
    許すと業態が主語でない記事（個社決算・家計調査）を誤って取り込む。
    実測 7 件がこのガードで防がれ、うち 3 件は「抽出成功」に数えられていた。
    """
    head = _subject_head(norm_title)
    for alias, seg_id in catalog.segment_alias_index():   # 長さ降順
        if alias in head:
            return catalog.segment(seg_id), 0.00
    # 主語が発表主体そのものなら本文中の業態名を採る。
    # 例: 「経済産業省／2月の商業動態統計、小売業販売額は0.2％減…」
    if AUTHORITY_HEAD_RE.search(head):
        for alias, seg_id in catalog.segment_alias_index():
            if alias in norm_title:
                return catalog.segment(seg_id), 0.05
    return None, 0.00


def resolve_metric(
    window: str, catalog: Catalog, value_type: str | None = None
) -> tuple[Metric | None, float, str]:
    """左窓から最長一致で指標を解決する（§4.3.4）。

    長さ降順の索引で `rfind`（右端優先）を使うことで、
    `6月の総売上高233億円、既存店売上2.3%減` の 2 番目の値に対して
    `既存店売上` が `売上高` より先に一致する。

    `value_type` を渡すと、その型の指標だけを候補にする。カタログ §2.2 が
    「絶対額か率かでさらに分岐」と定めているとおり、**率の値を絶対額の指標に
    入れてはならない**。`日本百貨店協会／3月の売上高3.2％増` の `売上高` は
    `sales-amount-absolute`（単位 jpy_oku）の別名でもあるため、型で絞らないと
    **% の値が億円単位の指標に入る**（単位不整合のまま observations に蓄積し、
    例外にならない = §1.2 の silent accumulation）。golden-60 が実際に検出した。
    """
    for alias, metric_id in catalog.metric_alias_index():   # 長さ降順
        idx = window.rfind(alias)
        if idx < 0:
            continue
        if value_type is not None and catalog.metric(metric_id).value_type != value_type:
            continue
        distance = len(window) - (idx + len(alias))
        if distance <= METRIC_WINDOW_NEAR:
            return catalog.metric(metric_id), 0.00, alias
        if distance <= METRIC_WINDOW_FAR:
            return catalog.metric(metric_id), 0.10, alias
    return None, 0.00, ""


def resolve_scope(metric: Metric, segment: Segment, window_text: str) -> str:
    """スコープ解決（実装設計 §3.3）。

    §2.2 の「記事に既存店の文字列が無ければ既存店指標として扱わない」判定は
    `existing-store-sales-yoy` への**昇格を禁じる**ものであって、既定スコープの
    適用そのものを禁じてはいない（§9.3 D4）。
    """
    if "既存店" in window_text:
        return "existing_store"
    if segment.segment_id == "co-op" and metric.metric_id == "sales-amount-absolute":
        return "total_supply"
    return metric.default_scope


def resolve_authority(norm_title: str, norm_summary: str, segment: Segment) -> tuple[str, float]:
    """(source_authority, ペナルティ) を返す（§4.3.6）。

    掲載媒体（流通ニュース / DCS）と発表主体（協会 / 経産省）は別物。
    natural key に入るのは後者のみ。
    """
    haystack = norm_title + "\x1f" + norm_summary
    for word, code in AUTHORITY_DETECTION:
        if word in haystack:
            return code, 0.00
    return segment.source_authority, 0.00   # 定義上の既定であり推測ではない


def classify_unresolved(norm_title: str, has_value: bool, has_qualitative: bool) -> str:
    """業態が解決できなかった行の分類（§4.3.7 の判定木）。

    `AUTHORITY_MARKER` を最初に評価する順序が要点。この順序でないと
    `4月都内物価…総務省` のようなカタログに業態行が不足しているケースが
    個社扱いで黙って除外され、カタログ改善の signal が消える。
    """
    if AUTHORITY_MARKER_RE.search(norm_title):
        return "no_segment_match"
    if STAT_VOCAB_RE.search(norm_title) and (has_value or has_qualitative):
        return "out_of_scope"       # 個社開示
    return "out_of_scope"           # 統計記事ではない


def _collect_values(norm: str) -> list[_Value]:
    """値トークンを位置つきで列挙する。重なりは先に見つけた方を優先する。"""
    found: list[_Value] = []
    for m in VALUE_PCT_RE.finditer(norm):
        direction = m.group("dir")
        sign = -1.0 if direction in NEGATIVE_DIR else 1.0
        penalty = 0.00 if direction in _PLAIN_DIR else 0.05
        found.append(
            _Value(m.start(), m.end(), sign * float(m.group("num")), "percent_yoy", penalty, m.group(0))
        )
    for m in VALUE_JPY_RE.finditer(norm):
        # 全構成要素が任意のため空文字にも一致しうる。必ず絞り込む（§4.3.2）
        if not any(m.group(g) for g in ("cho", "oku", "man")):
            continue
        if any(v.start < m.end() and m.start() < v.end for v in found):
            continue
        found.append(_Value(m.start(), m.end(), to_jpy_oku(m), "jpy_oku", 0.05, m.group(0)))
    for m in WARI_RE.finditer(norm):
        if any(v.start < m.end() and m.start() < v.end for v in found):
            continue
        sign = 1.0 if m.group("dir") == "増" else -1.0
        found.append(_Value(m.start(), m.end(), sign * float(m.group("n")) * 10.0, "percent_yoy", 0.10, m.group(0)))
    for m in HANGEN_RE.finditer(norm):
        if any(v.start < m.end() and m.start() < v.end for v in found):
            continue
        found.append(_Value(m.start(), m.end(), -50.0, "percent_yoy", 0.10, m.group(0)))
    found.sort(key=lambda v: v.start)
    return found


def residual_after_known_terms(window: str, metric_alias: str, catalog: Catalog) -> str:
    """左窓から**既知の語**を取り除いた残りを返す（cc-sier #728 の判定基準）。

    取り除くのは 指標別名 / 業態別名 / 期間表現 / 助詞・記号。残ったものが
    「指標別名・業態別名・期間表現のいずれにも該当しない残余語」である。

        `2月既存店売上ツルハ` → 既存店売上 と 2月 を除去 → **`ツルハ`** が残る
        `4月の販売額は`       → 販売額 と 4月 を除去   → 残余なし

    前者は個社の並記（値は業態の観測値ではない）、後者は業態内の内訳。
    §4.3.3 の主語位置ガードが「主語の位置」で個社を弾くのに対し、
    こちらは「値の直前の修飾語」で弾く。
    """
    text = window
    if metric_alias:
        text = text.replace(metric_alias, "")
    for alias, _seg_id in catalog.segment_alias_index():   # 長さ降順
        text = text.replace(alias, "")
    text = period_mod.strip_period_expressions(text)
    text = _COMPARISON_BASIS_RE.sub("", text)
    text = _FILLER_RE.sub("", text)
    if not text:
        return ""
    # 残余が業態別名の一部（短縮形）なら業態への言及であって不明語ではない。
    # `小売業販売額` の `小売業` はカタログの別名 `小売業全体` の短縮形であり、
    # 設計 §4.3.6 はこの行を meti-commerce-dynamics の正当な観測例としている。
    # カタログに短縮形の別名が無いことを、パーサ側で誤判定に変えない。
    for alias, _seg_id in catalog.segment_alias_index():
        if text in alias:
            return ""
    return text


def _left_window(norm: str, start: int, prev_end: int) -> str:
    """左窓を切り出す（§4.3.1）。

    「直前の数値トークンの終端」「節区切り」「/ の直後」のうち
    最も右にある位置から、当該数値トークンの開始位置まで。
    """
    lo = prev_end
    for m in CLAUSE_SEP_RE.finditer(norm, 0, start):
        lo = max(lo, m.end())
    return norm[lo:start]


def _observation_id(article_id: str, natural_key: str) -> str:
    return hashlib.sha256(f"{article_id}\x1f{natural_key}".encode()).hexdigest()[:16]


def _make(
    segment: Segment, metric: Metric, scope: str, authority: str, per, value, unit,
    raw: str, article_id: str, confidence: float, digest_date: str,
    streak: int | None = None, sign_only: str | None = None, needs_check: bool = False,
) -> Observation:
    key = "\x1f".join((segment.segment_id, metric.metric_id, scope, per.period_key, authority))
    return Observation(
        observation_id=_observation_id(article_id, key),
        segment_id=segment.segment_id, metric_id=metric.metric_id, scope=scope,
        source_authority=authority, period_key=per.period_key, period_type=per.period_type,
        period_start=per.period_start, period_end=per.period_end,
        value=value, unit=unit, streak_broken_months=streak, sign_only=sign_only,
        needs_source_check=needs_check, raw_expression=raw, article_id=article_id,
        extraction_method="deterministic", confidence=round(confidence, 2),
        manual_override=False, first_seen_date=digest_date, last_updated_date=digest_date,
    )


def detect_collision(obs: list[Observation]) -> bool:
    """intra-title の natural key 衝突（§4.3.5）。

    `ファミレス／6月既存店すかいらーく1.7％増、サイゼリヤ9.7％増` は素朴に
    処理すると同一キーが 2 回生成され、片方が他方を silent に上書きする。
    """
    keys = [o.natural_key() for o in obs]
    return len(keys) != len(set(keys))


def _unresolved(row: DigestRow, article_id: str, reason: str) -> UnresolvedRow:
    return UnresolvedRow(
        id=hashlib.sha256(f"{article_id}\x1f{reason}".encode()).hexdigest()[:16],
        digest_date=row.digest_date, raw_line=row.raw_line, reason_code=reason,
        last_attempted_at=row.digest_date,   # 実行時刻を持ち込まない（NFR-06）
    )


def parse_row(row: DigestRow, catalog: Catalog, article_id: str) -> ParseResult:
    """1 行を Observation[] または UnresolvedRow[] に解決する。

    値の解釈のみを行い、永続化・重複排除は一切知らない（§2.3）。
    """
    norm = textnorm.normalize(row.title)
    norm_summary = textnorm.normalize(row.summary)
    pub = date.fromisoformat(row.digest_date)

    values = _collect_values(norm)
    qualitative = QUALITATIVE_RE.search(norm)
    flat = FLAT_RE.search(norm)

    segment, seg_penalty = resolve_segment(norm, catalog)
    if segment is None:
        reason = classify_unresolved(norm, bool(values), bool(qualitative))
        return ParseResult((), (_unresolved(row, article_id, reason),))

    if not values and not qualitative and not flat:
        return ParseResult((), (_unresolved(row, article_id, "no_numeric"),))

    # **指標の解決を期間より先に評価する。** §4.3.7 の判定木は period を含まず、
    # 「値はあるが指標が解決できない」を no_metric_match と定めている。期間を
    # 先に見ると、指標も期間も無いランキング記事（`食品スーパー決算ランキング2026
    # "1兆円クラブ"入り…`）が ambiguous_period に落ち、設計が no_metric_match の
    # 例として挙げている分類と食い違う。
    matched: list[tuple[_Value, Metric, float, str]] = []
    unmatched_values = 0
    has_unknown_modifier = False
    prev_end = 0
    for token in values:
        window = _left_window(norm, token.start, prev_end)
        prev_end = token.end
        want = "ratio" if token.unit == "percent_yoy" else "absolute"
        metric, metric_penalty, alias = resolve_metric(window, catalog, want)
        if metric is None:
            unmatched_values += 1
            continue
        # **値の直前に未知の修飾語があれば、その値は業態の観測値としない**
        # （cc-sier #728）。`ドラッグストア／…ツルハ4.0%増` の `ツルハ` が該当。
        if len(residual_after_known_terms(window, alias, catalog)) >= RESIDUAL_MIN_LENGTH:
            has_unknown_modifier = True
            continue
        matched.append((token, metric, metric_penalty, window))

    # (a) 個社の並記 — 行全体を company_disclosure に落とす（実装設計 §4.3.7）。
    #     業態は解決できているが値の主語が個社なので、`out_of_scope`（業態が
    #     解決できなかった行）とは別コードで区別する。どちらも分母からは外れる。
    if has_unknown_modifier:
        return ParseResult((), (_unresolved(row, article_id, "company_disclosure"),))

    if not matched and not qualitative and not flat:
        return ParseResult((), (_unresolved(row, article_id, "no_metric_match"),))

    per, period_penalty = period_mod.resolve_with_penalty(norm, pub)
    if per is None:
        return ParseResult((), (_unresolved(row, article_id, "ambiguous_period"),))

    authority, auth_penalty = resolve_authority(norm, norm_summary, segment)
    base = seg_penalty + period_penalty + auth_penalty

    observations: list[Observation] = []
    for token, metric, metric_penalty, window in matched:
        # 左窓を渡す。タイトル全体を渡すと
        # `百貨店／3月の販売額2.2％増の5547億円、既存店は3.4％増` の「販売額」まで
        # 既存店扱いになる（別の節にある「既存店」に引きずられる）。
        scope = resolve_scope(metric, segment, window)
        observations.append(_make(
            segment, metric, scope, authority, per, token.value, metric.unit,
            token.raw, article_id, 1.00 - (base + metric_penalty + token.penalty), row.digest_date,
        ))

    # 定性表現のみ（増収増益 等）→ 営業収益 / 営業利益 の 2 レコード（§4.3.5）
    if not observations and qualitative:
        pairs = []
        if qualitative.group("a"):
            pairs.append(("operating-revenue-yoy", "+" if qualitative.group("a") == "増収" else "-"))
        if qualitative.group("b"):
            pairs.append(("operating-profit-yoy", "+" if qualitative.group("b") == "増益" else "-"))
        if qualitative.group("c"):
            pairs.append(("operating-profit-yoy", "+" if qualitative.group("c") == "増益" else "-"))
        for metric_id, sign in pairs:
            metric = catalog.metric(metric_id)
            observations.append(_make(
                segment, metric, resolve_scope(metric, segment, norm), authority, per,
                None, metric.unit, qualitative.group(0), article_id,
                1.00 - (base + 0.40), row.digest_date, sign_only=sign, needs_check=True,
            ))

    # 横ばい → 直近の指標に value 0.0（§4.3.5）
    if not observations and flat:
        metric, metric_penalty, _alias = resolve_metric(norm[: flat.start()], catalog)
        if metric is not None:
            observations.append(_make(
                segment, metric, resolve_scope(metric, segment, norm), authority, per,
                0.0, metric.unit, flat.group(0), article_id,
                1.00 - (base + metric_penalty + 0.35), row.digest_date, needs_check=True,
            ))

    if not observations:
        reason = "no_metric_match" if (values or qualitative or flat) else "no_numeric"
        return ParseResult((), (_unresolved(row, article_id, reason),))

    # 連続記録（§4.3.5）。value < 0 かつ ratio のものに付与。
    # 該当が複数なら display_order 最小 → カタログ記載順が先、で決定論的に選ぶ。
    streak = STREAK_BROKEN_RE.search(norm)
    if streak:
        order = {m.metric_id: i for i, m in enumerate(catalog.metrics)}
        targets = [
            (i, o) for i, o in enumerate(observations)
            if o.value is not None and o.value < 0 and catalog.metric(o.metric_id).value_type == "ratio"
        ]
        if targets:
            idx, chosen = min(
                targets,
                key=lambda t: (catalog.segment(t[1].segment_id).display_order, order[t[1].metric_id]),
            )
            observations[idx] = _make(
                catalog.segment(chosen.segment_id), catalog.metric(chosen.metric_id), chosen.scope,
                chosen.source_authority, per, chosen.value, chosen.unit, chosen.raw_expression,
                article_id, chosen.confidence, row.digest_date, streak=int(streak.group("n")),
            )

    # (b) 業態としては正当だが指標を解決できなかった値を**必ず退避する**。
    #     FR-10 は無条件の絶対条件であり、observation にも unresolved にも
    #     現れない値を残さない（cc-sier #728）。将来カタログに内訳カテゴリを
    #     追加すれば回収できる形で残す。
    leftovers: tuple[UnresolvedRow, ...] = ()
    if unmatched_values and observations:
        leftovers = (_unresolved(row, article_id, "no_metric_match_in_multi_value"),)

    if detect_collision(observations):
        # 衝突は silent な上書きを生む。閾値未満に固定して LLM へ回す（§4.3.5）
        observations = [
            _make(
                catalog.segment(o.segment_id), catalog.metric(o.metric_id), o.scope,
                o.source_authority, per, o.value, o.unit, o.raw_expression, article_id,
                0.30, row.digest_date, streak=o.streak_broken_months,
                sign_only=o.sign_only, needs_check=o.needs_source_check,
            )
            for o in observations
        ]

    return ParseResult(tuple(observations), leftovers)
