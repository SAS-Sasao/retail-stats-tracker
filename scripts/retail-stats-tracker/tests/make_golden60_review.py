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

> **「決めること」列は質問であって答えではない。** 当初は機械推定の業態・指標を
> 出していたが、それは人手確定へのアンカリングになる（`3月消費支出…外食マイナス―総務省`
> が「外食」の部分一致で `family-restaurant` にヒットする等、実際に誤りも含んでいた）。
> **判断は必ずタイトル原文から行うこと。**

---

## 先に決めてほしい 3 点（実装側の推奨つき）

**推奨であって決定ではない。** G1 は期待値の確定を人手に限定している。
根拠の詳細は `docs/design/origin.md` D-E の N-1a を参照。

| # | 論点 | 実装側の推奨 |
|---|---|---|
| **G-2**<br>（最重要） | ランキング記事を NFR-05 の分母から外すか（未決事項 (c)） | **`out_of_scope`（外す）。ただし「数値が改善するから」を理由にしない。** 要件 v0.1.1 の「小売月次統計でない一般記事」に素直に該当するため、定義のまま処理でき要件改訂も不要。**定義の問題として先に決め、数値の動きは事後に報告する**順序を推奨 |
| **G-4** | 分母の帰属が未定義のマクロ統計行の扱い | **「日本国内の小売・外食の販売動向を示す統計か」を唯一の線引きに。** 海外マクロ（米/ユーロ圏 GDP・米 CPI）→ `out_of_scope` / 地域別 CPI（都内物価）→ `no_segment_match`（要件 制約 15 が例示）/ 国内の需要側マクロ（消費支出・消費者態度）→ `no_segment_match` / 農林水産物輸出額 → `out_of_scope`。**分母は増える方向**に働き、G-2 と逆向きになる |
| **G-1** | 区分①の補充 6 件（全店系）でよいか | **このまま 12 + 6 で凍結。母集団は広げない。** G1 の母集団は「計測日 2026-07-26 の 595 行」と明示されており、窓を広げると設計の他の実測値と比較できなくなる。補充 6 件は業態・期間・発表主体の解決評価には使える。ただし **golden-60 単体では NFR-04 を判定できない**（既存店指標が 12 件しかない）ことを記録する |

**この 3 点はいずれも「取れた／取れない」の境界を動かす**ので、個別の 60 行を埋める前に
決めてほしい。とくに G-2 と G-4 は NFR-05 の分母定義そのものである。

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

### 記入例（**設計からの転記**であって推奨値ではない）

下の 2 例は実装設計 §7.2 の T-10h / T-10i が期待値を本文で明示しているものを、
そのまま JSON にしたもの。**書式の見本**として使ってほしい。

`ショッピングセンター／6月既存店売上1.6％減、夏物振わず51カ月ぶりに前年割れ`
（T-10h: `existing-store-sales-yoy = -1.6` かつ `streak_broken_months = 51`）

```json
"expected": [
  {
    "segment_id": "shopping-center", "metric_id": "existing-store-sales-yoy",
    "scope": "existing_store", "source_authority": "sc-association",
    "period_key": "2026-06", "period_type": "month",
    "value": -1.6, "unit": "percent_yoy",
    "streak_broken_months": 51, "sign_only": null, "needs_source_check": false
  }
]
```

定性表現のみの行（T-10i: `増収増益` は 2 件、`value = None`、`sign_only = "+"`、
`needs_source_check = True`）

```json
"expected": [
  {"segment_id": "...", "metric_id": "operating-revenue-yoy", "scope": "n_a",
   "source_authority": "...", "period_key": "...", "period_type": "...",
   "value": null, "unit": "percent_yoy",
   "streak_broken_months": null, "sign_only": "+", "needs_source_check": true},
  {"segment_id": "...", "metric_id": "operating-profit-yoy", "scope": "n_a",
   "source_authority": "...", "period_key": "...", "period_type": "...",
   "value": null, "unit": "percent_yoy",
   "streak_broken_months": null, "sign_only": "+", "needs_source_check": true}
]
```

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


