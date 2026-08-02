# retail_stats — 実行方法・データ再構築手順

日次ダイジェストの「B5. 決算・統計」章を決定論パース + LLM フォールバック
で構造化し、単一 HTML のトレンド可視化サイトとして配信するツール。

設計の詳細は `../../docs/design/`（`implementation-design.md` /
`loop-engineering-design.md` / `cicd-design.md` / `requirements.md` /
`retail-monthly-kpi-catalog.md`）を参照。実装状況は未着手（骨格のみ）。

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
python3 -m unittest discover -s scripts/retail-stats-tracker/tests
```

## 前提

- Python 3.10 以上（標準ライブラリのみ。外部パッケージを追加しない）
- 実行対象のデータ（日次ダイジェスト MD / カタログ MD）は
  `.companies/domain-tech-collection/` 配下（cc-sier-organization リポジトリ側）
  を想定している。本リポジトリ単体では `--org` の参照先データが存在しないため、
  実データでの動作確認は cc-sier-organization リポジトリ上、または
  本リポジトリに同等のデータ層を用意した上で行うこと。
