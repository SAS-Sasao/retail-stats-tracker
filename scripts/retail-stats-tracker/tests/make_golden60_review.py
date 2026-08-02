#!/usr/bin/env python3
"""golden-60 候補の**レビュー用資料**を生成する（ループ設計 §3.3 規律 G1）。

`make_golden60.py` が出した候補 60 件を、オーナーが期待値を確定しやすい形に
整形する。**期待値は書かない。** 判断材料（タイトル・掲載日・カタログ別名の
一致状況・値トークンの有無・期間表記）を 1 か所に集めるだけである。

出力:
    golden-60-review.md   区分ごとに並べたレビューシート（読むための資料）
                          各行に候補 JSONL の行番号を添えるので、確定したら
                          その行の expected を埋める

**このスクリプトは LLM を呼ばない。** 期待値を機械が推測して埋めると
「実装に引きずられた期待値」になり評価が成立しない（G1）。とくに
`retail-stats-extractor`（IF-03 の LLM 抽出フォールバック）に書かせることは、
評価対象そのものに正解を作らせることになるため行わない。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_stats import catalog as catalog_mod  # noqa: E402
from retail_stats import config  # noqa: E402

BUCKET_TITLES = {
    "major4_existing_store": "① 主要 4 業態の月次既存店指標（18 件）",
    "multi_metric": "② 複数指標を含む記事（8 件・FR-11）",
    "period_all_5_types": "③ 期間表記の全 5 種（8 件）",
    "notation_variants": "④ 表記ゆれ（6 件・FR-05）",
    "qualitative_and_streak": "⑤ 定性表現のみ・連続記録（6 件）",
    "multi_authority": "⑥ 発表主体が並立する行（4 件）★末尾 3 区分",
    "no_numeric": "⑦ 数値が取れないことが正解の行（4 件）★末尾 3 区分",
    "out_of_scope": "⑧ 対象範囲外が正解の行（6 件）★末尾 3 区分",
}

BUCKET_NOTES = {
    "major4_existing_store": (
        "NFR-04 が 90% を要求している対象そのもの。**うち 6 件は「既存店」表記が無い全店系**"
        "（厳密条件に一致する一意 URL が 12 件しか実在しないための補充枠。判断 G-1）。"
        "補充枠は「主要4業態の月次統計 かつ 値あり」に限定してあり個社決算は混ざっていない。"
        "`selected_because` で区別できる。"
    ),
    "multi_metric": (
        "1 行が複数の observation に分解される。"
        "`日本百貨店協会／6月の外国人売上29.8％増、客数0.5％減・客単価30.4％増` = **3 レコード**。"
    ),
    "period_all_5_types": "月次 / 決算期 / 四半期 / 半期 / 年度 の 5 種が全て含まれる（制約 5）。",
    "notation_variants": "全角％ / 半角% / カ月表記のゆれ。正規化後に同一 observation へ収束することを見る。",
    "qualitative_and_streak": (
        "`増収増益` は **value=None / sign_only='+' / needs_source_check=True** の 2 レコード。"
        "`51カ月ぶりに前年割れ` は **value と streak_broken_months=51 の両方**を持つ（制約 11）。"
    ),
    "multi_authority": (
        "**期待値は「2 レコードが共存し、どちらも上書きされない」**（制約 14）。"
        "natural key の第 5 要素 `source_authority` だけが異なる。"
    ),
    "no_numeric": (
        "**期待値は `unresolved`（`reason_code = no_numeric`）**（制約 3）。"
        "「取れないことが正解」を評価データに含めないと、無理に数値をひねり出す方向へ最適化が進む。"
        "選定側では**ランキング記事を除外**し、「対象内の月次統計だが値が取れない」行に絞った"
        "（未決事項 (c) が決着していないため、それを前提にしない）。G1 が名指しする代表例 "
        "`ホームセンター月次実績＝2026年6月度` を含む。"
    ),
    "out_of_scope": (
        "**期待値は `unresolved`（`reason_code = out_of_scope`）**（制約 15）。"
        "ただし**うち 2 件は真の取りこぼしで期待値は `no_segment_match`**。"
        "この 2 種の判別が評価できないと、NFR-05 の分母操作を誰も検出できなくなる。"
    ),
}

HEADER = """# golden-60 レビューシート

