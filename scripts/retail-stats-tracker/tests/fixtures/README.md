# テストフィクスチャ

実装設計 §7.3「テストデータの置き場所と切り出し」に対応する。

実ファイル（`.companies/.../daily-digest/*.md` / カタログ）を直接読むテストは、
入力が毎日追加・修正されるため再現性を持たない。テストが「昨日は通ったのに
今日落ちる」状態になると、決定論パースのルール追加サイクル（要件リスク 7-7）が
回らない。したがって**テストの入力は常にこのディレクトリ**であり、実データの
所在（`docs/design/origin.md` D-A）に依存しない。

## `catalog/`（実装設計 §7.3）— **作成済み（M2）**

実カタログ `docs/design/retail-monthly-kpi-catalog.md` の `## 1.` `## 2.`
セクションのみを写した `valid.md` を基本とし、そこから**表の 1 箇所だけ**を
壊した異常系 4 種を作る。「1 箇所だけ違う」ことで、テスト失敗時に原因が
一意に決まる。

| ファイル | 内容 | 検出される検査 |
|---|---|---|
| `valid.md` | 正常系。実カタログの業態区分マスタ・KPI定義のみを抜粋（業態 13 件 / 指標 14 件） | — |
| `missing_column.md` | 指標定義表から `既定スコープ` 列を削除 | 段階 3 の必須列解決（`required_column_missing`） |
| `duplicate_heading.md` | `## 3. 業態区分の補足` を追加して見出しを多重一致させる | 段階 1 の見出し検出（`segment_heading_ambiguous`） |
| `undefined_id.md` | `electronics-retailer` の上位業態に存在しない ID を書く | V9（C12 の `loader_rejected`。**C1〜C11 は通る**点が重要） |
| `unknown_authority.md` | `home-center` の発表主体を IF-02 対応表外の組織名にする | V13 / C11（`authority_unmapped`） |

各ファイルの先頭に `> **異常系フィクスチャ**: …` の 1 行を置いて意図を書いて
いる（表そのものの差分は 1 箇所のみ）。

V1〜V13 の網羅は `tests/test_catalog.py` の `_build_catalog()` が最小カタログを
組み立てて行う。フィクスチャ 5 種は「実カタログ由来の本物の形」に対する回帰、
`_build_catalog()` は検査項目の網羅、という分担にしている。

再生成する場合は実カタログの `## 1.` 〜 `## 3.` 直前を写し、上表の 1 箇所だけを
壊す。

## `digests/`（実装設計 §7.3）— **作成済み（M1）**

`../make_fixtures.py` が実データから決算・統計章のみを抜き出して生成する。
実データ（`.companies/{org}/docs/daily-digest/`）が必要なため、cc-sier 側または
`RETAIL_STATS_WORKSPACE` で作業コピーを指した状態で実行する。12 日分を生成済み。

```bash
RETAIL_STATS_WORKSPACE=/path/to/cc-sier-organization \
python3 scripts/retail-stats-tracker/tests/make_fixtures.py \
  --dates 2026-04-14,2026-04-15,2026-04-16,2026-04-17,2026-04-18,2026-04-22,2026-04-23 \
  --dates 2026-07-22,2026-07-23,2026-07-24,2026-07-25,2026-07-26 \
  --out scripts/retail-stats-tracker/tests/fixtures/digests/
```

章が無い日（2026-04-14）も**ファイルとして生成する**。存在しないファイルにすると
走査対象から外れ、T-10a（章が無い日でエラーにならない）の検証にならないため。

| 日付群 | 検証対象 |
|---|---|
| 2026-04-15 / 16 / 17 / 18 / 22 / 23 | `s041442` の非連続6日重複、4つの title variant |
| 2026-04-14 | 決算・統計章そのものが存在しない日 |
| 2026-07-22 〜 07-26 | 主要4業態の6月既存店、全角/半角混在、複数指標分解、連続記録表現、生協の総供給高、金額+率の併存、出典名の揺れ |

生成手順は `../make_fixtures.py` のモジュール docstring を参照。

## `golden-60.candidates.jsonl`（ループ設計 §3.3 規律 G1）

`../make_golden60.py` が G1 の選定基準表どおり 8 区分・合計 60 件を**機械的に**選定した候補。
再実行でバイト一致する（URL 昇順・乱数なし）。

**期待値は意図的に空**（`expected: null` / `status: "needs_human_review"`）。G1 は選定を
「機械的に決める」、期待値を「人手で確定」と明確に分けている。期待値を機械が推測して
埋めると「実装に引きずられた期待値」になり評価が成立しない。オーナーが `expected` を
埋め `status` を `confirmed` にして **`golden-60.jsonl`** として凍結する。

区分と件数、および凍結前に判断が要る 3 点は `docs/design/origin.md` D-E の N-1a を参照。
構成そのものは `../test_golden60.py` が固定している。

## 個人情報の扱い

フィクスチャに含まれるのは公開記事の見出しと URL のみであり、個人情報・
顧客固有情報は含まない（NFR-15）。