def _decisions(row: dict) -> str:
    """その行で**オーナーが決めること**を列挙する。

    checker から「手がかり列（機械推定の業態・指標）は人手確定へのアンカリングに
    なる」と指摘を受けたため、**答えの示唆ではなく質問**を出す形に変えた。
    質問はアンカリングしない。
    """
    f = row["features"]
    bucket = row["bucket"]
    out: list[str] = []

    # --- (B) 解けないことが正解の行 -----------------------------------------
    if bucket in ("no_numeric", "out_of_scope"):
        if "真の取りこぼし" in row["selected_because"]:
            out.append(
                "**(B)** `no_segment_match`（取りこぼし＝カタログに業態を足すべき）か "
                "`out_of_scope`（対象外）か ← **G-4 の判断が直接効く**"
            )
        elif bucket == "no_numeric":
            out.append("**(B)** `no_numeric` でよいか（業態は解決できるが値が無い）")
        else:
            out.append("**(B)** `out_of_scope` でよいか（個社決算 / 非統計記事）")
        return "<br>".join(out)

    # --- (A) observation が取れる行 -----------------------------------------
    if f["pct_tokens"] >= 2:
        out.append(f"**何レコードに分解するか**（% トークン {f['pct_tokens']} 個。FR-11）")
    if f["has_existing_store"]:
        out.append("`scope` = `existing_store`（「既存店」表記あり）でよいか")
    else:
        out.append(
            "**「既存店」表記なし** → 既存店指標に**昇格させない**。"
            "率なら `all-store-sales-yoy` / 絶対額なら `sales-amount-absolute`（カタログ §2.2）"
        )
    if bucket == "multi_authority":
        out.append(
            "`source_authority`（経産省側 = `meti` / 協会側 = カタログ既定）。"
            "**相方と natural key が衝突せず 2 レコード共存すること**"
        )
    if f["period_kind"] == "month":
        out.append("`period_key`: タイトルに年が無ければ**掲載月の前月**（カタログ §4.2）")
    elif f["period_kind"]:
        out.append(f"`period_key` / `period_type`（{f['period_kind']}）")
    else:
        out.append("**期間が読み取れない** → `ambiguous_period` で (B) にするかを含めて判断")
    if f["has_streak"]:
        out.append("`streak_broken_months` も入れる（**値と両方**。制約 11）")
    if f["has_qualitative"] and f["value_tokens"] == 0:
        out.append("`value = null` / `sign_only` / `needs_source_check = true`")
    return "<br>".join(out)


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

    forms_b = [r for r in rows if r["bucket"] in ("no_numeric", "out_of_scope")]
    forms_a = [r for r in rows if r not in forms_b]
    multi = [r for r in forms_a if r["features"]["pct_tokens"] >= 2]
    existing = [r for r in forms_a if r["features"]["has_existing_store"]]
    summary = [
        "\n## 作業量の目安\n",
        f"- **(A) observation を書く行: {len(forms_a)} 件** "
        f"（うち複数レコードに分解しうる行 {len(multi)} 件、「既存店」表記あり {len(existing)} 件）",
        f"- **(B) `reason_code` を選ぶだけの行: {len(forms_b)} 件**",
        "",
        "(B) は 1 行あたり選択肢 7 値から 1 つ選ぶだけなので速い。時間がかかるのは (A) の"
        f"うち複数指標に分解する {len(multi)} 件で、ここが FR-11 の評価そのものになる。",
        "",
        "---",
    ]
    out = [HEADER, "\n".join(summary)]
    for bucket, title in BUCKET_TITLES.items():
        picked = [(i + 1, r) for i, r in enumerate(rows) if r["bucket"] == bucket]
        out.append(f"\n## {title}\n")
        out.append(f"{BUCKET_NOTES[bucket]}\n")
        out.append("| 行 | 掲載日 | 記事タイトル | **決めること** |")
        out.append("|---:|---|---|---|")
        for lineno, row in picked:
            title_cell = row["title"].replace("|", "\\|")
            dates = row["appeared_dates"]
            date_cell = dates[0] if len(dates) == 1 else f"{dates[0]} (+{len(dates) - 1})"
            out.append(
                f"| {lineno} | {date_cell} | {title_cell} | {_decisions(row)} |"
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