ループ設計 §3.3 規律 G1 の評価データセット。**候補の選定は機械的に済んでいる**ので、
残っているのは**期待値の確定**（人手）だけである。

- 候補ファイル: `scripts/retail-stats-tracker/tests/fixtures/golden-60.candidates.jsonl`
- 確定後の凍結先: `scripts/retail-stats-tracker/tests/fixtures/golden-60.jsonl`
- 構成の検査: `scripts/retail-stats-tracker/tests/test_golden60.py`

本シートは**読むための資料**であり、記入先ではない。各行に候補 JSONL の行番号を
添えてあるので、確定したらその行の `expected` を埋め `status` を `confirmed` にする。

> **「手がかり」列は機械推定であり誤りを含む。** カタログ別名の単純な部分一致で
> 出しているだけで、主語位置のガード（設計 §4.3.3）を通していない。実例として
> `3月消費支出…外食マイナス―総務省` は「外食」の部分一致で `family-restaurant` に
> ヒットするが、これは総務省の家計調査であって外食業態の統計ではない。
> **判断は必ずタイトル原文から行い、この列は目印としてのみ使うこと。**

---

## 先に決めてほしい 4 点

この 4 点で期待値が変わるため、**個別の 60 行を埋める前に**決めてほしい。

| # | 論点 | 影響 |
|---|---|---|
| **G-2**<br>（最重要） | **ランキング記事を NFR-05 の分母から外すか**（未決事項 (c)） | 選定側では区分 ⑦ からランキング記事を除外した（決着していない論点を評価データの前提にしないため）。ただし**分母の定義そのもの**なので、決め方によっては区分 ⑧ の期待値が動く |
| **G-4** | **分母の帰属が未定義のマクロ統計行**（海外 GDP / 米 CPI / 消費者心理 / 消費支出 / 農水省統計など）の扱い | 候補に複数含まれる。`cpi` / `ec-platform` 以外のマクロ統計はカタログに segment が無く、`no_segment_match`（取りこぼし）と `out_of_scope`（対象外）のどちらが正しいかで NFR-05 の分母が変わる |
| **G-1** | 区分 ① の 18 件のうち **6 件が「既存店」表記の無い全店系**でよいか | 厳密条件（主要4業態 × 既存店）に一致する一意 URL は実データに 12 件しか無い。補充枠は「主要4業態の月次統計 かつ 値あり」に限定してあり、個社決算は混ざっていない |
| **G-5** | G1 の表記ゆれ 4 要素のうち **「全角数字」は母集団に 0 件** | 延べ 595 行に 1 件も無く、区分 ④ で構造的に充足できない。要件 FR-05 の記述との差として記録するかどうか |

---

## 期待値の書き方

`expected` は次のどちらかの形にする。

**(A) observation が取れる行** — 配列。1 行が複数の observation に分解される場合は複数要素。

```json
"expected": [
  {
    "segment_id": "shopping-center",
    "metric_id": "existing-store-sales-yoy",
    "scope": "existing_store",
    "source_authority": "sc-association",
    "period_key": "2026-06",
    "period_type": "month",
    "value": -1.6,
    "unit": "percent_yoy",
    "streak_broken_months": 51,
    "sign_only": null,
    "needs_source_check": false
  }
]
```

**(B) 解けないことが正解の行** — `unresolved` を持つオブジェクト。

```json
"expected": {"unresolved": {"reason_code": "no_numeric"}}
```

`reason_code` は 7 値: `no_metric_match` / `no_segment_match` / `no_numeric` /
`ambiguous_period` / `low_confidence` / `llm_schema_error` / `out_of_scope`。

### 埋めるときの原則（G1 の趣旨）

- **記事タイトルに現れない情報を推測で埋めない。** タイトルから読み取れないものは
  そもそも取れないのが正解であり、その場合は (B) を選ぶ
