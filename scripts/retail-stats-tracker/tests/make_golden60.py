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
    ("major4_existing_store", 18, "主要 4 業態（SC / 百貨店 / チェーンストア / コンビニ）の月次既存店指標"),
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
# G1 が要求する 5 種は カタログ §4.2 の行にそのまま対応する。
#   月次   = 「6月」「2026年6月度」
#   決算期 = 「◯◯年◯月期」（決算期末月。会計年度の別の名付け方）
#   四半期 = 「3〜5月」
#   半期   = 「1〜6月期」
#   年度   = 「2025年度」
#
# **順序が意味を持つ。狭いパターンから先に置くこと。**
# `1~6月期`（半期）は fiscal_period の `[0-9]{1,2}月期` にも quarter の
# `[0-9]{1,2}~[0-9]{1,2}月` にも一致する。half を先頭に置かないと半期が
# 1 件も選ばれず、G1 の「全 5 種」を満たせなくなる。
PERIOD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("half", re.compile(r"[0-9]{1,2}~[0-9]{1,2}月期")),
    ("fiscal_period", re.compile(r"(?:[0-9]{2,4}年)?[0-9]{1,2}月期")),
    ("fiscal_year", re.compile(r"[0-9]{2,4}年度")),
    ("quarter", re.compile(r"[0-9]{1,2}~[0-9]{1,2}月")),
    ("month", re.compile(r"(?:[0-9]{4}年)?[0-9]{1,2}月")),
)
PERIOD_KINDS = tuple(name for name, _ in PERIOD_PATTERNS)


def representative(titles: list[str]) -> str:
    """§4.7 の代表 variant 選択（数値トークン数 → 長さ → 辞書順）。走査順に依存しない。"""
    return max(titles, key=lambda t: (len(_NUM_RE.findall(textnorm.normalize(t))), len(t), t))


def period_kind(norm: str) -> str | None:
    for name, pattern in PERIOD_PATTERNS:
        if pattern.search(norm):
            return name
    return None


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
        # --- ここから下は原文で見る ---
        "has_fullwidth_pct": "％" in raw,
        "has_halfwidth_pct": "%" in raw,
        "has_fullwidth_digit": bool(re.search(r"[０-９]", raw)),
        "has_kagetsu_variant": bool(re.search(r"[ヶヵか]月", raw)),
    }


