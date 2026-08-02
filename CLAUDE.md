# retail-stats-tracker

## プロジェクト概要

日次ダイジェストの「B5. 決算・統計」章（小売業界の決算・月次統計記事）を
決定論パース + LLM フォールバックで時系列データ化し、単一 HTML の
トレンド可視化サイトとして配信する小売月次統計トラッカー。

## 設計の出自

このプロジェクトの設計は cc-sier-organization リポジトリの組織
「domain-tech-collection」で策定された。詳細は `docs/design/origin.md`
を参照すること。設計原本は cc-sier 側にあり、本リポジトリはスナップショット
である。設計変更は cc-sier 側で行い、このリポジトリにも反映すること。

- 要件定義: `docs/design/requirements.md`（v0.1.1、上位文書）
- 実装設計: `docs/design/implementation-design.md`
- 開発ループ設計: `docs/design/loop-engineering-design.md`（検証 hooks / Subagent 編成）
- CI/CD 設計: `docs/design/cicd-design.md`
- KPI カタログ（IF-02 外部定義）: `docs/design/retail-monthly-kpi-catalog.md`

## 技術スタック

- Python（標準ライブラリのみ。外部パッケージを追加しない方針。実行環境
  3.10 以上、開発環境実測 3.12.13）
- テスト: `unittest`（実装設計 §7.1 で確定。pytest は導入しない）
- フロントエンド: Chart.js（MIT license、vendoring）+ 素の JS/CSS。単一
  HTML に自己完結（NFR-08）

## ディレクトリ構成

```
retail-stats-tracker/
├── docs/
│   └── design/            ← 設計成果物のスナップショット（cc-sier から切り出し）
├── scripts/retail-stats-tracker/
│   ├── retail_stats/      ← 実装コード本体
│   │   ├── __main__.py    ← python3 -m retail_stats のエントリ
│   │   ├── cli.py / config.py / models.py / textnorm.py
│   │   ├── catalog.py / digest.py / period.py / parser.py
│   │   ├── llm.py / cache.py / store.py / report.py
│   │   └── html/           ← 単一 HTML 生成器
│   └── tests/              ← unittest（実装設計 §7.2 のテストケースに対応）
├── .claude/agents/          ← Subagent 定義（maker 4 + checker 1 + 抽出器 1）
└── docs/retail-stats/       ← 配信 HTML（IF-05。実装後に生成）
```

## 開発ルール

### 設計上の確定事項（実装時の前提。変更する場合は要件定義の改訂として扱う）

- natural key は **5 要素** `(segment_id, metric_id, scope, period_key, source_authority)`。
  発表主体が異なる観測は上書きせず共存させる（要件 7-14）
- テストは `unittest`。外部依存を増やさない（NFR-08 の思想を開発環境にも適用）
- 冪等性の比較対象は **6 ファイル allowlist**
  （`observations.json` / `articles.json` / `extraction-cache.json` /
  `unresolved.json` / `manifest.json` / `series.json`）。`runs.json` は
  実行時刻を含むため必ず除外する
- `DATA_DIR` 直下に存在を許容するのは **8 種**（上記6 + `runs.json` +
  `permanently-unresolvable.json`）
- `--no-llm` は「LLM を新規に呼ばない」であり「LLM 由来の抽出を一切使わない
  （キャッシュヒットも捨てる）」ではない
- LLM フォールバックの実行主体は claude-code-action ではなく `claude` CLI
  の subprocess 呼び出し（`ClaudeCliClient`）
- **検証 hooks（Stop 配下）は全て読み取り専用**にする。hooks は並列実行
  されるため、破壊的検査（冪等性の R1/R2 等）は `--full` モードで
  `/retail-stats-verify` と CI に限定する
- Subagent の maker-checker 分離: `retail-stats-qa`（checker、Bash あり
  Write/Edit なし）と `retail-stats-extractor`（抽出器、Read のみ、memory
  を持たない）は既存 19 種のパターンと異なる意図的な組み合わせ

### 実装マイルストーン（実装設計 §8 の概要）

| # | 内容 | 判断分岐点 |
|---|---|---|
| M1 | 骨格と入力の確定（config/models/textnorm/digest/cli の dry-run） | |
| M2 | カタログローダ | |
| M3 | 決定論パースと分布計測 | ★ NFR-04/05 未達なら M3 に戻る |
| M4 | 永続化と冪等性 | |
| M5 | LLM フォールバック | |
| M6 | 配信 JSON と単一 HTML | |
| M7 | 運用への接続（--report-json、CI 引き継ぎ） | |

### コミット規約

Conventional Commits（`feat:` / `fix:` / `docs:` / `refactor:` / `chore:`）。
ブランチ運用は GitHub Flow（main + feature branches）を想定する。設計変更は
重要なものは ADR として `docs/architecture/adrs/` に記録する。

## 未決事項

`docs/design/origin.md`「未決事項」節を参照（NFR-05 未達 / U10 複数主体併記）。
実装着手前にオーナー判断が必要。
