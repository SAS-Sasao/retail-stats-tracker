#!/usr/bin/env python3
"""golden-60 の**候補**を機械的に選定する（ループ設計 §3.3 規律 G1）。

G1 は 2 つのことを別々に要求している。本スクリプトが担うのは前者だけである。

| G1 の要求 | 担当 |
|---|---|
| 「選定基準（**偏りが評価を無効化するため、機械的に決める**）」 | **本スクリプト** |
| 「期待される observation を**人手で確定**して凍結する」 | **人間（オーナー）** |

**期待値は自動で埋めない。** golden-60 はパーサを評価するための正解データであり、
期待値を機械が推測して入れると「実装に引きずられた期待値」になって評価が成立しない。
G1 が「パーサのコードを 1 行も書く前に完了させる」と定めているのは同じ理由である。
本スクリプトは各行に `expected: null` と `status: "needs_human_review"` を置き、
どの区分の枠として選ばれたか（`bucket`）と選定根拠（`selected_because`）だけを添える。

出力: JSONL（1 行 1 候補）。オーナーが `expected` を埋め、`status` を `"confirmed"` に
してから `tests/fixtures/golden-60.jsonl` として凍結する。

使用例:
    RETAIL_STATS_WORKSPACE=/path/to/cc-sier-organization \\
    python3 scripts/retail-stats-tracker/tests/make_golden60.py \\
      --until 2026-07-26 \\
      --out scripts/retail-stats-tracker/tests/fixtures/golden-60.candidates.jsonl

`--until` は G1 の母集団（計測日 2026-07-26 の 595 行）を再現するためにある。
指定しないと日次ダイジェストが増えるたびに選定結果が変わり、凍結の意味が失われる。

母集団は「一意 URL の**代表 variant**」（実装設計 §4.7 の選択規則）とする。
595 行の延べには同一記事の再掲が含まれ、そのまま選ぶと同じ記事が複数枠を占めうるため。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_stats import catalog as catalog_mod  # noqa: E402
from retail_stats import config, digest, textnorm  # noqa: E402

# G1 の選定基準表（区分 → 件数）。合計 60。
BUCKETS: tuple[tuple[str, int, str], ...] = (
    ("major4_existing_store", 16, "主要 4 業態（SC / 百貨店 / チェーンストア / コンビニ）の月次既存店指標"),
    ("multi_metric", 8, "複数指標を含む記事（FR-11）"),
    ("period_all_5_types", 8, "期間表記の全 5 種（月次 / 決算期 / 四半期 / 半期 / 年度）"),
    ("notation_variants", 6, "表記ゆれ（全角％ / 半角% / 全角数字 / カ月・ヶ月）"),
    ("qualitative_and_streak", 6, "定性表現のみ（増収増益 / 横ばい）と連続記録（51カ月ぶりに前年割れ）"),
    ("multi_authority", 4, "発表主体が並立する行（経産省調べ と 協会統計）"),
    ("no_numeric", 4, "数値が取れないことが正解の行（期待値 = unresolved / no_numeric）"),
    ("out_of_scope", 6, "対象範囲外が正解の行（うち 2 件は真の取りこぼし = no_segment_match）"),
)

MAJOR4 = ("shopping-center", "department-store", "chain-store", "convenience-store")

_NUM_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_PCT_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?%")
_AUTHORITY_MARKER_RE = re.compile(r"経産省調べ|経済産業省|商業動態統計|総務省")
_QUALITATIVE_RE = re.compile(r"増収|減収|増益|減益|横ばい")
_STREAK_RE = re.compile(r"[0-9]+カ月ぶり")
# 値トークン = 率（%）または金額（兆/億/万円）。日付や件数は値ではない。
_VALUE_TOKEN_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?%|[0-9]+(?:\.[0-9]+)?(?:兆|億|万)?円")

# 期間表記の 5 種（カタログ §4.2）。normalize 後の文字列に当てる。
#   月次   = 「6月」「2026年6月度」
#   決算期 = 「◯◯年◯月期」（決算期末月）
#   四半期 = 「3〜5月」「第1四半期」（**幅 3 か月**）
#   半期   = 「1〜6月期」「上期」「中間」（**幅 6 か月**）
#   年度   = 「2025年度」「通期」
#
# **`N~M月` 系は「期」の有無ではなく幅で分ける。** 当初 half を
# `[0-9]{1,2}~[0-9]{1,2}月期` としていたが、これは `1~3月期`（第1四半期）にも
# 一致する。実測では half 判定 7 件のうち実際に半期だったのは 1 件だけで、
# G1 の「全 5 種」が名目だけになっていた。カタログ §4.2 が half の例に挙げるのは
# `1〜6月期` であり、区別しているのは**期間の幅**である。
_RANGE_RE = re.compile(r"(?P<a>[0-9]{1,2})~(?P<b>[0-9]{1,2})月")
_QUARTER_WORD_RE = re.compile(r"第[1-4]四半期|[1-4]Q")
_HALF_WORD_RE = re.compile(r"上期|下期|上半期|下半期|中間期?")
_FISCAL_YEAR_RE = re.compile(r"[0-9]{2,4}年度|通期")
_FISCAL_PERIOD_RE = re.compile(r"(?:[0-9]{2,4}年)?[0-9]{1,2}月期")
_MONTH_RE = re.compile(r"(?:[0-9]{4}年)?[0-9]{1,2}月")

PERIOD_KINDS = ("month", "fiscal_period", "quarter", "half", "fiscal_year")

# 月次統計記事らしさ / ランキング記事（未決事項 (c) の対象）
_STATISTICS_RE = re.compile(r"統計|月次|月度|既存店|販売額|売上|客数|客単価|供給高|物価|市場規模")
_RANKING_RE = re.compile(r"ランキング|週刊")


def _span_months(a: int, b: int) -> int:
    """開始月 a から終了月 b までの月数（年またぎを許容）。9~2月 → 6。"""
    return (b - a) % 12 + 1


def period_kind(norm: str) -> str | None:
    """期間表記を カタログ §4.2 の 5 種に分類する。判定できなければ None。"""
    if _HALF_WORD_RE.search(norm):
        return "half"
    if _QUARTER_WORD_RE.search(norm):
        return "quarter"
    m = _RANGE_RE.search(norm)
    if m:
        span = _span_months(int(m.group("a")), int(m.group("b")))
        if span == 3:
            return "quarter"
        if span == 6:
            return "half"
        return None          # 9 か月累計など。5 種のいずれでもない
    if _FISCAL_YEAR_RE.search(norm):
        return "fiscal_year"
    if _FISCAL_PERIOD_RE.search(norm):
        return "fiscal_period"
    if _MONTH_RE.search(norm):
        return "month"
    return None


def month_hint(norm: str) -> str | None:
    """対象月の手がかり（発表主体の並立ペアを組むためのグルーピングキー）。"""
    m = re.search(r"(?<![0-9~])([0-9]{1,2})月(?!期)", norm)
    return m.group(1) if m else None


def representative(titles: list[str]) -> str:
    """§4.7 の代表 variant 選択（数値トークン数 → 長さ → 辞書順）。走査順に依存しない。"""
    return max(titles, key=lambda t: (len(_NUM_RE.findall(textnorm.normalize(t))), len(t), t))


def classify(raw: str, norm: str, cat) -> dict:
    """1 行の特徴量を出す。**期待値ではない**（どの区分の候補になりうるかの判定材料）。

    表記ゆれ（全角％ / 全角数字 / ヶ・ヵ月）は **`raw`（原文）で判定する**。
    `norm` は NFKC 正規化済みで全角％が半角% に、`ヶ月` が `カ月` に潰れており、
    正規化後の文字列から表記ゆれを探しても構造的に 0 件になる。
    それ以外の特徴（業態別名・数値・期間）は正規化後で判定する。
    """
    seg_hits = [sid for alias, sid in cat.segment_alias_index() if alias in norm]
    return {
        "segment_alias_hits": sorted(set(seg_hits)),
        "pct_tokens": len(_PCT_RE.findall(norm)),
        "numeric_tokens": len(_NUM_RE.findall(norm)),
        "value_tokens": len(_VALUE_TOKEN_RE.findall(norm)),
        "has_existing_store": "既存店" in norm,
        "has_authority_marker": bool(_AUTHORITY_MARKER_RE.search(norm)),
        "has_qualitative": bool(_QUALITATIVE_RE.search(norm)),
        "has_streak": bool(_STREAK_RE.search(norm)),
        "period_kind": period_kind(norm),
        "is_statistics_like": bool(_STATISTICS_RE.search(norm)),
        "is_ranking": bool(_RANKING_RE.search(norm)),
        # --- ここから下は原文で見る ---
        "has_fullwidth_pct": "％" in raw,
        "has_halfwidth_pct": "%" in raw,
        "has_fullwidth_digit": bool(re.search(r"[０-９]", raw)),
        "has_kagetsu_variant": bool(re.search(r"[ヶヵか]月", raw)),
    }


def _sort_key(item: dict) -> tuple:
    """**ドメインで層化してから** URL 昇順。

    素の URL 昇順はドメインのアルファベット順と一致するため（`https://d…` <
    `https://n…` < `https://www.ryutsuu…`）、候補が豊富な区分ほど 1 ドメインに
    偏る。実測では diamond-rm.net が母集団 17.5% に対し選定 46.7% を占め、
    協会統計・経産省統計のほぼ全てを供給する流通ニュースが 57.6% → 33.3% に
    沈んでいた。各ドメイン内の順位を第 1 キーにすると、決定論を保ったまま
    ドメインを巡回する。
    """
    return (item["_domain_rank"], item["_domain"], item["url"])


def annotate_ranks(candidates: list[dict]) -> None:
    """各候補に、同一ドメイン内での順位を付ける（層化サンプリングのため）。"""
    by_domain: dict[str, int] = {}
    for item in sorted(candidates, key=lambda c: c["url"]):
        domain = re.sub(r"https?://([^/]+)/.*", r"\1", item["url"])
        item["_domain"] = domain
        item["_domain_rank"] = by_domain.get(domain, 0)
        by_domain[domain] = item["_domain_rank"] + 1


def pick(candidates: list[dict], predicate, count: int, bucket: str, why: str, taken: set) -> list[dict]:
    """条件に合う候補から count 件を決定論的に選ぶ（ドメイン層化。乱数を使わない）。"""
    chosen = []
    for item in sorted(candidates, key=_sort_key):
        if len(chosen) >= count:
            break
        if item["url"] in taken or not predicate(item):
            continue
        taken.add(item["url"])
        chosen.append({**item, "bucket": bucket, "selected_because": why})
    return chosen


def _subject_first(item: dict) -> int:
    """業態別名が**タイトル冒頭**に来ているか（0 = 来ている / 1 = 来ていない）。

    設計 §4.3.3 の主語位置ガードと同じ考え方。`日本百貨店協会／3月の売上高…` は
    協会そのものが主語だが、`大手百貨店／3月売上高 三越伊勢丹7.6%増…` は
    個社の集計であり、業態別名は冒頭に来ない。並立ペアの「協会側」には
    前者を選ぶ必要がある（後者は 制約 15 の個社開示にあたり observation に
    ならない）。sort キーに使うので、真を 0 にして昇順で先に来るようにする。
    """
    norm = item["normalized_title"]
    return 0 if any(norm.startswith(a) for a in item.get("_aliases", ())) else 1


def pick_authority_pairs(candidates: list[dict], count: int, taken: set) -> list[dict]:
    """**発表主体が並立するペアを両側そろえて**選ぶ（G1 区分⑥ / 制約 14）。

    期待値は「2 レコードが共存し、どちらも上書きされない」なので、片側だけを
    選ぶと**その期待値を書ける行が 1 件も無くなる**（初版がこの状態だった）。
    同一業態・同一月について「発表主体マーカーを持つ行（= 経産省側）」と
    「持たない行（= 協会側）」がそろう組を探し、両方を同時に採る。
    """
    groups: dict[tuple, dict[str, list]] = {}
    for item in sorted(candidates, key=_sort_key):
        if item["url"] in taken:
            continue
        f = item["features"]
        segs = [s for s in f["segment_alias_hits"] if s != "meti-commerce-dynamics"]
        month = item["_month_hint"]
        if not segs or not month:
            continue
        if not f["is_statistics_like"] or f["value_tokens"] == 0:
            # **両側とも値を持つ統計記事に限る。** 制約 14 の期待値は
            # 「2 レコードが共存し、どちらも上書きされない」であり、片側が
            # 定性のみ・値なしだと共存を値で示せない（`3月の百貨店売上高、
            # 全社増収` を協会側に選ぶと、真の協会統計 `日本百貨店協会／
            # 3月の売上高3.2％増` が別区分に流れてペアが成立しない）。
            continue
        groups.setdefault((segs[0], month), {}).setdefault(
            "meti" if f["has_authority_marker"] else "association", []
        ).append(item)

    for sides in groups.values():
        for side in sides.values():
            side.sort(key=lambda x: (_subject_first(x), _sort_key(x)))

    chosen = []
    for key in sorted(groups):
        if len(chosen) >= count:
            break
        sides = groups[key]
        if "meti" not in sides or "association" not in sides:
            continue
        pair = [sides["meti"][0], sides["association"][0]]
        if any(x["url"] in taken for x in pair):
            continue
        for item in pair:
            taken.add(item["url"])
            chosen.append({
                **item,
                "bucket": "multi_authority",
                "selected_because": (
                    f"発表主体の並立ペア（segment={key[0]} / {key[1]}月）の"
                    + ("経産省側" if item["features"]["has_authority_marker"] else "協会側")
                    + "。**相方と 2 レコードが共存するのが期待値**（制約 14）"
                ),
            })
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(description="golden-60 の候補を機械的に選定する（G1）")
    parser.add_argument("--out", required=True, metavar="PATH")
    parser.add_argument("--org", default=config.DEFAULT_ORG)
    parser.add_argument("--source", metavar="DIR", help="digest ディレクトリ。省略時は config.digest_dir()")
    parser.add_argument("--since", default="2026-03-21", metavar="YYYY-MM-DD")
    parser.add_argument(
        "--until",
        default="2026-07-26",
        metavar="YYYY-MM-DD",
        help="G1 の母集団（計測日 %(default)s の 595 行）を再現するための上限",
    )
    args = parser.parse_args()

    source = Path(args.source) if args.source else config.digest_dir(args.org)
    if not source.is_dir():
        print(f"digest ディレクトリがありません: {source}", file=sys.stderr)
        return 3
    cat = catalog_mod.load(config.catalog_path(args.org))

    files = [
        p
        for p in digest.iter_digest_files(source, since=args.since)
        if digest.date_from_filename(p) <= args.until
    ]
    rows = [row for p in files for row in digest.parse_file(p).rows]

    by_url: dict[str, list] = {}
    for row in rows:
        by_url.setdefault(row.url, []).append(row)

    candidates = []
    for url in sorted(by_url):
        group = by_url[url]
        title = representative([r.title for r in group])
        norm = textnorm.normalize(title)
        candidates.append(
            {
                "url": url,
                "title": title,
                "normalized_title": norm,
                "source_name": group[0].source_name,
                "first_digest_date": min(r.digest_date for r in group),
                "appeared_dates": sorted({r.digest_date for r in group}),
                "_month_hint": month_hint(norm),
                "_aliases": [a for a, _ in cat.segment_alias_index() if a in norm],
                "features": classify(title, norm, cat),
                "expected": None,
                "status": "needs_human_review",
            }
        )

    print(f"母集団: {len(files)} ファイル / 延べ {len(rows)} 行 / 一意 URL {len(candidates)} 件")

    annotate_ranks(candidates)
    taken: set = set()
    selected: list[dict] = []

    def f(item):
        return item["features"]

    def in_scope(item):
        """カタログの業態別名で解決できる = 本システムの対象内。"""
        return bool(f(item)["segment_alias_hits"])

    # **希少な区分から先に取る。** pick() は taken 集合で URL の重複選択を防ぐため、
    # 先に走った区分が後続の区分の唯一の候補を奪う。順序は宣言ではなく
    # **実データの候補件数**で決めること（初版はこの順序が守られておらず、
    # no_numeric と multi_authority が代表例を他区分に奪われていた）。

    # ⑧-a 真の取りこぼし（母集団 3 件。最も希少）
    selected += pick(
        candidates,
        lambda c: not in_scope(c) and f(c)["has_authority_marker"],
        2, "out_of_scope",
        "発表主体マーカーはあるが業態を解決できない = **真の取りこぼし候補**"
        "（期待値は no_segment_match。out_of_scope との判別を評価するため意図的に混ぜる）",
        taken,
    )

    # ⑥ 発表主体の並立ペア（両側そろえて 4 件 = 2 組）
    selected += pick_authority_pairs(candidates, 4, taken)

    # ⑦ 対象内なのに値が取れない行。**ランキング記事は除く**
    #    G1 の代表例 `ホームセンター月次実績＝2026年6月度` がこの性質そのもの。
    #    ランキング記事は未決事項 (c)（分母除外の可否）に依存するため、
    #    決着していない論点を評価データの前提にしない。
    selected += pick(
        candidates,
        lambda c: f(c)["value_tokens"] == 0
        and in_scope(c)
        and f(c)["is_statistics_like"]
        and not f(c)["is_ranking"],
        4, "no_numeric",
        "対象内の月次統計記事だが値トークン（% / 金額）が 0"
        "（期待値は unresolved / no_numeric。out_of_scope との違いは対象内である点）",
        taken,
    )

    # ⑤-a 連続記録（streak_broken_months を評価できる行。**対象内 × 値あり**）
    selected += pick(
        candidates,
        lambda c: f(c)["has_streak"] and in_scope(c) and f(c)["value_tokens"] > 0,
        3, "qualitative_and_streak",
        "連続記録表現 + 値あり + 対象内（期待値は value と streak_broken_months の**両方**）",
        taken,
    )

    # ① 主要4業態 × 既存店（G1 の厳密条件）
    selected += pick(
        candidates,
        lambda c: bool(set(f(c)["segment_alias_hits"]) & set(MAJOR4)) and f(c)["has_existing_store"],
        16, "major4_existing_store", "主要4業態の別名に一致 かつ 「既存店」を含む（G1 の厳密条件）", taken,
    )
    # **G1 は 18 件を求めるが、母集団から 18 件は取れない（G-6）。**
    # 主要4業態にヒットする一意 URL は 34 件。うち既存店表記ありが 12、
    # 「既存店表記なしの月次統計・値あり」が 9 で計 21。ここから ⑤（連続記録）が 1、
    # ⑥（発表主体ペア）が 4 を先に確保するため、残りは 16 件が上限になる。
    # これ以上広げるには個社決算（セブン＆アイ / J.フロント / 個社SC の年度売上）を
    # 入れるしかなく、制約 15 が out_of_scope と定める行を NFR-04 の評価枠に
    # 混ぜることになる（checker が F7 として差し戻した欠陥そのもの）。
    # **件数を満たすために性質を捨てない。** 不足は origin.md D-E の G-6 で報告する。
    strict = sum(1 for s in selected if s["bucket"] == "major4_existing_store")
    if strict < 16:
        # 不足分は「主要4業態の月次統計記事（既存店表記なし）」で補う。
        # **個社決算を混ぜない**（それは区分⑧ の性質であり NFR-04 の評価対象にならない）。
        selected += pick(
            candidates,
            lambda c: bool(set(f(c)["segment_alias_hits"]) & set(MAJOR4))
            and f(c)["period_kind"] == "month"
            and f(c)["is_statistics_like"]
            and f(c)["value_tokens"] > 0,
            16 - strict, "major4_existing_store",
            "主要4業態の月次統計だが「既存店」表記なし = **全店系**（厳密条件が"
            "12 件しか実在しないための補充枠。期待値の scope を要確認）",
            taken,
        )

    # ⑤-b 定性表現のみ。連続記録側は「対象内 × 値あり」が母集団に 2 件しか無い
    #     （設計 §7.3 が名指しする 51カ月＝SC と 40カ月＝スーパー）ため適応枠にする。
    streak_n = sum(1 for s in selected if s["bucket"] == "qualitative_and_streak")
    selected += pick(
        candidates,
        lambda c: f(c)["has_qualitative"] and f(c)["value_tokens"] == 0,
        6 - streak_n, "qualitative_and_streak",
        "定性表現のみ（期待値は value=None / sign_only / needs_source_check=True）",
        taken,
    )

    # ② 複数指標。**対象内に限る**（FR-11 の評価対象は業態が解決できる行）
    selected += pick(
        candidates,
        lambda c: f(c)["pct_tokens"] >= 2 and in_scope(c),
        8, "multi_metric", "% トークンが 2 個以上 かつ 対象内（1 行が複数 observation に分解される）", taken,
    )

    # ③ 期間 5 種を 1 件ずつ確保してから残り枠を埋める
    for kind in PERIOD_KINDS:
        selected += pick(
            candidates, lambda c, k=kind: f(c)["period_kind"] == k,
            1, "period_all_5_types", f"期間表記 = {kind}（5 種を 1 件ずつ確保する枠）", taken,
        )
    selected += pick(
        candidates, lambda c: f(c)["period_kind"] is not None,
        max(0, 8 - sum(1 for s in selected if s["bucket"] == "period_all_5_types")),
        "period_all_5_types", "期間表記あり（5 種確保後の残り枠）", taken,
    )

    # ④ 表記ゆれ（原文で判定）
    selected += pick(
        candidates,
        lambda c: f(c)["has_fullwidth_pct"] or f(c)["has_kagetsu_variant"] or f(c)["has_fullwidth_digit"],
        6, "notation_variants", "全角％ / 全角数字 / カ月表記のゆれを原文に含む", taken,
    )

    # ⑧-b 対象範囲外（個社決算・非統計記事）
    selected += pick(
        candidates,
        lambda c: not in_scope(c) and not f(c)["has_authority_marker"],
        4, "out_of_scope", "業態別名にも発表主体マーカーにも一致しない（個社・非統計記事）", taken,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for item in selected:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"\n選定結果: {len(selected)} 件 → {out}")
    for name, want, why in BUCKETS:
        got = sum(1 for s in selected if s["bucket"] == name)
        mark = "OK " if got == want else "!! "
        print(f"  {mark}{name:<24} {got:>2} / {want:<2}  {why}")
    expected_total = sum(n for _, n, _ in BUCKETS)
    if len(selected) != expected_total:
        print(f"\n[warn] 合計が {expected_total} 件になっていません（{len(selected)} 件）。", file=sys.stderr)
    if expected_total != 60:
        print(
            f"\n[G-6] G1 の合計は 60 件だが、本母集団から取れるのは {expected_total} 件。"
            "\n      区分① は 18 件を求められているが 16 件が上限（母集団の枯渇）。"
            "\n      不足 2 件を埋めるには個社決算を混ぜるしかなく、制約 15 に反する。"
        )
    print("\n**期待値は未確定です。** 各行の expected を人手で埋め、status を confirmed にしてから")
    print("tests/fixtures/golden-60.jsonl として凍結してください（ループ設計 §3.3 G1）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