def pick(candidates: list[dict], predicate, count: int, bucket: str, why: str, taken: set) -> list[dict]:
    """条件に合う候補から count 件を決定論的に選ぶ（URL 昇順。乱数を使わない）。"""
    chosen = []
    for item in sorted(candidates, key=lambda c: c["url"]):
        if len(chosen) >= count:
            break
        if item["url"] in taken or not predicate(item):
            continue
        taken.add(item["url"])
        chosen.append({**item, "bucket": bucket, "selected_because": why})
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
                "features": classify(title, norm, cat),
                "expected": None,
                "status": "needs_human_review",
            }
        )

    print(f"母集団: {len(files)} ファイル / 延べ {len(rows)} 行 / 一意 URL {len(candidates)} 件")

    taken: set = set()
    selected: list[dict] = []

    def f(item):
        return item["features"]

    # **希少な区分から先に取る。** pick() は taken 集合で URL の重複選択を防ぐため、
    # 先に走った区分が後続の区分の唯一の候補を奪いうる。実例: 真の取りこぼし候補
    # `6月都内物価…8カ月ぶり伸び拡大―総務省` は `Nカ月ぶり` を含むため
    # qualitative_and_streak にも一致し、そちらを先に走らせると out_of_scope の
    # 「2 件は真の取りこぼしを混ぜる」という G1 の構成要求が満たせなくなる
    # （候補は実データに 3 件しか無い）。区分の希少度の昇順に並べること。
    selected += pick(
        candidates,
        lambda c: not f(c)["segment_alias_hits"] and f(c)["has_authority_marker"],
        2, "out_of_scope",
        "発表主体マーカーはあるが業態を解決できない = **真の取りこぼし候補**"
        "（期待値は no_segment_match。out_of_scope との判別を評価するため意図的に混ぜる）",
        taken,
    )
    selected += pick(
        candidates,
        lambda c: bool(set(f(c)["segment_alias_hits"]) & set(MAJOR4)) and f(c)["has_existing_store"],
        18, "major4_existing_store", "主要4業態の別名に一致 かつ 「既存店」を含む（G1 の厳密条件）", taken,
    )
    # G1 は 18 件を求めるが、厳密条件（主要4業態 × 既存店）に一致する一意 URL は
    # 実データに 12 件しか存在しない（--until 2026-07-26 時点）。不足分は
    # 「主要4業態の月次指標（既存店表記なし）」で補い、どちらで選ばれたかを
    # selected_because に必ず残す。黙って 12 件で打ち切ると、golden-60 が
    # NFR-04（主要4業態 90%）の評価に足りていないことが誰にも見えなくなる。
    strict = sum(1 for s in selected if s["bucket"] == "major4_existing_store")
    if strict < 18:
        selected += pick(
            candidates,
            lambda c: bool(set(f(c)["segment_alias_hits"]) & set(MAJOR4))
            and f(c)["period_kind"] is not None,
            18 - strict, "major4_existing_store",
            "主要4業態の別名に一致 かつ 期間表記あり（**既存店表記なし = 全店系**。"
            "厳密条件が 12 件しか無いための補充枠。期待値の確定時に scope を要確認）",
            taken,
        )
    selected += pick(
        candidates, lambda c: f(c)["pct_tokens"] >= 2,
        8, "multi_metric", "% トークンが 2 個以上（複数指標の分解対象）", taken,
    )
    # 期間は「**全 5 種**」が要求なので、まず各種 1 件ずつ確保してから残り 3 枠を埋める。
    # 種類ごとに 2 件ずつ取る方式だと、枠数（8）が種類数（5）で割り切れず、
    # 最後の種類（実データで最多の「月次」）が 0 件になって「全 5 種」を満たさない。
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
    selected += pick(
        candidates, lambda c: f(c)["has_fullwidth_pct"] or f(c)["has_kagetsu_variant"],
        6, "notation_variants", "全角％ または カ月表記のゆれを含む", taken,
    )
    selected += pick(
        candidates, lambda c: f(c)["has_qualitative"] or f(c)["has_streak"],
        6, "qualitative_and_streak", "定性表現 または 連続記録表現を含む", taken,
    )
    selected += pick(
        candidates, lambda c: f(c)["has_authority_marker"] and f(c)["segment_alias_hits"],
        4, "multi_authority", "発表主体マーカー（経産省調べ等）と業態別名の両方を含む", taken,
    )
    # `no_numeric` は「数字が 1 つも無い行」ではなく「**値が取れない行**」である。
    # G1 が挙げる実例 `ホームセンター月次実績＝2026年6月度` は 2026 と 6 という
    # 数字を持つが、率でも金額でもないため値は取れない。`numeric_tokens == 0` で
    # 判定すると、この設計自身の代表例が候補から落ち、代わりに個社決算記事
    # （本来 out_of_scope）が入ってしまう。
    # さらに「業態は解決できる」ことを条件に加える。対象内なのに値が取れない、
    # というのが no_numeric と out_of_scope を分ける点だからである。
    selected += pick(
        candidates,
        lambda c: f(c)["value_tokens"] == 0 and f(c)["segment_alias_hits"],
        4, "no_numeric",
        "業態は解決できるが値トークン（% / 金額）が 0"
        "（期待値は unresolved / no_numeric。out_of_scope との違いは対象内である点）",
        taken,
    )
    selected += pick(
        candidates,
        lambda c: not f(c)["segment_alias_hits"] and not f(c)["has_authority_marker"],
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
    if len(selected) != 60:
        print(f"\n[warn] 合計が 60 件になっていません（{len(selected)} 件）。", file=sys.stderr)
    print("\n**期待値は未確定です。** 各行の expected を人手で埋め、status を confirmed にしてから")
    print("tests/fixtures/golden-60.jsonl として凍結してください（ループ設計 §3.3 G1）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
