# retail_stats — 実行方法・データ再構築手順

日次ダイジェストの「B5. 決算・統計」章を決定論パース + LLM フォールバック
で構造化し、単一 HTML のトレンド可視化サイトとして配信するツール。

設計の詳細は `../../docs/design/`（`implementation-design.md` /
`loop-engineering-design.md` / `cicd-design.md` / `requirements.md` /
`retail-monthly-kpi-catalog.md`）を参照。

実装状況: **M2（カタログローダ）完了**。M1（骨格と入力の確定）のうち
`config.py` のパス解決のみ実装済みで、`models.py` / `textnorm.py` /
`digest.py` / `cli.py` は骨格のまま。

## カタログ契約検査（ループ設計 段階 0）

```bash
# 現行カタログが IF-02 スキーマ契約（C1〜C12）を満たすか検査する
python3 scripts/retail-stats-tracker/validate_catalog.py

# 任意のカタログ MD を検査する（--no-git で C10 の HEAD 比較を省く）
python3 scripts/retail-stats-tracker/validate_catalog.py --no-git path/to/catalog.md
```

exit 0 = pass / 1 = 契約違反（stdout に理由コード付きの一覧）/ 3 = I/O エラー。
`.claude/hooks/verify/retail-stats/verify-catalog-contract.sh` が
カタログ MD の編集時（PostToolUse）に同じスクリプトを呼ぶ。

## 実行方法（実装完了後）

```bash
# 増分実行（既定）
python3 -m retail_stats build

# 全件再構築
python3 -m retail_stats build --rebuild

# LLM を新規に呼ばない（キャッシュヒットは使う。日次自動実行向け）
python3 -m retail_stats build --no-llm

# 抽出キャッシュを破棄して LLM を再実行（明示指定時のみ）
python3 -m retail_stats build --rebuild --invalidate-cache

# HTML のみ再生成
python3 -m retail_stats html

# reason_code 別の未解決分布を計測する
python3 -m retail_stats measure --rebuild --report-json /tmp/measure.json
```

引数の詳細は `retail_stats/cli.py` および `docs/design/implementation-design.md` §2.5 を参照。

## テスト

```bash
cd scripts/retail-stats-tracker && python3 -m unittest discover -s tests
```

テストの入力は常に `tests/fixtures/` であり、実データの所在に依存しない
（実装設計 §7.3）。

## 前提

- Python 3.10 以上（標準ライブラリのみ。外部パッケージを追加しない）
- 実行対象のデータ（日次ダイジェスト MD / カタログ MD）は
  `.companies/domain-tech-collection/` 配下（cc-sier-organization リポジトリ側）
  を想定している。

## 入力データの所在（`docs/design/origin.md` D-A）

`--org SLUG` は**組織スラグ**であり、パスではない（実装設計 §2.5）。
データ層が別リポジトリにある場合は、`.companies/` を含むディレクトリだけを
環境変数 `RETAIL_STATS_WORKSPACE` で差し替える。

```bash
# cc-sier-organization の作業コピーを入力に使う
RETAIL_STATS_WORKSPACE=/path/to/cc-sier-organization \
  python3 -m retail_stats build --dry-run --rebuild
```

| 対象 | 解決順 |
|---|---|
| カタログ | ① `{workspace}/.companies/{org}/docs/retail-domain/retail-monthly-kpi-catalog.md` → ② `{repo_root}/docs/design/retail-monthly-kpi-catalog.md`（本リポジトリのスナップショット） |
| ダイジェスト | `{workspace}/.companies/{org}/docs/daily-digest/`（フォールバックなし） |
| データ出力 | `{workspace}/.companies/{org}/docs/retail-stats/data/`（フォールバックなし） |
| 配信 HTML | `{repo_root}/docs/retail-stats/index.html`（org 非依存） |

どちらのカタログを読んだかは `config.resolved_inputs()` の `catalog_source`
（`canonical` / `repo-snapshot`）で分かる。