- **「取れないことが正解」「2 レコードが共存するのが正解」を正しく書く。** ここを
  「取れる」側に倒すと、評価が「取れた数」だけを報酬にしてしまい、無理に数値を
  ひねり出す方向・母集団の違う値を 1 つに畳む方向へ最適化が進む（G1 本文）
- 迷った行は `status` を `needs_human_review` のまま残してよい。**未確定を
  `confirmed` と書かないこと**が、この評価データの価値を守る

---
"""


def _fmt_features(row: dict, metric_index) -> str:
    f = row["features"]
    parts = []
    segs = f["segment_alias_hits"]
    parts.append(f"業態={'/'.join(segs) if segs else '**未解決**'}")
    norm = row["normalized_title"]
    metrics = sorted({mid for alias, mid in metric_index if alias in norm})
    parts.append(f"指標={'/'.join(metrics) if metrics else '**未解決**'}")
    parts.append(f"期間={f['period_kind'] or '**なし**'}")
    parts.append(f"値={f['value_tokens']}")
    if f["has_existing_store"]:
        parts.append("既存店")
    if f["has_authority_marker"]:
        parts.append("**発表主体マーカー**")
    if f["has_qualitative"]:
        parts.append("定性")
    if f["has_streak"]:
        parts.append("連続記録")
    if f["has_fullwidth_pct"]:
        parts.append("全角％")
    return " / ".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="golden-60 のレビュー用資料を生成する")
    parser.add_argument(
        "--candidates",
        default="scripts/retail-stats-tracker/tests/fixtures/golden-60.candidates.jsonl",
    )
    parser.add_argument("--out", required=True, metavar="PATH")
    parser.add_argument("--org", default=config.DEFAULT_ORG)
    args = parser.parse_args()

    path = Path(args.candidates)
    if not path.is_file():
        print(f"候補ファイルがありません: {path}", file=sys.stderr)
        return 3
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    cat = catalog_mod.load(config.catalog_path(args.org))
    metric_index = cat.metric_alias_index()

    out = [HEADER]
    for bucket, title in BUCKET_TITLES.items():
        picked = [(i + 1, r) for i, r in enumerate(rows) if r["bucket"] == bucket]
        out.append(f"\n## {title}\n")
        out.append(f"{BUCKET_NOTES[bucket]}\n")
        out.append("| 行 | 掲載日 | 記事タイトル | 手がかり（※機械推定・誤りうる） |")
        out.append("|---:|---|---|---|")
        for lineno, row in picked:
            title_cell = row["title"].replace("|", "\\|")
            dates = row["appeared_dates"]
            date_cell = dates[0] if len(dates) == 1 else f"{dates[0]} (+{len(dates) - 1})"
            out.append(
                f"| {lineno} | {date_cell} | {title_cell} | {_fmt_features(row, metric_index)} |"
            )
        # 補充枠がある区分は内訳を出す
        reasons = {r["selected_because"] for _, r in picked}
        if len(reasons) > 1:
            out.append("\n選定根拠の内訳:\n")
            for reason in sorted(reasons):
                n = sum(1 for _, r in picked if r["selected_because"] == reason)
                out.append(f"- ({n} 件) {reason}")
        out.append("")

    out.append("\n---\n")
    out.append("## 確定後の手順\n")
    out.append("```bash")
    out.append("# 1. 候補の expected を埋めて status を confirmed にする")
    out.append("#    （golden-60.candidates.jsonl を編集）")
    out.append("# 2. 凍結")
    out.append("cp scripts/retail-stats-tracker/tests/fixtures/golden-60.candidates.jsonl \\")
    out.append("   scripts/retail-stats-tracker/tests/fixtures/golden-60.jsonl")
    out.append("# 3. 構成と確定状態を検査")
    out.append("cd scripts/retail-stats-tracker && python3 -m unittest tests.test_golden60")
    out.append("```\n")
    out.append(
        "`test_golden60.TestGolden60Frozen` は、凍結ファイルの全 60 行が "
        "`status: confirmed` かつ `expected` が非 null であることを検査する。"
        "未確定の行が混ざっていれば落ちる。\n"
    )

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(out), encoding="utf-8")
    print(f"レビューシートを生成しました: {args.out}（{len(rows)} 件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
