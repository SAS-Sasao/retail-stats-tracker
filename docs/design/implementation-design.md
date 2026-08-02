# 小売月次統計トラッカー 実装設計書

## 日次ダイジェスト B5 章パーサ + 静的トレンド可視化サイトの実装設計

| 項目 | 内容 |
|------|------|
| ドキュメント種別 | 設計書 v0.1.1（ドラフト） |
| 作成日 | 2026-07-26 |
| 最終更新日 | 2026-08-02（v0.1.1: M3 実装からの報告 Issue #728 / #729 を反映。確定内容は §9.3 の D5 / D6） |
| 作成者 | 技術リサーチ室（system-architect） |
| 対象システム | retail-stats-tracker |
| 準拠する要件定義 | 要件定義書 **v0.1.2**（natural key 5 項化 / NFR-05 分母再定義 / reason_code 9 値化 / V12 の値種別緩和を反映済み） |
| ステータス | レビュー待ち |

---

## 1. 概要

### 1.1 本書の位置づけ

本書は [要件定義書 v0.1.2](requirements.md)（以下「要件」）が定義した「何を作るか」に対し、「どう作るか」を実装者が手を動かせる粒度まで落としたものである。要件を上位文書とし、本書は要件を変更しない。

| 項目 | 内容 |
|------|------|
| 上位文書 | `.companies/domain-tech-collection/docs/research/requirements.md`（**v0.1.2**） |
| 参照文書（読み取り専用の外部定義） | `.companies/domain-tech-collection/docs/retail-domain/retail-monthly-kpi-catalog.md` |
| 本書がカバーする FR | FR-01〜FR-14, FR-16〜FR-20, FR-22, FR-23, FR-24（FR-18 データ品質パネルは §6.4 SC-06 の P1 / P2 / P3 三分割で実装） |
| 本書がカバーする NFR | NFR-01〜NFR-15（NFR-12 は §2.5 の終了コード、§5.4 規則 6 のアトミック書き込み、§5.5 の書き出し前検査でデータ側を担保。運用面はスコープ外） |
| 本書がカバーする SC | SC-01, SC-02, SC-03, SC-04, SC-05, SC-06 |
| 本書のスコープ外 | FR-15 の重ね合わせ UI 詳細（SC-02 の実装方針は §6 に記載、細部は実装時に確定）、FR-21 / IF-04 の GitHub Actions ワークフロー定義、**NFR-12 のうち配信可用性の運用**（監視・復旧手順。データ側の担保は上記のとおり本書が扱う）、Claude Code の hooks / subagent / skill を用いた開発体制の設計（ai-developer / ci-cd-engineer 管轄） |

### 1.2 設計方針

要件が採用した「二段ハイブリッド（決定論ファースト + LLM フォールバック + URL 単位キャッシュ）」と「カタログ駆動」を、実装レベルでは次の 4 つの構造として表現する。

| 要件の決定 | 実装での表現 |
|---|---|
| カタログ駆動（FR-03 / NFR-09） | 業態名・指標名・別名をコードに一切書かない。`catalog.py` が唯一のカタログ読取口であり、パーサは `Catalog` オブジェクト経由でのみ ID を得る。カタログに無い ID をコードが生成する経路を持たない（FR-24） |
| 二段ハイブリッド（FR-04 / FR-07） | `parser.py`（決定論）と `llm.py`（フォールバック）が同一の `Observation` dataclass を返す。呼び出し側は `extraction_method` フィールドでしか両者を区別しない。LLM が無効（`--no-llm`）でもパイプライン全体が完走する |
| 非決定性の封じ込め（NFR-06 / リスク 7-6） | LLM は `cache.py` の背後にのみ存在する。キャッシュヒット時は LLM を呼ばない。永続化される全レコードのタイムスタンプは**掲載日（ファイル名の日付）由来**であり実行時刻を含まない。実行時刻を持つ `runs.json` のみバイト一致保証の対象外とする |
| 冪等 upsert（FR-09 / NFR-07） | natural key `(segment_id, metric_id, scope, period_key, source_authority)` を `store.py` の `upsert()` に閉じ込める。パーサは重複を意識しない。同一記事が N 日掲載されても、`SourceArticle.appeared_dates` が伸びるだけで observation は増えない |
| 発表主体による系列分離（要件 7-14） | 母集団の異なる統計を上書きさせない。`source_authority` を natural key に含めることで、協会統計と政府統計が **別レコードとして共存**する。画面側でも同一チャートに混在させない（§6.4）。判定は `parser.resolve_authority()` の 1 箇所に閉じる |
| 対象範囲の明示（要件 7-15 / NFR-05） | 個社決算・非統計記事を `out_of_scope` として**明示的に分類**し、NFR-05 の分母から除外する。破棄も silent skip もしない。SC-06 に「対象外」として独立表示し、取りこぼし（`no_segment_match`）と区別できるようにする |
| **値トークンの完全な追跡（FR-10）— 無条件の絶対条件** | **値トークンが observation にも `unresolved` にも現れない状態を、いかなる理由があっても作らない。** タイトルから切り出した値トークンは、observation として採用するか `unresolved` に退避するかの**どちらかに必ず着地する**。着地しない経路をコードに持たない（§4.3.5 の残余語ガード / §4.3.7 の判定木がこの不変条件を担保する） |

**FR-10 は他のどの判断よりも優先する。** 値トークンが痕跡なく消える状態は、本節が挙げた silent accumulation（例外にならず不在として蓄積する失敗）の**最も直接的な形**である。NFR-05 の分子が減ること、実装が複雑になること、`unresolved` の件数が増えて画面が汚れて見えることは、いずれもこの原則を曲げる理由にならない。設計上のトレードオフの対象にしない条件として扱う（設計工程での確定は §9.3 の D5）。

補足として、決定論パースの実装は既存の [`parse-wbs.py`](../../../../.claude/hooks/parse-wbs.py) の header-aware パース手法を踏襲する（§2.4 で再利用範囲を明示）。

### 1.3 全体構成図

```
                                repo root
  ┌──────────────────────────────────────────────────────────────────────┐
  │                                                                      │
  │  scripts/retail-stats-tracker/            [実装コード：本書の主対象]  │
  │    retail_stats/                                                     │
  │      cli.py ─────────── build / html / measure サブコマンド           │
  │        │                                                             │
  │        ├─▶ catalog.py ──────┐                                        │
  │        ├─▶ digest.py ───────┤                                        │
  │        ├─▶ parser.py ───────┼──▶ models.py (dataclass)               │
  │        │     └─ period.py   │                                        │
  │        ├─▶ llm.py ──────────┤                                        │
  │        ├─▶ store.py ────────┘                                        │
  │        ├─▶ report.py                                                 │
  │        └─▶ html/build.py                                             │
  │                                                                      │
  └──────────────────────────────────────────────────────────────────────┘
             │ read-only                │ read/write            │ write
             ▼                          ▼                       ▼
  ┌─────────────────────────┐  ┌──────────────────────┐  ┌────────────────┐
  │ .companies/domain-tech- │  │ .companies/domain-   │  │ docs/          │
  │ collection/docs/        │  │ tech-collection/     │  │  retail-stats/ │
  │   daily-digest/*.md     │  │ docs/retail-stats/   │  │    index.html  │
  │     (IF-01)             │  │   data/              │  │  (IF-05)       │
  │   retail-domain/        │  │     observations.json│  │                │
  │     retail-monthly-     │  │     articles.json    │  │  GitHub Pages  │
  │     kpi-catalog.md      │  │     extraction-      │  └────────────────┘
  │     (IF-02)             │  │       cache.json     │
  └─────────────────────────┘  │     unresolved.json  │
                               │     manifest.json    │
                               │     runs.json        │
                               │     series.json      │
                               └──────────────────────┘
```

パイプライン内部のデータフローは次のとおり。

```
  digest/*.md          catalog.md
      │                    │
      ▼                    ▼
  ┌────────────┐      ┌──────────┐
  │ digest.py  │      │catalog.py│  ← 見出し部分一致 / 列名許容リスト / 整合チェック
  │  FR-01/02  │      │  IF-02   │     不整合は即エラー停止（FR-24）
  └─────┬──────┘      └────┬─────┘
        │ DigestRow[]      │ Catalog
        └────────┬─────────┘
                 ▼
        ┌──────────────────┐
        │ articles 集約     │  URL で dedup、title_variants 蓄積、
        │  (store.py)      │  appeared_dates 追記（NFR-07）
        └────────┬─────────┘
                 │ SourceArticle[]（一意 URL 単位）
                 ▼
        ┌──────────────────┐    hit
        │ cache.py 参照     │─────────────┐
        │   FR-08          │              │
        └────────┬─────────┘              │
                 │ miss                   │
                 ▼                        │
        ┌──────────────────┐              │
        │ parser.py        │              │
        │  正規化 → 値抽出  │              │
        │  → 指標/業態解決  │              │
        │  → 期間解決       │              │
        │  → confidence     │              │
        └────────┬─────────┘              │
                 │                        │
      conf>=0.70 ├────────────────────────┤
                 │ conf<0.70 / 未解決      │
                 ▼                        │
        ┌──────────────────┐              │
        │ llm.py           │              │
        │  スキーマ検証     │──失敗──▶ unresolved.json
        │  1回リトライ      │              │
        └────────┬─────────┘              │
                 │ 成功 → cache へ追記     │
                 └────────┬───────────────┘
                          ▼
                 ┌──────────────────┐
                 │ store.upsert()    │  natural key で収束（FR-09）
                 │  manual_override  │  保護（FR-23）
                 └────────┬─────────┘
                          ▼
              observations.json / series.json
                          │
                          ▼
                 ┌──────────────────┐
                 │ html/build.py    │  JSON + JS + CSS + Chart.js を
                 │  FR-13/14        │  単一 HTML にインライン埋め込み
                 └──────────────────┘
```

---

## 2. ディレクトリ・モジュール構成

### 2.1 配置先の決定

[`.claude/rules/artifact-placement.md`](../../../../.claude/rules/artifact-placement.md) の配置マトリクスには「アプリケーションコード」の行が無い。禁止事項（リポジトリルート直下への業務成果物、`.claude/` 配下への業務成果物）に抵触しない範囲で、既存の前例から選定した。

| 候補 | 前例 | 採否 | 理由 |
|---|---|---|---|
| `.claude/hooks/retail_stats/` | `parse-wbs.py` / `daily-insights-sync.py` 等 21 本 | 不採用 | `hooks/` は「1 ファイル 1 責務のグルースクリプト」の置き場であり、実体は Bash 16 本 + Python 5 本のフラット構造。8 モジュール + テスト + フロント資産を持つパッケージを混ぜると、hook 一覧の可読性が落ちる |
| `scripts/retail-stats-tracker/` | `scripts/sync-to-dist.sh`（リポジトリ横断ツール） | **採用** | ルート直下ではなく `scripts/` 配下であり禁止事項に触れない。`scripts/` は既にリポジトリ横断ツールの置き場として存在する。パッケージ単位のサブディレクトリを持てる |
| `.companies/domain-tech-collection/docs/retail-stats/src/` | なし | 不採用 | `docs/` はドキュメントの置き場であり、実行コードを混ぜると成果物レビューの単位が壊れる。また将来 `--org` で他組織に適用する際に置き場が破綻する |

**決定**: コードは `scripts/retail-stats-tracker/`、データは要件 §1.4 のとおり `.companies/{org}/docs/retail-stats/data/`、配信 HTML は要件 IF-05 のとおり `docs/retail-stats/index.html` に置く。

トレードオフ: コードが組織スコープ外（`scripts/`）、データが組織スコープ内（`.companies/`）に分かれるため、1 つの PR が両方をまたぐ。ただしこれは `.claude/hooks/parse-wbs.py`（コードは横断、出力は組織スコープ）と同じ形であり、リポジトリ内で一貫している。

### 2.2 ディレクトリツリー

```
scripts/retail-stats-tracker/
├── README.md                     ← 実行方法・データ再構築手順
├── retail_stats/
│   ├── __init__.py
│   ├── __main__.py               ← python3 -m retail_stats のエントリ
│   ├── cli.py                    ← 引数解析・サブコマンド振り分け
│   ├── config.py                 ← パス解決・閾値定数（org 依存を集約）
│   ├── models.py                 ← dataclass 群（他モジュールに依存しない）
│   ├── textnorm.py               ← 表記ゆれ正規化（FR-05）。依存なし
│   ├── catalog.py                ← カタログローダ（FR-03 / FR-24 / IF-02）
│   ├── digest.py                 ← ダイジェスト走査・表行分解（FR-01 / FR-02）
│   ├── period.py                 ← 期間解決（FR-06）
│   ├── parser.py                 ← 決定論パース本体（FR-04 / FR-05 / FR-11）
│   ├── llm.py                    ← LLM フォールバック（FR-07 / IF-03）
│   ├── cache.py                  ← 抽出キャッシュ（FR-08）
│   ├── store.py                  ← JSON 永続化・冪等 upsert（FR-09 / FR-23）
│   ├── report.py                 ← 差分レポート・reason_code 集計（FR-22）
│   └── html/
│       ├── __init__.py
│       ├── build.py              ← 単一 HTML 生成（FR-13 / FR-14）
│       ├── template.html         ← 骨格（プレースホルダのみ）
│       ├── app.js                ← ビュー切替・描画・CSV 出力
│       ├── styles.css            ← 画面 + 印刷スタイル
│       └── vendor/
│           ├── chart.umd.min.js  ← Chart.js 実体（要件 §5.4）
│           └── LICENSE-chartjs    ← MIT ライセンス表記
└── tests/
    ├── __init__.py
    ├── test_textnorm.py
    ├── test_catalog.py
    ├── test_digest.py
    ├── test_period.py
    ├── test_parser.py
    ├── test_store.py
    ├── test_idempotency.py
    ├── make_fixtures.py          ← 実データからフィクスチャを切り出すツール
    └── fixtures/
        ├── catalog/
        │   ├── valid.md
        │   ├── missing_column.md
        │   ├── duplicate_heading.md
        │   ├── undefined_id.md
        │   └── unknown_authority.md
        └── digests/
            ├── 2026-04-15.md 〜 2026-04-23.md   ← s041442 の 6 日重複
            ├── 2026-07-22.md 〜 2026-07-26.md   ← 主要 4 業態 + 全角/半角混在
            └── 2026-04-14.md                    ← 決算・統計章が存在しない日
```

### 2.3 モジュールの責務と依存方向

依存は下から上への一方向のみ。循環は存在しない。

```
  レイヤ 4  cli.py ────────────────────────────────────┐
                │                                      │
  レイヤ 3  ┌───┴────┬─────────┬──────────┬─────────┐  │
            store.py  report.py  llm.py   html/build.py│
                │         │        │          │        │
  レイヤ 2  ┌───┴─────────┴────────┴──────────┘        │
            parser.py ──▶ period.py                    │
                │                                       │
  レイヤ 1  ┌───┴────┬──────────┬─────────┐            │
            catalog.py  digest.py  cache.py             │
                │         │          │                  │
  レイヤ 0  ┌───┴─────────┴──────────┴──────────────────┘
            models.py    textnorm.py    config.py
            （相互にも外部にも依存しない）
```

| モジュール | 責務 | 依存先 | 依存されない相手 |
|---|---|---|---|
| `models.py` | 全 dataclass 定義と enum。ロジックを持たない | なし | — |
| `textnorm.py` | 文字列正規化のみ。副作用なし | なし | — |
| `config.py` | リポジトリルート解決、org スコープのパス生成、閾値定数 | `pathlib` のみ | — |
| `catalog.py` | カタログ MD → `Catalog`。列名許容リスト、整合チェック、エラー停止 | models, textnorm | digest / parser に依存しない |
| `digest.py` | ダイジェスト MD → `DigestRow[]`。セクション判定と表行分解のみ。値の解釈は行わない | models, textnorm | catalog に依存しない（対称性のため意図的に分離） |
| `cache.py` | `cache_key → 抽出結果` の読み書き。追記のみ | models | llm に依存しない（llm が cache を使う、逆ではない） |
| `period.py` | 期間表現 → `Period`。掲載日を引数で受け取る（グローバル日時に触れない） | models, textnorm | — |
| `parser.py` | `DigestRow` + `Catalog` → `Observation[]` + `UnresolvedRow[]`。**本システムの中核** | models, textnorm, catalog, period | store に依存しない（永続化を知らない） |
| `llm.py` | 未解決行 → `Observation[]`。スキーマ検証とリトライ | models, catalog, cache | parser に依存しない |
| `store.py` | JSON 読み書き、natural key upsert、manual_override 保護、決定論シリアライズ | models, config | parser / llm に依存しない |
| `report.py` | 実行サマリー・reason_code 分布・上書き差分の整形 | models | — |
| `html/build.py` | `series.json` + テンプレート → 単一 HTML | models, config | パース系に依存しない |
| `cli.py` | 引数解析とパイプラインの結線のみ。ドメインロジックを持たない | 全レイヤ | — |

**この依存方向にした理由**: `parser.py` を永続化から切り離しておくと、§7 の単体テストが「タイトル文字列 → Observation」の純関数テストとして書ける。決定論パースの正規表現ルールは今後追加され続ける（要件リスク 7-7）ため、追加のたびにファイル I/O を伴わずに回帰確認できることを最優先した。

### 2.4 `parse-wbs.py` からの再利用範囲

| `parse-wbs.py` の実装 | 本システムでの扱い |
|---|---|
| `split_table_row()`（L107-114）— `\|` 分解と前後空白除去 | **そのまま移植**。`digest.py` / `catalog.py` の両方で使う |
| `is_separator_row()`（L117-119）— `^:?-+:?$` によるセパレータ判定 | **そのまま移植** |
| `detect_header_map()`（L122-137）— 許容名リストで canonical → index を作り、必須キーが揃った時のみヘッダ確定 | **設計を移植し、判定条件を差し替え**。digest 側は `記事` と `ソース` の両方が揃った時にヘッダ確定、catalog 側は必須列が全て揃った時に確定（欠けていればエラー停止、これは parse-wbs.py が「None を返してスキップ」するのと逆） |
| 見出しでヘッダマップをリセットする走査ループ（L262-299） | **設計を移植**。`###` 見出しで対象セクション判定を切り替え、`##` 見出しで打ち切る点は要件 FR-01 に合わせて変更 |
| `HEADER_ALIASES` 辞書による列名ゆらぎ吸収（L45-56） | **設計を移植**。中身は IF-02 の許容列名に差し替え |
| `infer_*_from_*()` 系の推測関数（L180-244） | **移植しない**。WBS は欠損値を推測で埋めてよいが、本システムは推測でのラベル付けを禁じている（カタログ §2.2 申し送り、FR-24） |
| `REPO_ROOT = Path(__file__).resolve().parents[2]` | **考え方のみ移植**。配置階層が違うため `config.py` で `.git` / `.claude-plugin` の存在を上位に辿って解決する |

### 2.5 エントリポイントと CLI インターフェース

```bash
# 増分実行（既定）。前回実行以降に内容が変わった MD のみ処理（FR-12）
python3 -m retail_stats build

# 全件再構築（FR-12）
python3 -m retail_stats build --rebuild

# LLM を新規に呼ばない（キャッシュヒットは使う。日次自動実行向け・要件 7-10 の第一候補）
python3 -m retail_stats build --no-llm

# 抽出キャッシュを破棄して LLM を再実行（要件リスク 7-6：明示指定時のみ）
python3 -m retail_stats build --rebuild --invalidate-cache

# HTML のみ再生成（データは変更しない）
python3 -m retail_stats html

# reason_code 別の未解決分布を計測する（要件リスク 7-7 / 実装ステップ M3 の完了判定）
python3 -m retail_stats measure --rebuild --report-json /tmp/measure.json
```

| 引数 | 対象サブコマンド | 既定値 | 意味 |
|---|---|---|---|
| `--org SLUG` | build / html / measure | `domain-tech-collection` | 処理対象組織。`.companies/{slug}/` を基点にする |
| `--rebuild` | build / measure | off | manifest を無視して全 MD を処理する（FR-12） |
| `--since YYYY-MM-DD` | build / measure | なし | 指定日以降の digest のみ処理（デバッグ用） |
| `--invalidate-cache` | build | off | `extraction-cache.json` を破棄して LLM を再実行する。**指定しない限りキャッシュは絶対に破棄しない** |
| `--no-llm` | build / measure | off | **LLM を新規に呼ばない**。`extraction-cache.json` のヒットは通常どおり使う。キャッシュに無い閾値未満の行のみ unresolved に落とす（下記に詳述） |
| `--dry-run` | build | off | 標準出力にサマリーを出すのみでファイルを書かない |
| `--report-json PATH` | build / measure | なし | 差分レポートを JSON で書き出す（FR-22 の PR 本文生成用） |
| `--fail-on-unresolved-rate R` | build / measure | なし | 未解決率が R を超えたら exit 1（NFR-05 の CI ガード） |

**`--no-llm` の意味を確定する（ループ設計からの確認依頼への回答）**。`--no-llm` は **(A) LLM を新規に呼ばない**であり、**(B) LLM 由来の抽出を一切使わない（キャッシュヒットも捨てる）ではない**。閾値未満の行の処理順序は次のとおり:

```
閾値未満の行
  ├─ extraction-cache.json にヒット → キャッシュの observation を採用（--no-llm でも同じ）
  └─ キャッシュミス
        ├─ --no-llm あり → LlmClient を呼ばずに unresolved へ（NullClient と同じ結果）
        └─ --no-llm なし → ClaudeCliClient を呼び、結果をキャッシュに追記
```

(A) を採る根拠:

| # | 根拠 |
|---|---|
| 1 | **責務の重複を避ける**。キャッシュを使わせない役割は `--invalidate-cache` が既に担っている。`--no-llm` にも同じ効果を持たせると 2 つのフラグが同じ意味を持つ |
| 2 | **「指定しない限りキャッシュは絶対に破棄しない」原則**（`--invalidate-cache` の説明）と整合する。(B) は `--no-llm` を暗黙の破棄フラグにしてしまう |
| 3 | **キャッシュを Git 管理する設計（§5.3）が意味を持つのは (A) のときだけ**。v0.1 は「`ClaudeCliClient` によるローカル実行 + キャッシュ commit を既定とし、日次自動実行は `--no-llm`」（§4.6.1）という分業であり、commit したキャッシュを日次実行が使えなければ commit する理由が無くなる |
| 4 | **冪等性検証（§5.1）が成立する**。`--no-llm` で 2 回実行してバイト一致を見る設計は、キャッシュヒットが安定して同じ observation を返すことに依拠している |

**ループ設計 R2（no-drift 検査）への回答**: R2 が前提としている (A) が正である。committed の出力（LLM 結果を含む）と `--rebuild --no-llm` の出力は、キャッシュが commit されている限り一致するため、R2 は恒常 fail しない。ただし**キャッシュに無い記事を新規に LLM で解決した直後は、キャッシュを同じ PR に含めない限り R2 が落ちる**。`extraction-cache.json` を成果物 PR に必ず同梱すること（§5.3 の「Git 管理: 対象」はこのためでもある）。

§4.6.1 の `NullClient` は「キャッシュミス時に呼ばれるクライアント」の実装であり、キャッシュ層より下に位置する。同節の「日次自動実行は `--no-llm` で決定論パースのみとする」という記述は、**新規の LLM 呼び出しを行わないという意味**であって、キャッシュ済みの LLM 結果を捨てる意味ではない。

**終了コード**: 0 = 正常、1 = データ不整合（カタログ検証失敗・未解決率超過）、2 = 引数エラー、3 = I/O エラー。`2>/dev/null` や `|| true` による握り潰しは行わない（NFR-10）。生成失敗時は既存の成果物を空で上書きしない（NFR-12）。書き込みは全て一時ファイル + `os.replace()` によるアトミック置換とする。

---

## 3. カタログローダ設計

### 3.1 IF-02 スキーマ契約の実装

`catalog.py` は次の 4 段階で処理する。いずれの段階でも、曖昧なまま読み進めることをしない。

#### 段階 1: 見出し検出（部分一致・番号非依存）

```python
SEGMENT_HEADING_KEYWORDS = ("業態区分",)
METRIC_HEADING_KEYWORDS = ("指標定義", "KPI定義")   # 照合前に空白を除去する

def _find_h2(lines: list[str], keywords: tuple[str, ...]) -> int:
    """条件に一致する H2 の行番号を返す。0 個または 2 個以上ならエラー停止。"""
    hits = []
    for i, line in enumerate(lines):
        m = re.match(r"^##\s+([^#].*)$", line.strip())
        if not m:
            continue
        text = re.sub(r"\s+", "", m.group(1))     # "KPI 定義" → "KPI定義"
        if any(kw in text for kw in keywords):
            hits.append(i)
    if len(hits) != 1:
        raise CatalogError(
            f"見出し検出に失敗しました: keywords={keywords} 一致数={len(hits)}"
            f" 一致行={[lines[i].strip() for i in hits]}"
        )
    return hits[0]
```

現行カタログでの検出結果（実測済み）:

| 対象 | 一致した H2 | 行番号 |
|---|---|---|
| 業態定義 | `## 1. 業態区分マスタ` | 20 |
| 指標定義 | `## 2. KPI 定義` | 84 |

（`grep -n "^## " retail-monthly-kpi-catalog.md` の実行結果は 12 / 20 / 84 / 138 / 163 / 234。行番号はカタログ改訂で動くため、実装は行番号に依存せず見出しテキストの部分一致で検出する。上表は本書執筆時点の位置を示す参考値）

`## 0. このカタログの前提` `## 3. ドメイン上の落とし穴` `## 4. 正規化ルール表` `## 5. 出典` はいずれにも一致せず、多重一致は発生しない。

#### 段階 2: 定義表の特定

検出した H2 の次の行から、**次の H2 の直前まで**を走査し、**最初に現れた MD テーブル**（区切り行を伴う行）を定義表とする。H3 小見出しを挟んでもよい。

現行カタログでは、`## 2. KPI 定義` の配下に §2.1 KPI 一覧、§2.2 の比較表、§2.3 の対応マトリクスの 3 つのテーブルがある。§2.3 のマトリクスは 1 列目が `metric_id` の値（`sales-amount-absolute` 等）であり、これを誤って定義表として読むと列数・列名が全く合わない。「最初のテーブル」規則はこの誤読を構造的に防いでいる。

#### 段階 3: 列名解決（許容リスト）

```python
SEGMENT_COLUMNS: dict[str, tuple[str, ...]] = {
    "segment_id":        ("segment_id", "業態ID"),
    "name":              ("名称", "正式名称"),
    "aliases":           ("別名", "表記ゆれ"),
    "entity_type":       ("種別",),
    "source_authority":  ("発表主体",),
    "display_order":     ("表示順",),
}
SEGMENT_OPTIONAL_COLUMNS = {"parent_segment_id": ("上位業態",)}

METRIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "metric_id":     ("metric_id", "KPI ID", "KPIID"),
    "name":          ("名称", "正式名称"),
    "aliases":       ("別名", "表記ゆれ"),
    "unit_raw":      ("単位",),
    "value_type":    ("値種別",),
    "direction_hint": ("方向",),
    "default_scope_raw": ("既定スコープ", "既存店/全店"),
    "precision":     ("小数桁",),
}
```

照合は「ヘッダセルの前後空白除去 + 内部空白除去 + バッククォート除去」後の完全一致で行う（`KPI ID` と `KPIID` の両方を受理するため許容リストに両形を入れている）。定義表に許容リスト外の列（`公表サイクル` `定義・カバー範囲` `主な適用業態` `解釈上の注意`）があっても無視する。**`発表主体` は無視してはならない**。natural key の第 5 要素 `source_authority` を供給する必須列であり、上記 `SEGMENT_COLUMNS` に `"source_authority": ("発表主体",)` として含まれている（§9.3 の D1 で必須列に昇格）。必須列が 1 つでも解決できなければ `CatalogError` で停止する（FR-24）。欠損列を既定値で埋めて続行しない。

#### 段階 4: セル値の解釈

カタログのセルは装飾を含むため、順序を固定した前処理を行う。

```python
def clean_cell(cell: str) -> str:
    s = cell.strip()
    s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)        # 強調を剥がす
    s = s.replace("`", "")                         # `shopping-center` → shopping-center
    return s.strip()

def cell_head(cell: str) -> str:
    """括弧注記と併記を落として先頭のラベルだけを取る。
    '該当なし（`co-op` は総供給高で上書き。§4.5 参照）'         → '該当なし'
    '経済産業省（商業動態統計）／個社開示'                       → '経済産業省'
    '業界紙（DCS）集計（協会名は記事本文未確認。※業界一般知識…）' → '業界紙'
    """
    s = clean_cell(cell)
    s = re.split(r"[（(／/]", s, maxsplit=1)[0]
    return s.strip()

ALIAS_SPLIT_RE = re.compile(r"[,、/／]")

def split_aliases(cell: str) -> list[str]:
    s = clean_cell(cell)
    out = [a.strip() for a in ALIAS_SPLIT_RE.split(s) if a.strip()]
    return [a for a in out if a not in ("", "—", "-", "－")]
```

`cell_head()` が必要な実例は `sales-amount-absolute` の既定スコープ列であり、実セルは `該当なし（`co-op` は総供給高で上書き。§4.5 参照）` である。ここから `該当なし` を取り出して `n_a` に変換する。`co-op` への上書きは §3.3 のスコープ解決規則で扱う。

単位列は 1 セル内に複数トークンを含みうるため（`sales-amount-absolute` の実セルは `億円 / 兆円`）、**トークンごとに照合**する。

```python
UNIT_TOKEN_MAP = {"%": "percent_yoy", "％": "percent_yoy",
                  "億円": "jpy_oku", "兆円": "jpy_oku"}

def resolve_unit(cell: str, metric_id: str) -> str:
    tokens = [t.strip() for t in re.split(r"[/／,、]", clean_cell(cell)) if t.strip()]
    units = {UNIT_TOKEN_MAP[t] for t in tokens if t in UNIT_TOKEN_MAP}
    if not units:
        raise CatalogError(f"単位を解決できません: metric_id={metric_id} cell={cell!r}")
    if len(units) > 1:
        raise CatalogError(f"単位が複数の enum に解決されます: metric_id={metric_id} {units}")
    return units.pop()
```

`億円 / 兆円` は 2 トークンとも `jpy_oku` に写るため集合は 1 要素になり、格納単位は `jpy_oku` に一本化される。`兆円` 表記の値は取り込み時に ×10,000 して億円に換算する（要件 IF-02 単位対応表、カタログ §4.4）。

### 3.2 内部表現

```python
# models.py
from dataclasses import dataclass, field

dataclass(frozen=True)
class Segment:
    segment_id: str
    name: str
    aliases: tuple[str, ...]          # 名称を含めて重複除去済み・長い順にソート済み
    parent_segment_id: str | None
    entity_type: str                  # association / company / macro
    source_authority: str             # 既定の発表主体コード（IF-02 発表主体対応表で解決）
    source_authority_label: str       # 表示用。カタログ「発表主体」列の原文
    display_order: int

dataclass(frozen=True)
class Metric:
    metric_id: str
    name: str
    unit: str                         # percent_yoy / percent / jpy_oku / count / index
    value_type: str                   # ratio / absolute
    direction_hint: str               # higher_is_better / lower_is_better / neutral
    aliases: tuple[str, ...]          # 名称を含めて重複除去済み・長い順にソート済み
    default_scope: str                # existing_store / all_store / total_supply / n_a
    precision: int

dataclass(frozen=True)
class Catalog:
    segments: tuple[Segment, ...]     # display_order 昇順
    metrics: tuple[Metric, ...]       # カタログ記載順
    source_path: str
    source_sha256: str                # カタログ改訂の検知に使う

    def segment(self, segment_id: str) -> Segment: ...   # 未定義なら CatalogError
    def metric(self, metric_id: str) -> Metric: ...      # 未定義なら CatalogError
    # 別名 → ID の逆引き索引。長い別名を先に照合するため長さ降順で保持する
    def segment_alias_index(self) -> tuple[tuple[str, str], ...]: ...
    # 指標側は 1 別名が複数 ID に対応しうる（V12 の緩和。§3.3）。
    # 同一別名を共有できるのは value_type が異なる指標間のみで、V12 がそれを保証する
    def metric_alias_index(self) -> tuple[tuple[str, tuple[str, ...]], ...]: ...
```

`aliases` に `name` を必ず含める理由は、カタログの別名列が名称と重複していないケース（`shopping-center` の別名は `ショッピングセンター` のみ、`electronics-retailer` は `家電大型専門店` のみ）と、含んでいるケースの両方が存在するためである。ローダ側で正規化しておけば、パーサは別名索引だけを見ればよい。

別名索引を**長さ降順**で保持するのは最長一致のためである。`既存店売上高`（6 文字）> `既存店売上`（5 文字）> `既存店`（3 文字）の順に照合しないと、`既存店売上高` が `既存店` にマッチしてしまう。

### 3.3 バリデーション（FR-24）

`Catalog.validate()` が以下を検査し、1 つでも違反があれば全件を列挙した `CatalogError` を送出して **exit 1** で停止する。部分的に読み込んで続行しない。

| # | 検査 | 違反時のメッセージ例 |
|---|---|---|
| V1 | `segment_id` / `metric_id` が kebab-case（`^[a-z0-9]+(-[a-z0-9]+)*$`） | `不正な ID 形式: 'Shopping Center' (行 28)` |
| V2 | `segment_id` / `metric_id` が一意 | `segment_id が重複しています: 'co-op' (行 36, 41)` |
| V3 | `entity_type` ∈ {association, company, macro} | `未知の 種別: 'アソシエーション' (segment_id=co-op)` |
| V4 | `value_type` ∈ {ratio, absolute} | 同上の形式 |
| V5 | `direction_hint` ∈ {higher_is_better, lower_is_better, neutral} | 同上 |
| V6 | `unit` が §3.1 の単位対応表で一意に解決できる | `単位を解決できません: metric_id=xxx cell='—'` |
| V7 | `default_scope` が `{既存店: existing_store, 全店: all_store, 総供給高: total_supply, 該当なし: n_a}` で解決できる | `既定スコープを解決できません: metric_id=xxx cell='店舗別'` |
| V8 | `precision` / `display_order` が非負整数 | `小数桁が整数ではありません: 'N/A'` |
| V9 | `parent_segment_id` が空でなければ `segments` に存在する | `未定義の 上位業態: 'xxx' (segment_id=yyy)` |
| V10 | `parent_segment_id` の参照に循環がない | `上位業態に循環があります: a → b → a` |
| V11 | 別名が空でない（各行 1 つ以上） | `別名が空です: segment_id=xxx` |
| V12 | 別名が **業態内 / 指標内で重複しない**。ただし **値種別（`value_type`）が異なる指標間では同一別名を許す**。値種別が同一の指標間では引き続き禁止する | `別名 '売上高' が metric_id=A と metric_id=B で重複しています（ともに value_type=ratio）` |
| V13 | `発表主体` 列の先頭トークンが IF-02 発表主体対応表に存在する | `未知の発表主体: '日本DIY・ホームセンター協会' (segment_id=home-center)。IF-02 発表主体対応表への追加が必要です` |

V12 は決定論パースの解決可能性に直結する。別名が衝突していると、どの ID に寄せるかがコード側の暗黙のルールになってしまい NFR-09（カタログ追記だけで完結する）が崩れる。

**値種別が異なる場合に限って重複を許す理由**（Issue #729 で確定）。決め手は**曖昧性が記事側に実在する**ことである。

```
  売上高3.2％増       → 率（ratio）
  売上高1兆4505億円   → 絶対額（absolute）
```

同じ `売上高` という語が両方を指しており、これは**記事表記の性質であってカタログの設計不備ではない**。カタログ §2.2 は既に「単に『売上高』であれば `sales-amount-absolute` または `all-store-sales-yoy`（絶対額か率かでさらに分岐）」と分岐条件を言語化しているのに、改訂前の V12 がその表現自体を禁じていた。**§2.2 と V12 が両立していなかった**のであり、本改訂は §2.2 が既に持っている分岐条件を V12 の例外として書き下ろしたものである。

改訂前の V12 のもとでは、`日本百貨店協会／3月の売上高3.2％増` のような**率**の値が `all-store-sales-yoy` に解決できず `no_metric_match` に落ちていた（実測 3 行。うち 2 行は日本百貨店協会の月次統計そのもので、本システムが最も取りたい種類のデータである）。

**値種別が同一の指標間での重複禁止は維持する。** ここを緩めると、値の型で候補を絞っても一意に決まらず、「どの ID に寄せるか」が結局コード側の暗黙ルールになる。**NFR-09 が崩れる境界はこの 1 点**であり、V12 後半の禁止はその防波堤として機能する。

この緩和により、**値の型（率 / 絶対額）による候補の絞り込みは設計上の正式な解決手段になる**（暫定回避ではない）。実装は §4.3.4 の `resolve_metric()` に閉じる。型フィルタが無い状態では `3.2`（%）が単位 `jpy_oku` の指標に格納される——**率を億円として蓄積する**——誤格納が起こり、例外にならないため golden-60 のような評価データが無ければ検知できない。§4.3.2 の金額換算バグと同じ silent accumulation の類型である。

**`parent_segment_id` は集約に使わない**。この列は表示上の系統情報としてのみ保持し、**子 segment の値を親に足し上げるロールアップ処理を一切実装しない**。

理由は、経産省統計を個別業態の親として扱うのがドメイン上の誤りであるため。カタログ改訂で `electronics-retailer` の `上位業態 = meti-commerce-dynamics` リンクは削除され、`meti-commerce-dynamics` は「小売業全体」という独立した集計区分に定義が狭められた（カタログ §1.1 / §1.4）。仮に親子集約を実装していると、「小売業全体」の値と各業態の内訳が二重計上される。**現行カタログでは 13 行すべての `上位業態` が空欄**であり、V9 / V10 は将来 `種別=company` 行が追加された場合（カタログ §1.5 では個社の `上位業態` に所属業態を書く想定）に備えた防御的検査として残す。その場合も用途は画面上のグルーピング表示に限り、値の集約には使わない。

**`co-op` × `sales-amount-absolute` のスコープ上書き（カタログ §4.5）** はカタログ表の 1 セルでは表現されないため、ローダではなくパーサ側の解決規則として実装する。ローダは `default_scope = n_a` をそのまま保持する。

```python
# parser.py
def resolve_scope(metric: Metric, segment: Segment, window_text: str) -> str:
    # 1) 記事に「既存店」の文字列がある場合のみ existing_store を許す（カタログ §2.2）
    if "既存店" in window_text:
        return "existing_store"
    # 2) 生協 × 売上高（絶対額）は total_supply に上書き（カタログ §4.5）
    if segment.segment_id == "co-op" and metric.metric_id == "sales-amount-absolute":
        return "total_supply"
    # 3) それ以外はカタログの既定スコープ
    return metric.default_scope
```

**カタログ改訂の検知**: `Catalog.source_sha256` を `runs.json` に記録する。前回実行と値が異なる場合、差分レポートに `カタログが改訂されています。IF-02 の見出し検出条件・単位対応表・スコープ対応表の 3 点を再確認してください`（要件 7-9）を出力する。

---

## 4. パーサ設計

本システムの中核。`digest.py` が行を切り出し、`parser.py` が値を解釈する。

### 4.1 セクション抽出と表行トークン化（FR-01 / FR-02）

```python
SECTION_KEYWORD = "決算・統計"      # 章番号（B5）では判定しない（要件 7-1）

DIGEST_COLUMNS = {
    "index":   ("#", "No", "番号"),
    "article": ("記事", "タイトル", "Article"),
    "source":  ("ソース", "出典", "Source"),
    "summary": ("要約", "概要", "Summary"),
}
```

走査規則:

1. `^###\s+(.+)$` に一致したら、見出しテキストに `決算・統計` を**含むか**で対象フラグを立て直す。章番号は見ない
2. `^##\s+` に一致したら対象フラグを落とす（章の切り替わり）
3. 対象フラグが立っている間、`|` 開始行を `split_table_row()` で分解する
4. 区切り行はスキップ
5. ヘッダ行（`記事` と `ソース` の両方が解決できる行）で列マップを確定する。**列マップが確定していない状態のデータ行は捨てずに `unresolved` に落とす**（silent な欠測を防ぐ、要件 7-12）
6. 記事セルから `\[(?P<title>.+?)\]\((?P<url>https?://[^\s)]+)\)` を抽出する。抽出できない行は `unresolved`（`no_metric_match` ではなく後述の `malformed_row` 相当として `low_confidence` に寄せる）

実測（2026-03-21 〜 2026-07-26 の 102 ファイル）:

| 項目 | 実測値 |
|---|---|
| 決算・統計章を持つファイル | 93（章が無い日は 9 日: 03-21 / 03-23 / 03-24 / 03-25 / 03-26 / 03-27 / 03-29 / 03-30 / 04-14） |
| 表を持つファイル | 89 |
| ヘッダ行のバリエーション | `('#', '記事', 'ソース', '要約')` の **1 種類のみ**（89 ファイル全て） |
| データ行（延べ） | 595 |
| リンク抽出成功 | 595 / 595（100%） |
| 一意 URL | 406 |

要件 §1.1 の実測（101 ファイル / 588 行 / 一意 405）との差は、本書執筆時点で 2026-07-26 のダイジェストが 1 日分追加されたことによる。母数の性質は変わっていない。

章が無い日は例外ではなく通常系として扱い、スキップ日数を `runs.json` の `files_without_section` に記録する（要件 7-1）。

```python
dataclass(frozen=True)
class DigestRow:
    digest_date: str        # "2026-07-25"（ファイル名由来）
    row_index: int          # 表内の # 列の値
    title: str              # 原文（正規化前）
    url: str
    source_name: str
    summary: str
    raw_line: str           # 未解決時の証跡（FR-10）
```

### 4.2 表記ゆれ正規化（FR-05）

`textnorm.normalize()` は次の順序で適用する。順序を変えると結果が変わるため、テストで順序を固定する。

```python
import re, unicodedata

_KA_MONTH_RE   = re.compile(r"[ヶヵカか](?=月)")
_SP_IN_NUM_RE  = re.compile(r"(?<=[0-9])\s+(?=[0-9])")
_SP_BEFORE_UNIT_RE = re.compile(r"(?<=[0-9])\s+(?=[月%期年日度億兆万円])")
_SP_BEFORE_PCT_RE  = re.compile(r"\s+(?=%)")
# 桁区切りカンマ。終端条件に \b を使ってはならない（下記の注意を参照）
_THOUSAND_SEP_RE   = re.compile(r"(?<=[0-9]),(?=[0-9]{3}(?![0-9]))")

def normalize(s: str) -> str:
    # 1) NFKC: 全角％→%、全角数字→半角、／→/、（）→()、＝→=、＆→& を一括で吸収
    s = unicodedata.normalize("NFKC", s)
    # 2) NFKC が触らない波ダッシュ・ダッシュ類を ASCII に寄せる
    s = s.replace("〜", "~").replace("～", "~")
    s = s.replace("－", "-").replace("―", "-").replace("–", "-")
    # 3) カ月表記の統一（カ / ヶ / ヵ / か → カ）
    s = _KA_MONTH_RE.sub("カ", s)
    # 4) 数値内・数値と単位の間に混入した空白を除去
    s = _SP_IN_NUM_RE.sub("", s)
    s = _SP_BEFORE_UNIT_RE.sub("", s)
    s = _SP_BEFORE_PCT_RE.sub("", s)
    # 5) 数値の桁区切りカンマを除去（"1兆4,505億円" → "1兆4505億円"）
    s = _THOUSAND_SEP_RE.sub("", s)
    return s
```

**桁区切りカンマの終端条件に `\b` を使ってはならない**（実装上の落とし穴）。当初 `(?<=[0-9]),(?=[0-9]{3}\b)` と書いていたが、これは実データで発火しない。Python の `re` は CJK 文字を単語構成文字として扱うため、`4,505億円` の `505` と `億` の間に単語境界が存在せず、先読みが失敗する。

```python
>>> re.search(r"505\b", "505億円")     # None（CJK の直前に単語境界がない）
>>> re.search(r"505\b", "505 yen")     # マッチする
```

このバグの危険性は、**例外にも未解決行にもならず不正な値として蓄積する**点にある。カンマが残ったまま後段の `VALUE_JPY_RE` に渡ると、カンマで分断された `505億円` に一致して `505.0` を返す。正しい `14505.0` に対して約 30 倍の誤差が、警告なしに `observations.json` に入る。`(?![0-9])` に置き換えることで解決する（下記は実行結果）。

```
入力              旧 (?=[0-9]{3}\b)   新 (?=[0-9]{3}(?![0-9]))
1兆4,505億円      1兆4,505億円  NG     1兆4505億円   OK
8,577億円         8,577億円     NG     8577億円      OK
12,345,678円      12345,678円   NG     12345678円    OK
1,23億円          1,23億円      OK     1,23億円      OK   （3 桁でないので除去しない）
2026,1            2026,1        OK     2026,1        OK   （3 桁でないので除去しない）
```

各規則の根拠（計測日 **2026-07-26**、決算・統計章）。集計基準は 3 系統あり、値が大きく変わるため**どの基準かを必ず併記する**。

- **[行]** — データ行 595 行を対象。同一記事が N 日掲載されれば N 回数える
- **[一意]** — 一意 URL 406 件を対象。いずれかの variant が該当すれば 1 件
- **[代表]** — 一意 URL 406 件の代表 variant のみを対象（§4.7 の選択規則）

走査対象は **記事タイトルのみ**（要約・ソース名を含めない）。再現手順は付録 A のスクリプトを参照。

| 規則 | 実測での必要性 | [行] | [一意] | [代表] |
|---|---|---|---|---|
| NFKC（全角％→%） | 全角 `％` と半角 `%` が混在する。同一 URL 内でも混在する（`s071772` は 4 日掲載中 1 日のみ全角）。**どの基準でも両者が併存**しており、正規化しなければ値抽出が片方だけ落ちる | ％ 153 / % 172 | ％ 127 / % 129 | ％ 123 / % 94 |
| NFKC（全角数字→半角） | 決算・統計章のタイトルでは **0 件**。防御的措置として残すが、現行データでは発火しない | 0 | 0 | 0 |
| NFKC（`／`→`/`） | ほぼ全ての協会統計タイトルが `業態名／内容` 形式。区切り記号を統一しないと業態抽出位置の判定が二重になる | — | — | — |
| カ月統一 | `カ月` / `ヵ月` が併存。`ヶ月` `か月` はタイトル中 0 件だが、`ヵ` が実在する以上 4 種すべてを吸収する方が安全 | カ月 11 / ヵ月 1 / ヶ月 0 / か月 0 | 10 / 1 / 0 / 0 | 10 / 1 / 0 / 0 |
| 数値中の空白除去 | `イオン 決算／2 月期増収増益、営業収益は 5 期連続で過去最高に`、`ビックカメラ 決算／9〜2 月増収増益` 等。**同一 URL の別日 variant では空白が無い**ため、正規化しないと同一記事が別物として扱われる。§4.4.2 の span 判定にも影響する（後述） | 6 | 6 | 6 |
| 桁区切りカンマ除去 | タイトル中は `ツルハHD…売上高は1兆4,505億円` の 1 件。行全体（要約含む）では 11 件。同一企業の同一決算が `1兆4,505億円` と `1兆4505億円` の 2 表記で出現する | 1 | 1 | 1 |
| 波ダッシュ統一 | 月範囲表現に `〜`（U+301C）と `～`（U+FF5E）と ASCII `-` が混在する | 〜 63 / ～ 4 / - 1 | 39 / 3 / 1 | 37 / 3 / 1 |
| （参考）月範囲表現の総数 | 上記 3 種の区切りを含む `N〜M月` 形式 | 68 | 41 | 41 |

**旧版からの訂正**: 本表の数値は L2 レビューでの再現失敗を受けて全面的に再測定したものである。初版は集計基準（行 / 一意 / 代表）と走査範囲（タイトルのみ / 要約含む）を混在させていたため再現できなかった。特に `カ月 24 件` `全角％ 115 件・半角% 102 件` `月範囲 97 件` は誤りで、上表が正しい。**規則そのものの妥当性は変わらない**（いずれの基準でも表記ゆれの併存は確認できる）。

**元のタイトルは破棄しない**。`SourceArticle.title_first_seen` / `title_variants` は原文で保持し、正規化文字列はパース中のみ使う（`raw_expression` も原文からの切り出しとする）。

### 4.3 決定論パースのアルゴリズム

#### 4.3.1 基本方針: 数値トークンをアンカーにした後方探索

節（`、` `・` `。`）で分割してから指標を探す方式は、`6月既存店売上1.6%減、夏物振わず51カ月ぶりに前年割れ` のように「指標を含まない節」が混ざると破綻する。そこで**数値トークンを先に全て見つけ、各数値から左方向に指標別名を探す**。

```
  日本百貨店協会/6月の外国人売上29.8%増、客数0.5%減・客単価30.4%増
  ^^^^^^^^^^^^^^                                                    ← 業態アンカー（先頭）
                      ~~~~~~~~~~[29.8%増]                           ← 値①: 左窓に「外国人売上」
                                        ~~~~[0.5%減]                ← 値②: 左窓に「客数」
                                                  ~~~~~[30.4%増]    ← 値③: 左窓に「客単価」

  左窓の定義 = 「直前の数値トークンの終端」または「節区切り」または「/ の直後」のうち、
                最も右にある位置から、当該数値トークンの開始位置まで
```

#### 4.3.2 正規表現ルール

```python
# --- 値トークン ---------------------------------------------------------
# 「1.6%減」「29.8%増」「5.3%上昇」「4.4% growth」（方向語なしも許容）
VALUE_PCT_RE = re.compile(
    r"(?P<num>[0-9]+(?:\.[0-9]+)?)%"
    r"(?P<dir>増加|減少|上昇|下落|増収|減収|増益|減益|増|減|高|安|プラス|マイナス)?"
)

# 「233億円」「1兆4505億円」「4560億1000万円」「1兆円」「31億8500万円」「約1.5兆円」
# 各部は小数を許容する。整数限定にすると 1.5兆円 の整数部を捨てて 5兆円 に一致する
_JPY_NUM = r"[0-9]+(?:\.[0-9]+)?"
VALUE_JPY_RE = re.compile(
    rf"(?<![0-9.])"                        # 数値の途中から一致し始めるのを防ぐ
    rf"(?:(?P<cho>{_JPY_NUM})兆)?(?:(?P<oku>{_JPY_NUM})億)?(?:(?P<man>{_JPY_NUM})万)?円"
)

# --- 方向語（値に符号を与える） ------------------------------------------
POSITIVE_DIR = {"増", "増加", "上昇", "高", "プラス", "増収", "増益"}
NEGATIVE_DIR = {"減", "減少", "下落", "安", "マイナス", "減収", "減益"}

# --- 割・半減（カタログ §4.1） ------------------------------------------
WARI_RE   = re.compile(r"(?P<n>[0-9]+(?:\.[0-9]+)?)割(?P<dir>増|減)")
HANGEN_RE = re.compile(r"半減")

# --- 連続記録表現（カタログ §4.1） --------------------------------------
STREAK_BROKEN_RE = re.compile(r"(?P<n>[0-9]+)カ月ぶり(?:に|の)?(?:前年割れ|前年同月割れ)")

# --- 定性表現のみ（value 化不可、sign_only を立てる） --------------------
QUALITATIVE_RE = re.compile(r"(?P<a>増収|減収)(?P<b>増益|減益)?|(?P<c>増益|減益)")

# --- 横ばい（値 0.0 + 要出典確認） --------------------------------------
FLAT_RE = re.compile(r"横ばい")

# --- 節・窓の区切り ------------------------------------------------------
CLAUSE_SEP_RE = re.compile(r"[、。・/:：]")
```

`VALUE_JPY_RE` は全構成要素が任意のため空文字にもマッチしうる。`finditer` の結果は「`cho` / `oku` / `man` のいずれかが非 None」の条件で必ず絞り込む。

金額の換算（要件 IF-02 単位対応表 / カタログ §4.4）:

```python
def to_jpy_oku(m: re.Match) -> float:
    """兆・億・万を億円単位の float に畳む。1兆 = 10,000億、1万円 = 0.0001億円。"""
    part = lambda g: float(m.group(g)) if m.group(g) else 0.0
    return part("cho") * 10_000 + part("oku") + part("man") / 10_000
```

**検証結果**（`normalize()` を通した上で `VALUE_JPY_RE` + `to_jpy_oku()` を実行した実測。旧版＝小数非対応・カンマ除去バグありとの比較）:

| 入力 | 期待値（億円） | 旧版 | 新版 |
|---|---|---|---|
| `233億円` | 233.0 | 233.0 | 233.0 |
| `1兆4505億円` | 14505.0 | 14505.0 | 14505.0 |
| `1兆4,505億円` | 14505.0 | **505.0**（カンマ未除去） | 14505.0 |
| `8,577億円` | 8577.0 | **577.0**（カンマ未除去） | 8577.0 |
| `4560億1000万円` | 4560.1 | 4560.1 | 4560.1 |
| `31億8500万円` | 31.85 | 31.85 | 31.85 |
| `453億6000万円` | 453.6 | 453.6 | 453.6 |
| `256億3466万円` | 256.3466 | 256.3466 | 256.3466 |
| `13兆4470億円` | 134470.0 | 134470.0 | 134470.0 |
| `1兆円` | 10000.0 | 10000.0 | 10000.0 |
| `約1.5兆円` | 15000.0 | **50000.0**（整数部を捨て `5兆円` に一致） | 15000.0 |
| `1.45兆円` | 14500.0 | **450000.0** | 14500.0 |
| `2.55兆円` | 25500.0 | **550000.0** | 25500.0 |
| `11.9兆円` | 119000.0 | **90000.0** | 119000.0 |
| `1.234兆円` | 12340.0 | **2340000.0** | 12340.0 |
| `12,345,678万円` | 1234.5678 | **0.0678**（1 つ目のカンマのみ除去され `12345,678万円` → `678万円` に一致） | 1234.5678 |

旧版 8/16 合格、新版 **16/16 合格**。旧版が落ちた 8 件はいずれも例外を出さず誤った数値を返すため、`unresolved` にも差分レポートにも現れない。**silent に誤値が蓄積する経路**であり、テストで固定する（§7.2 T-3）。

**実データでの出現規模**（計測日 2026-07-26、決算・統計章）: 桁区切りカンマは記事タイトル中で 1 件（`ツルハHD、経営統合後の連結決算売上高は1兆4,505億円で営業利益は630億円`）、行全体（要約を含む）では 11 件（`1,002億円` `735億6,700万円` `13兆2,170億円` `8,135億円` 等）。小数付き兆円（`1.5兆円` 型）は行全体で複数存在する。タイトル基準の現時点の件数は小さいが、`兆` 単位の企業決算は継続的に流入するため、放置すると誤差が蓄積し続ける。

#### 4.3.3 業態の解決

**業態別名は「主語位置」で一致しなければならない**。カタログの業態別名には `外食` `百貨店` `コンビニ` `ドラッグストア` のような**汎用語**が含まれるため、タイトル中のどこでも一致を許すと、業態が主語でない記事を誤って取り込む。

```python
# 主語位置 = 「/」より前。「/」が無ければ最初の読点より前
def _subject_head(norm_title: str) -> str:
    if "/" in norm_title:
        return norm_title.split("/", 1)[0]
    if "、" in norm_title:
        return norm_title.split("、", 1)[0]
    return norm_title

# 主語位置に業態名が無くても、主語が発表主体そのものなら本文中の業態名を採る
AUTHORITY_HEAD_RE = re.compile(
    r"協会|連合会|組合|生協連|経済産業省|経産省|総務省|農水省|農林水産省|財務省|厚労省|国交省"
)

def resolve_segment(norm_title: str, catalog: Catalog) -> tuple[Segment | None, float]:
    """業態と confidence ペナルティを返す。"""
    head = _subject_head(norm_title)
    # 1) 主語位置で別名一致: ペナルティなし
    for alias, seg_id in catalog.segment_alias_index():        # 長さ降順
        if alias in head:
            return catalog.segment(seg_id), 0.00
    # 2) 主語が発表主体名の場合に限り、本文中の別名一致を許す
    #    例: 「経済産業省／2月の商業動態統計、小売業販売額は0.2％減…」
    #        主語は経産省だが、観測対象は本文の「商業動態統計（小売業全体）」
    if AUTHORITY_HEAD_RE.search(head):
        for alias, seg_id in catalog.segment_alias_index():
            if alias in norm_title:
                return catalog.segment(seg_id), 0.05
    # 3) それ以外は業態未解決。§4.3.7 の判定木で out_of_scope / no_segment_match に振る
    return None, 0.00
```

**このガードが防ぐ誤抽出**（実測 7 件。ガード導入前はいずれも業態が解決していた）:

| タイトル | 誤って解決していた業態 | 実際の主語 |
|---|---|---|
| `ワタミ 決算／3月期営業利益5.9％増、国内外食好調で客数増` | `family-restaurant`（`外食` に一致） | ワタミ（個社決算） |
| `薬王堂HD 決算／2月期増収減益、ドラッグストア事業「フード」売上高は10.5%増` | `drugstore` | 薬王堂HD（個社決算） |
| `J.フロント 決算／2月期営業利益15.8％減、SC好調も百貨店・デベロッパー事業減益` | `department-store` | J.フロント（個社決算） |
| `セブン＆アイ 決算／2月期は減収増益、国内コンビニ事業は1.2%増収` | `convenience-store` | セブン＆アイ（個社決算） |
| `三陽商会 決算／2月期減収減益、大江伸治社長「百貨店不振の影響受けた」` | `department-store` | 三陽商会（個社決算） |
| `3月消費支出、2.9％減＝節約志向で外食マイナス―総務省` | `family-restaurant`（`外食` に一致） | 総務省 家計調査の消費支出 |
| `スプラウツ、ナチュラルグローサーズ…「ウェルネス系食品スーパー」3つの共通項` | `supermarket` | 米国企業の紹介記事 |

うち `ワタミ` / `薬王堂HD` / `J.フロント` の 3 件は**ガード導入前は「抽出成功」に数えられており、個社の決算値が業態の観測値として `observations.json` に入る状態**だった。しかも `source_authority` が個社側の既定値になるため、5 項 natural key では別レコードとして「正しく」共存してしまい、衝突検出にも掛からない。§4.3.2 の金額バグと同じ **silent accumulation** の類型である。

`3月消費支出…外食マイナス―総務省` は総務省の家計調査であり、日本フードサービス協会の外食統計ではない（小売ドメイン室の指摘）。ガード後は `no_segment_match`（＝カタログに業態行を追加すべき候補）に落ち、取りこぼしとして可視化される。

**なぜ「先頭アンカー限定」だけでは駄目か**: 経産省の商業動態統計 4 件（`経済産業省／2月の商業動態統計、小売業販売額は0.2％減の12兆1550億円` 等）は主語が発表主体名であり、観測対象の業態名は本文側にある。単純に先頭限定にするとこの 4 件を落とす。段階 2 の例外はこのために置いている。

**実測されたカバー率とその含意**: 一意 URL 406 件 [代表]（計測日 2026-07-26）のうち、上記ガード適用後にカタログの業態別名で解決できるのは **77 件（19.0%）** である。残りの大半は、カタログに `種別=company` の行が 1 つも無いために業態が解決できない個社記事（`カスミ／…` `サミット／…` `しまむら 決算／…` `平和堂 決算／…`）と、統計記事ではない一般記事（`コメの民間在庫1.5倍に` `NRF forecasts 4.4% retail sales growth`）である。

これらは決定論パースの精度不足ではなく **本システムの対象範囲外の記事**であるため、`§4.3.7` の規則で `out_of_scope` に分類し NFR-05 の分母から除外する（要件 v0.1.1 の 7-15）。NFR-04（主要 4 業態の月次既存店指標で 90% 以上）は、実測で **主要 4 業態 × 既存店 × 数値の 12 件が 12 件とも抽出可能（100%）** であり達成できる見込みが立っている。

#### 4.3.4 指標の解決（左窓の最長一致）

```python
METRIC_WINDOW_NEAR = 12     # 文字数。この範囲内なら追加ペナルティなし
METRIC_WINDOW_FAR  = 25     # この範囲まで許容し -0.10

def value_kind_of(token: ValueToken) -> str:
    """値トークンの型を返す。どの正規表現で一致したかだけで決まる（§4.3.2）。"""
    # VALUE_PCT_RE / WARI_RE / HANGEN_RE → ratio、VALUE_JPY_RE → absolute
    return "absolute" if token.matched_by is VALUE_JPY_RE else "ratio"

def resolve_metric(window: str, catalog: Catalog, value_kind: str
                   ) -> tuple[Metric | None, float, str]:
    """左窓から最長一致で指標を解決する。(metric, penalty, matched_alias) を返す。

    value_kind は当該値トークンの型（"ratio" / "absolute"）。V12 の緩和（§3.3）により
    1 つの別名が値種別の異なる複数指標に一致しうるため、候補を value_type で絞ってから
    最長一致を採る。値種別が同一の指標間では V12 が重複を禁じているので、
    絞り込み後の候補は必ず 0 個か 1 個になる。
    """
    for alias, metric_ids in catalog.metric_alias_index():   # 別名の長さ降順
        idx = window.rfind(alias)
        if idx < 0:
            continue
        cands = [m for m in map(catalog.metric, metric_ids)
                 if m.value_type == value_kind]
        if not cands:
            continue        # 値の型に合う指標が無い別名は「一致しなかった」として次へ進む
        assert len(cands) == 1, "V12 により値種別が同一の指標間で別名は重複しない"
        metric = cands[0]
        distance = len(window) - (idx + len(alias))
        if distance <= METRIC_WINDOW_NEAR:
            return metric, 0.00, alias
        if distance <= METRIC_WINDOW_FAR:
            return metric, 0.10, alias
    return None, 0.00, ""
```

長さ降順の索引で `rfind`（右端優先）を使うことで、`6月の総売上高233億円、既存店売上2.3%減` の 2 番目の値に対して `既存店売上` が `売上高` より先に一致する。

**値の型フィルタは正式な解決手段である**（Issue #729 で確定）。V12 の緩和により別名 `売上高` が `sales-amount-absolute`（absolute）と `all-store-sales-yoy`（ratio）の双方に一致しうるため、**どちらを採るかは値トークンの型で決まる**。カタログ §2.2 の「絶対額か率かでさらに分岐」を実装に落としたものであり、暫定回避ではない。

| 入力 | 値の型 | 解決先 |
|---|---|---|
| `日本百貨店協会／3月の売上高3.2％増` | ratio | `all-store-sales-yoy` |
| `ツルハHD／…連結決算売上高は1兆4505億円` | absolute | `sales-amount-absolute` |

**候補が 0 個のときは「一致しなかった」として次の別名へ進む**（その別名で確定させて `no_metric_match` にしない）。より短い別名が正しい型の指標を持つ可能性が残るためである。この分岐を落とすと、型の合わない長い別名が短い別名の一致を隠してしまう。

`assert` は防御的な自己検査であり、通常は V12 が保証する。カタログ側の V12 違反を `Catalog.validate()` が先に止めるため（FR-24）、パーサ実行時にこの assert が発火することはない。

#### 4.3.5 複数指標の分解（FR-11）

```
入力: 日本百貨店協会／6月の外国人売上29.8％増、客数0.5％減・客単価30.4％増
      掲載日 2026-07-25

  step 1  正規化
          日本百貨店協会/6月の外国人売上29.8%増、客数0.5%減・客単価30.4%増

  step 2  業態解決（先頭アンカー）
          "日本百貨店協会" → department-store  penalty 0.00

  step 3  期間解決（§4.4）
          "6月" → 2026-06 / month / lag=1  penalty 0.05

  step 4  値トークン列挙（VALUE_PCT_RE / VALUE_JPY_RE）
          [(29.8, 増)pos17] [(0.5, 減)pos26] [(30.4, 増)pos34]

  step 5  各値の左窓を切り出して指標を解決（値の型で候補を絞る。§4.3.4）
          値①  左窓 "6月の外国人売上"   → 外国人売上   → inbound-sales-yoy
          値②  左窓 "、客数"           → 客数         → customer-count-yoy
          値③  左窓 "・客単価"         → 客単価       → spend-per-customer-yoy

  step 5b 残余語ガード（後述）
          解決できた 3 値の左窓の残余はいずれも期間表現（6月）と助詞のみ → 通過

  step 6  スコープ解決（§3.3）
          "既存店" は本文に無い → 各指標の default_scope（3 指標とも 既存店 → existing_store）
          ※ カタログ §2.1 の既定スコープが「既存店」であり、§2.2 の
             「記事に既存店の文字列が無ければ既存店指標として扱わない」判定は
             existing-store-sales-yoy への昇格を禁じるものであって、
             既定スコープの適用そのものを禁じてはいない（§9.3 の D4 に整理。小売ドメイン室が
             カタログ §2.2 に適用順序を明記し確認済み）

  step 7  符号付与と Observation 生成
          +29.8 / -0.5 / +30.4  → 3 レコード
          natural key はいずれも異なる（metric_id が違う）→ 衝突なし

  step 8  付帯情報パス（streak / sign_only / 横ばい）
          該当なし
```

##### 残余語ガード（値の左窓の未解決語による除外）

**規則**: **指標別名・業態別名・期間表現のいずれにも該当しない残余語が値の左窓にある場合、その値は業態の観測値としない。**

これは §4.3.3 の主語位置ガードの**自然な拡張**である。主語位置ガードが「**主語の位置**」で個社を弾くのに対し、本ガードは「**値の直前の修飾語**」で弾く。両者は同じ危険（個社の値が業態の観測値になる silent accumulation）に対する、適用位置の異なる 2 つの防壁であり、片方だけでは塞げない。主語位置ガードは `ワタミ 決算／…国内外食好調` のように業態名が主語でないケースを止めるが、`ドラッグストア／2月既存店売上ツルハ4.0%増` は**業態名が主語なので発火しない**。

**なぜ必要か**（Issue #728）。改訂前の設計では、次の 1 行で 2 つの事故が同時に起きていた。

```
  ドラッグストア／2月既存店売上ツルハ4.0%増、コスモス薬品7.0%増
    値① 4.0%増  左窓「2月既存店売上ツルハ」→ 既存店売上 に一致 → 採用
    値② 7.0%増  左窓「、コスモス薬品」    → 指標別名なし   → 黙って破棄

  (1) 個社の値が業態の観測値になる
      4.0 はツルハ 1 社の実績だが (drugstore, existing-store-sales-yoy, …) として
      confidence 0.95 で格納される。カタログ §1.4 の「個社決算は out_of_scope 分類」に反する
  (2) もう一方の値が痕跡なく消える
      コスモス薬品の 7.0 は observation にも unresolved にも現れない（silent loss。FR-10 違反）
```

後述の衝突検出は observation が 1 件しか生成されない以上**発火しようがなく**、安全網として機能していなかった。実測 16 行が該当する（一意 URL 406 件 [代表] / 計測日 2026-07-26。Issue #728 の実装側報告）。

**該当 16 行は一律 `out_of_scope` にしてはならない。性質の異なる 2 種類が混在する。**

| 種類 | 例 | 1 件目の扱い |
|---|---|---|
| (a) 個社の並記 | `ドラッグストア／2月既存店売上ツルハ4.0%増、コスモス薬品7.0%増` | **対象外**。1 件目も業態の観測値ではない |
| (b) 業態内の内訳 | `家電大型専門店／4月の販売額は12.1％増、生活家電が15.8％増に（経産省調べ）` | **正当な観測値として採用** |

(b) はカタログ §1.1 が `electronics-retailer` の発表主体を「経済産業省（商業動態統計）」のみと定めている**業態統計そのもの**であり、`12.1` は経産省が発表する業態全体の販売額である。`out_of_scope` に落とすと**本来取るべきデータを捨てる**ことになる。

**判定基準** — 左窓に残る「未解決の残余語」の性質で分ける。

| 入力 | 1 件目の左窓 | 指標解決後の残余 | 判定 |
|---|---|---|---|
| `ドラッグストア／2月既存店売上ツルハ4.0%増` | `2月既存店売上ツルハ` | `2月`（期間）+ **`ツルハ`（不明語）** | (a) 個社 |
| `家電大型専門店／4月の販売額は12.1％増` | `4月の販売額は` | `4月`（期間）のみ | (b) 業態 |

```python
RESIDUE_MIN_LEN = 2          # 1 文字の残りは送り仮名・記号の取り残しとみなす

PERIOD_TOKEN_RE = re.compile(
    r"[0-9]{4}年|[0-9]{1,2}〜[0-9]{1,2}月|[0-9]{1,2}月(?:期|度)?|"
    r"上期|下期|通期|年度|第[1-4]四半期|前年同月|前年同期"
)
FUNCTION_TOKEN_RE = re.compile(r"[のはがをにでとやもへ約、。・／/:：（）()「」\s]+")

def residue_of(window: str, matched_alias: str, catalog: Catalog) -> str:
    """左窓から、解決に使われた語・業態別名・期間表現・助詞記号を差し引いた残り。"""
    s = window.replace(matched_alias, "") if matched_alias else window
    for alias, _ in catalog.segment_alias_index():      # 長さ降順
        s = s.replace(alias, "")
    s = PERIOD_TOKEN_RE.sub("", s)
    s = FUNCTION_TOKEN_RE.sub("", s)
    return s

def residue_guard_trips(resolved: list[ResolvedValue], catalog: Catalog) -> bool:
    """解決できた値のいずれかに 2 文字以上の未解決残余語が残れば True（＝行全体を対象外）。"""
    return any(len(residue_of(v.window, v.matched_alias, catalog)) >= RESIDUE_MIN_LEN
               for v in resolved)
```

**行の分類は「解決できた値」の残余だけで決まる。** 解決できなかった値トークンの残余（`、コスモス薬品` / `、生活家電が`）は分類に使わない。使うと (b) が (a) に巻き込まれるためである。

**処理の帰結**:

| 条件 | 解決できた値（1 件目） | 解決できなかった値トークン |
|---|---|---|
| (a) 解決できた値の残余に不明語あり | 行全体を対象外（`reason_code = company_disclosure`） | 同左（**行単位**で落ちる） |
| (b) 残余が期間表現のみ | observation として採用 | **`unresolved` に退避**（`reason_code = no_metric_match_in_multi_value`） |

**(b) でも 2 件目を捨てない。** `生活家電 15.8` は `unresolved` に残し、SC-06 のデータ品質パネル（P2）に表示する。**将来カタログに内訳カテゴリの指標が追加されれば回収できる形**で保持するのが目的であり、`no_metric_match` と別コードにするのはこの回収可能性を分布から読み取れるようにするためである。

**(a) の行も破棄しない**。`company_disclosure` として `unresolved.json` に原文ごと保持する。対象外は「捨てる」ことではなく「分母から外して可視化する」ことである（FR-10 / NFR-10 / D3）。

**判定できないケースは保守的に対象外とする。** 残余語が個社名なのか内訳カテゴリなのかを機械的に区別する手段は現時点で存在しない（カタログに `種別=company` の行が 0 件のため、**個社名の辞書が無い**）。区別できないケースは必ず残るので、その場合は `company_disclosure` に倒す。誤って業態値に混入させるより、落として SC-06 で件数を追える方が安全である。カタログに個社行または内訳カテゴリ指標が追加されれば、判定は自動的に改善する（パーサのコード変更は不要。NFR-09）。

**既知の副作用**: `経済産業省／…小売業販売額は0.2％減の12兆1550億円` のように**同一量を率と金額で言い換えた**行では、2 つ目の値トークンの左窓が `の` だけになり指標が解決できないため、`no_metric_match_in_multi_value` として退避される（§9.4 U10 の実測では 13 件）。実害はない（silent loss ではなく可視化された退避である）が、P2 に定常的に並ぶことになる。「同一量の言い換え」を検出して退避対象から外す規則は M3 の `measure` で件数を確認してから検討する。

##### intra-title の natural key 衝突検出

分解結果に同一 natural key が 2 つ以上現れた場合、1 つの観測に複数の値が対応していることになり、片方が他方を上書きしてしまう。

```python
def detect_collision(obs: list[Observation]) -> bool:
    keys = [o.natural_key() for o in obs]
    return len(keys) != len(set(keys))
```

衝突を検出したら、その記事から生成した**全 observation の confidence を 0.30 に固定**する。閾値 0.70 未満のため FR-07 により LLM フォールバックへ回る。LLM も解決できなければ `unresolved`（`reason_code = low_confidence`）に退避する。

**発火条件**（本改訂で書き直した）。この検出は**残余語ガードを通過した行にのみ適用する**。ガードが (a) を先に落とすため、**現行カタログでは発火する経路がほぼ無い**。

| かつて想定していた発火例 | 改訂後の実際の経路 |
|---|---|
| `ファミレス／6月既存店すかいらーく1.7％増、サイゼリヤ9.7％増` | **発火しない**。値① の残余に `すかいらーく` が残るため、残余語ガードが行全体を `company_disclosure` に落とす。そもそも 2 件目は §4.3.1 の左窓規則では指標が解決せず、observation は 1 件しか生成されないので衝突自体が起きなかった（Issue #728 の C-3a） |
| `家電大型専門店／…12.1％増、生活家電が15.8％増` | **現時点では発火しない**。2 件目は指標が解決せず `no_metric_match_in_multi_value` に退避される |

**発火しうるのは次の場合である**: カタログに内訳カテゴリの指標（例: 家電の `生活家電販売額`）が追加され、**同一業態・同一指標・同一期間・同一発表主体**の値が 1 タイトルに複数現れるようになったとき。すなわち上表 (b) の系統でカタログが充実した後に起こりうる。

**削除せず残す理由**: カタログ改訂だけで発火条件が成立しうる以上（NFR-09 のとおりカタログ追記にコード変更は伴わない）、検出を外すと**その時点で silent な上書きが復活する**。発火頻度が 0 であることは、安全網を撤去してよい根拠にならない。`measure` に発火件数を出力し、0 が維持されていることを継続的に確認する。

**付帯情報の付与規則**:

| 表現 | 処理 |
|---|---|
| `51カ月ぶりに前年割れ` | 同一記事の observation のうち、`value < 0` かつ `metric.value_type == "ratio"` のものに `streak_broken_months = 51` を付与する。該当が複数あれば `display_order` が最小の業態、次に指標のカタログ記載順が先のものに付与する（決定論的なタイブレーク）。該当が 0 件なら付与せず、`unresolved` にも落とさない |
| `増収増益` / `減収減益` | `operating-revenue-yoy` と `operating-profit-yoy` の 2 レコードを `value = None` / `sign_only = "+"` or `"-"` / `needs_source_check = True` で生成する。confidence -0.40 |
| `横ばい` | 直近の指標に `value = 0.0` / `needs_source_check = True` を付与。confidence -0.35 |
| `3割増` | `value = +30.0`（割 = 10%）。confidence -0.10 |
| `半減` | `value = -50.0`。confidence -0.10 |
| `2カ月連続でプラス` / `5カ月ぶりプラス` | **v0.1 では扱わない**。カタログ §4.1 が定義するのは `〜カ月ぶりの前年割れ` のみである。「ぶり」表現は 11 件 [行] / 10 件 [一意]、うち `〜カ月ぶりに前年割れ` の形は 3 件 [行] / 2 件 [一意] にとどまり、残りは `5カ月ぶりプラス` `8カ月ぶり伸び拡大` `2カ月連続でプラス` など方向が逆または別事象である。誤った意味付けをするより扱わない方が安全と判断した（§9.4 の U6） |

#### 4.3.6 発表主体の解決（`source_authority`）

要件 v0.1.1 で natural key に加わった 5 つ目の要素。**同一の業態・指標・期間であっても、発表主体が異なれば母集団の異なる別の量**である。これを 1 つのキーに畳むと、協会統計と政府統計が相互に上書きし合い、可視化の前段で誤データが混入する。

##### ドメイン側からの裏付け（カタログ §1.4）

本設計の指摘を受けて小売ドメイン室が再検討し、カタログに §1.4「同一業態に複数の発表主体が存在するケース」が新設された。**実データで多発表主体が発生する業態が名指しで列挙されており**、これが `source_authority` を natural key に含める設計の直接の根拠となる。

| segment_id | 発表主体 A | 発表主体 B | カタログ §1.4 の指示 |
|---|---|---|---|
| `home-center` | 業界紙（DCS）集計 | 経済産業省（商業動態統計） | 「対象企業母集団が異なるため数値は一致しない。**両方とも `entity_type=association` の正当な観測として `発表主体` 違いで別系列に保持する**」 |
| `drugstore` | 経済産業省（商業動態統計） | 個社開示（コスモス薬品 / ツルハ 等） | 「当面は経産省ソースのみを `drugstore` segment の観測として扱い、**個社決算は `out_of_scope` 分類とする**」（§4.3.7 の判定木と一致） |

`home-center` は「重複でも取りこぼしでもなく、母集団の異なる別系列として両方を保持すべきもの」とカタログが明記している。v0.1 の 4 項キーではこの 2 系列が同一キーに落ち、`_wins()` によって毎回どちらかが消えていた。カタログ §1.1 の `home-center` 行にも「経産省『商業動態統計』のホームセンター区分とは集計主体・対象企業が異なり数値は一致しない」と既述されている。

##### 記事の掲載媒体と発表主体は別物

混同しやすいため、格納先を明確に分ける。

| 概念 | 例 | 格納先 |
|---|---|---|
| 掲載媒体（記事を配信したメディア） | 流通ニュース / DCS / ネッ担 | `source_articles.source_name` |
| **発表主体**（統計を公表した組織） | 日本チェーンストア協会 / 経済産業省 / 総務省 | `observations.source_authority` |

`ショッピングセンター／6月既存店売上1.6％減`（流通ニュース）の掲載媒体は流通ニュースだが、発表主体は日本ショッピングセンター協会である。natural key に入るのは後者のみ。

##### 2 段階の解決

```python
# 段階 1: カタログ由来の既定値（segments.source_authority）
#         カタログ §1.1「発表主体」列の先頭トークンを IF-02 発表主体対応表で変換
# 段階 2: 記事側に発表主体の明示があれば上書き

AUTHORITY_DETECTION: tuple[tuple[str, str], ...] = (
    # (検出語, source_authority) — 長い語を先に評価する
    ("経済産業省",           "meti"),
    ("商業動態統計",         "meti"),
    ("経産省調べ",           "meti"),
    ("経産省",               "meti"),
    ("総務省",               "mic"),
    ("日本ショッピングセンター協会", "sc-association"),
    ("日本百貨店協会",       "department-store-association"),
    ("日本チェーンストア協会", "chain-store-association"),
    ("日本フードサービス協会", "food-service-association"),
    ("日本生活協同組合連合会", "co-op-union"),
    ("日本生協連",           "co-op-union"),
)

def resolve_authority(norm_title: str, norm_summary: str, segment: Segment
                      ) -> tuple[str, float]:
    """(source_authority, confidence ペナルティ) を返す。"""
    haystack = norm_title + "\x1f" + norm_summary
    for word, code in AUTHORITY_DETECTION:
        if word in haystack:
            return code, 0.00          # 記事に明示あり。最も確実
    return segment.source_authority, 0.00   # カタログ既定値。定義上の既定なので減点しない
```

検出語のテーブルは **IF-02 の発表主体対応表**（要件 v0.1.1）に定義されたものをコードに写す。カタログ本体には検出語の列が無いため、対応表の維持は要件側の責務とする。これはカタログ改訂で発表主体が増えた際に IF-02 も更新する必要があることを意味するので、`Catalog.validate()` の V13 として「カタログの全 `発表主体` セル先頭トークンが対応表に存在すること」を検査し、漏れをエラー停止で検知する（FR-24）。

##### `meti-commerce-dynamics` は segment か authority か

**結論: segment として残し、authority とは独立に扱う。**

根拠は 2 点。第 1 に、カタログ §1.1 の `meti-commerce-dynamics` は「商業動態統計（**小売業全体**）」という**集計範囲**を表す行であり、`経済産業省／5月の商業動態統計、小売業販売額5.3％増の13兆4470億円` の主語は「小売業全体」である。主語であるものは segment である。第 2 に、発表主体は「誰が出したか」という直交する軸であり、`百貨店（協会）` と `百貨店（経産省）` を区別するには segment とは別の次元が必要である。両者を 1 つの列に押し込むと、どちらか一方が表現できなくなる。

この整理はカタログ側でも同じ結論に至っており（カタログ §1.4）、経産省が業態別内訳を発表した場合は**各業態の segment に `source_authority = meti` として記録し、`meti-commerce-dynamics` には計上しない**。同じ数値が「小売業全体」と各業態の双方に載る二重計上を防ぐためである。

##### 解決例

| 記事タイトル | segment_id | source_authority | 決め手 |
|---|---|---|---|
| `日本百貨店協会／6月の売上高2.3％増…` | `department-store` | `department-store-association` | 記事に協会名が明示 |
| `百貨店／3月の販売額2.2％増の5547億円、既存店は3.4％増（経産省調べ）` | `department-store` | `meti` | 記事の `経産省調べ` で上書き |
| `経済産業省／5月の商業動態統計、小売業販売額5.3％増の13兆4470億円` | `meti-commerce-dynamics` | `meti` | 主語は「小売業全体」 |
| `家電大型専門店／5月の販売額は27.5％増、生活家電が41％増に` | `electronics-retailer` | `meti` | カタログ既定値（発表主体列 = 経済産業省） |
| `ホームセンター月次実績＝2026年6月度` | `home-center` | `trade-press` | カタログ既定値（発表主体列 = 業界紙） |
| `ホームセンター／3月の販売額は3.4％増2868億円、店舗数は0.7％増（経産省調べ）` | `home-center` | `meti` | 記事の `経産省調べ` で上書き。上 2 行と**別系列として共存**（カタログ §1.4） |

上から 1・2 行目は `(department-store, existing-store-sales-yoy, existing_store, 2026-03)` まで一致するが、`source_authority` が異なるため衝突しない。v0.1 の 4 項キーでは一方が他方を上書きしていた。

**CPI 記事はこの表に載せない**。`6月消費者物価、1.6％上昇＝伸び率3カ月ぶり拡大―総務省` は `総務省` が明示されているため `source_authority = mic` は決まるが、**現行カタログでは segment が解決しない**。`cpi` の別名は `消費者物価指数（CPI）` / `消費者物価指数` / `CPI` の 3 つで、記事表記の `消費者物価`（指数なし）が含まれないためである（実行確認済み。`resolve_segment` は `None` を返し §4.3.7 の判定木で `no_segment_match` に落ちる）。segment が決まらなければ発表主体の解決規則は働かないため、**解決例として扱うと実装者が誤ったテスト期待値を書く**。この記事は §4.3.7 の実測表・§9.3 D3・§9.4 U9 のいずれでも「解決しない側」の代表例として扱っている。カタログに別名 `消費者物価` を追加すれば segment は解決するようになるが、それだけでは NFR-05 の分子は増えない（U9 の到達可能性表を参照）。**別名追加はカタログの担当（小売ドメイン室）であり、本書からは U9 の未決事項として記録するに留める。**

#### 4.3.7 スコープ外の分類（`out_of_scope`）

要件 v0.1.1 の NFR-05 は分母を「発表主体が協会統計・マクロ統計である行」に限定する。分母から外す行を**明示的に分類**し、破棄も silent skip もしない（NFR-10）。

##### 判定木

上から評価し、最初に一致した分類を採る。**どの経路を通っても、値トークンは observation か `unresolved` のいずれかに必ず着地する**（FR-10。§1.2 の絶対条件）。

```
  業態が解決できた
    ├─ 値トークンがあり、左窓から指標も解決できた
    │   ├─ 解決できた値のいずれかの左窓に 2 文字以上の未解決残余語がある
    │   │     └─▶ company_disclosure（対象外。行全体。分母から除外・§4.3.5 の残余語ガード）
    │   └─ 解決できた値の残余は期間表現・助詞のみ
    │         ├─▶ 解決できた値: 対象内・抽出成功（NFR-05 の分子）
    │         └─▶ 解決できなかった値トークン: no_metric_match_in_multi_value
    │               （値単位で unresolved に退避。行は成功として数えるので分母に加算しない）
    ├─ 値トークンはあるが指標が 1 つも解決できない
    │     └─▶ no_metric_match（分母に残る失敗。カタログ別名の追加候補）
    └─ 値トークンも定性表現も無い
          └─▶ no_numeric（分母に残る失敗）

  業態が解決できなかった
    ├─ タイトルに AUTHORITY_MARKER を含む
    │     協会 | 連合会 | 組合 | 経済産業省 | 経産省 | 総務省 | 農水省 |
    │     農林水産省 | 財務省 | 厚労省 | 国交省 | 統計 | 白書
    │     └─▶ no_segment_match（真の取りこぼし。分母に残る）
    │           統計の発表主体を名乗っているのに業態が取れない
    │           ＝ カタログに業態行を追加すべき候補
    │
    ├─ 統計語彙 STAT_VOCAB を含み、かつ数値/定性表現がある
    │     既存店 | 売上高 | 売上 | 販売額 | 客数 | 客単価 | 営業利益 |
    │     営業収益 | 供給高 | 物価 | 市場規模 | 店舗数
    │     └─▶ out_of_scope（個社開示。分母から除外）
    │
    └─▶ out_of_scope（統計記事ではない。分母から除外）
```

`AUTHORITY_MARKER` を最初に評価する順序が要点である。この順序でないと、`4月都内物価、1.5%上昇＝5カ月連続伸び縮小―総務省` のような**カタログに業態行が不足しているケース**（全国 CPI は `cpi` にあるが都内 CPI は無い）が個社扱いで黙って除外され、カタログ改善の signal が消える。

##### `reason_code` の分類と NFR-05 分母への影響

要件 §4.2 の enum は本改訂で **9 値**になった（`company_disclosure` / `no_metric_match_in_multi_value` を追加）。分母への影響で 3 群に分かれる。

| 群 | `reason_code` | NFR-05 分母 | LLM | SC-06 |
|---|---|---|---|---|
| 失敗（要改善） | `no_metric_match` / `no_segment_match` / `no_numeric` / `ambiguous_period` / `low_confidence` / `llm_schema_error` | ○ 分母に残る | 回す | P2 |
| **対象外**（意図的除外） | `out_of_scope` / **`company_disclosure`** | × 除外 | **回さない** | P3 |
| **値単位の退避** | **`no_metric_match_in_multi_value`** | **加算しない**（行は成功として分子・分母に既に 1 回計上済み） | 回さない | P2 |

- `company_disclosure` は「業態は解決したが、値の左窓の残余語から個社（または区別不能な語）の値と判定した行」を表す。`out_of_scope`（業態そのものが解決しない行）とは**検出位置が異なる**ため別コードにする。両者を同じコードに畳むと、主語位置ガードと残余語ガードのどちらが効いたのかが `measure` の分布から読めなくなる
- `no_metric_match_in_multi_value` を分母に加算しないのは、NFR-05 の分母が**行単位**で定義されているためである（要件 NFR-05 / 7-15）。同じ行を成功として 1 回、値単位の退避としてもう 1 回数えると二重計上になる。件数は独立に `measure` と SC-06 P2 に出す
- `no_metric_match` と `no_metric_match_in_multi_value` を分けるのは回収経路が異なるためである。前者は**指標別名の追加**、後者は**内訳カテゴリ指標そのものの追加**で回収する

##### 実測結果（一意 URL 406 件 [代表] / 計測日 2026-07-26）

**この数値は L2 レビューでの再現失敗を受けて全面的に再測定したものである。** 初版の `75 / 90 = 83.3%` は、業態と数値の有無だけを見て**指標の解決可否を検査していなかった**ための過大計上であり、誤りだった。再現手順は付録 A のスクリプトを参照。

**確定値**（カタログへの指標別名追加を反映し、§4.3.3 の主語位置ガードを適用した後の実測）:

| 分類 | 件数 | 比率 | 分母 | 例 |
|---|---|---|---|---|
| 対象内・抽出成功 | **64** | 15.8% | ○ | `ショッピングセンター／6月既存店売上1.6％減` |
| `no_metric_match`（値はあるが指標未解決） | **3** | 0.7% | ○ | `3月の百貨店売上高、全社増収＝免税売り上げは5カ月ぶりプラス`、`食品スーパー決算ランキング2026` |
| `no_numeric` | **10** | 2.5% | ○ | `ホームセンター月次実績＝2026年6月度`、`コンビニエンスストア統計調査2月度` |
| `no_segment_match`（真の取りこぼし） | **6** | 1.5% | ○ | `4月都内物価、1.5%上昇―総務省`、`6月消費者物価、1.6％上昇―総務省`、`3月消費支出、2.9％減―総務省` |
| `out_of_scope`（個社開示） | 154 | 37.9% | × | `しまむら 決算／2月期増収増益`、`ワタミ 決算／3月期営業利益5.9％増` |
| `out_of_scope`（非統計記事） | 169 | 41.6% | × | `買い物は「コスパ」、家事は「タイパ」、休息は「メンパ」`、`NRF forecasts 4.4% retail sales growth` |

**NFR-05 の達成率**: 分母 83（= 64 + 3 + 10 + 6）、分子 64 → **77.1%**。**目標 80% を下回っており、NFR-05 は未達である。** §9.4 の U9 に確定として記録する。

**この表は §4.3.5 の残余語ガード（本改訂で追加）を反映していない。** ガードにより、上表で「対象内・抽出成功」に数えていた行のうち (a) 個社並記の系統が `company_disclosure` に移り、**分子と分母がともに減る**。移動件数は該当 16 行のうち (a) と判定される分（および残余語が区別不能で保守的に倒される分）であり、確定値は M3 の `measure` による再計測で確定させる。実装側の暫定実測は 56/83 = 67.5%（Issue #728 / #729 の報告時点。V12 緩和による +3 行の回収を含まない）。

**この減少は受け入れる。** 判断の記録は §9.3 の D5 を参照。既に未達である以上、正確性を犠牲にして数値を維持しても意味がない。**「正しく未達」であることの方が、「誤ったデータで達成に見える」ことより価値がある。** 減った分は SC-06 の P3 に `company_disclosure` として明示され、取りこぼしではなく意図的な除外であることが画面から判別できる。

**ここに至るまでの推移**（すべて付録 A のスクリプトで再現可能）:

| 段階 | 分子 / 分母 | 達成率 | 備考 |
|---|---|---|---|
| 初版の申告（誤り） | 75 / 90 | 83.3% | 指標の解決可否を検査していなかった過大計上 |
| 指標解決を含めた再測定 | 62 / 89 | 69.7% | L2 レビューでの指摘を受けた再集計 |
| + カタログ指標別名の追加（`外食売上` / `チェーンストア販売` / `ECプラットフォーム市場規模`） | 67 / 89 | 75.3% | 小売ドメイン室が実施。単純加算の見込み 68 に対し実測 67 |
| **+ §4.3.3 主語位置ガード（確定値）** | **64 / 83** | **77.1%** | 誤って成功に数えていた 3 件を除外し、分母からも 6 件が out_of_scope に移動 |

主語位置ガードは達成率を 75.3% → 77.1% に上げるが、これは**分子が正しくなった結果**であって改善施策ではない。ガード前の 67 件には個社の決算値を業態に誤帰属した 3 件が含まれていた。

##### 永続化と表示

| 項目 | 設計 |
|---|---|
| 永続化 | `unresolved.json` に `reason_code = "out_of_scope"`（業態未解決の対象外）または `"company_disclosure"`（残余語ガードで落ちた行）で格納する。要件 §4.2 の unresolved_rows スキーマ（`id` / `digest_date` / `raw_line` / `reason_code` / `last_attempted_at` の 5 列）を**そのまま使い、フィールドを追加しない**。値単位の退避（`no_metric_match_in_multi_value`）も同じ 5 列で表現し、`raw_line` には**行の原文**を入れる（値トークンだけを切り出して入れない。出典に戻れなくなるため） |
| 同一記事の重複行 | `(article_id, reason_code)` で 1 エントリに集約し、`digest_date` には初出日を入れる。**`no_metric_match_in_multi_value` は例外で `(article_id, reason_code, 値トークンの開始位置)` を集約キーとする**。1 行から複数の値が退避されうるため、`(article_id, reason_code)` で畳むと**2 件目以降の値が消えて FR-10 に反する**（集約は掲載日の重複を畳むための仕組みであって、値を畳むためのものではない）。`id` は同キーから決定論的に導出し、再実行でバイト一致させる（NFR-06）。**掲載回数を unresolved.json に持たせない**（`occurrences` 列を足さない）。回数が必要な場面では `articles.json` の `appeared_dates` の長さから導出する。配信用の `series.json` にのみ集計値として `occurrences` を載せる（§6.1）。永続層のスキーマを要件どおりに保ちつつ、画面に必要な情報は配信層で作る、という役割分担 |
| 下位分類（個社開示 / 非統計記事） | `out_of_scope` の下位分類は**永続化しない**。`report.py` と `html/build.py` が `raw_line` から同じ判定木で再計算し、`series.json` の `quality.out_of_scope_breakdown` に載せる。判定木は決定論的なので再計算しても結果が揺れない。**`company_disclosure` はこの再計算の対象外**で、reason_code として直接永続化される（残余語ガードは指標解決の途中結果に依存するため、`raw_line` からの再計算では復元できない） |
| SC-06 での表示 | 「未解決（要改善）」と「対象外（意図的除外）」を**別のパネルに分ける**。§6.4 参照 |
| LLM フォールバック | **対象外群（`out_of_scope` / `company_disclosure`）は LLM に回さない。** 対象範囲外と判定済みの行に LLM コストを払わない（NFR-11）。`company_disclosure` については、LLM が返すべき正解が「対象外」である以上、判定は決定論的に下せる。LLM 呼び出しは非決定性とコストを持ち込むだけで精度は上がらない。`no_metric_match_in_multi_value` も同様に回さない（回収経路はカタログへの内訳カテゴリ追加であり、LLM ではない） |
| 将来の `種別=company` 追加 | カタログに個社行が追加されれば、その記事は業態が解決できるようになり自動的に `out_of_scope` から外れる。パーサのコード変更は不要（NFR-09）。v0.1 では個社行を追加しない方針（カタログ §1.5）。追加時の `発表主体` は当該企業名そのもの（個社開示は発表主体＝観測対象企業と一致するため）であり、IF-02 発表主体対応表に企業名の kebab-case コードを足す運用になる |

`drugstore` はこの分類が実際に効く業態である。カタログ §1.4 が「当面は経産省ソースのみを `drugstore` segment の観測として扱い、**個社決算は `out_of_scope` 分類とする**」と明記しており、コスモス薬品・ツルハ等の個社決算記事は上の判定木で `out_of_scope`（個社開示）に落ちる。経産省の販売額・店舗数のみが `drugstore` segment の観測として残るため、`(drugstore, sales-amount-yoy, all_store, 2026-06, meti)` の系列が個社決算に汚染されない。

### 4.4 期間解決（FR-06）

#### 4.4.1 掲載日を基準にした年の推定

カタログ §4.3 の実測によれば、月次統計は「対象月の翌月 20 日前後」に発表され、ダイジェスト掲載も同時期に集中する（コンビニ・チェーンストア・百貨店・SC・ファミレスの 6 月分がいずれも 7 月 22〜25 日）。したがって、月だけが書かれた記事の年は次の規則で決まる。

```python
def recent_past_year(pub: datetime.date, month: int) -> int:
    """掲載日 pub 以前で直近の (年, month) の年を返す。"""
    return pub.year if month <= pub.month else pub.year - 1
```

この 1 行がカタログ §4.2 の 2 つの規則を同時に満たす。

- 掲載 2026-07-25 の `6月` → 6 ≤ 7 なので 2026 → `2026-06`（発表ラグ 1 カ月）
- 掲載 2026-01-20 の `12月` → 12 > 1 なので 2025 → `2025-12`（年またぎのロールバック）

「掲載月の前月」と直接書かない理由は、ダイジェストの再掲載や遅れて拾われた記事（`s041442` は 2026-04-15 から 04-23 まで 6 日間出現する）でラグが 1 カ月からずれるためである。ラグは信頼度の材料として使う。

```python
EXPECTED_LAG_MONTHS = {1, 2}      # カタログ §4.3 の実測レンジ

def lag_penalty(pub: datetime.date, period_start: datetime.date) -> float:
    lag = (pub.year * 12 + pub.month) - (period_start.year * 12 + period_start.month)
    if lag in EXPECTED_LAG_MONTHS:
        return 0.05
    return 0.25       # 想定外のラグ。誤解決の可能性があるため大きく減点する
```

#### 4.4.2 パターンと適用順序

**順序が意味を持つ**。`楽天の2026年1-3月期（1Q）…` を `P_FY_END` に先に当てると `3月期` に一致して FY2026-03 になり誤りとなるため、範囲パターンを先に評価する。

```python
ERA_BASE = {"令和": 2018, "平成": 1988}    # 令和8年 = 2026年

# 適用順（上から評価し、最初に一致したものを採用）
P_FY_YEAR = re.compile(r"(?:(?P<y4>[0-9]{4})|(?P<y2>[0-9]{2}))年度")
P_HALF    = re.compile(r"(?:(?P<y4>[0-9]{4})年)?(?P<h>上|下)半期")
P_RANGE   = re.compile(r"(?<![0-9])(?P<m1>1[0-2]|[1-9])\s*[~-]\s*(?P<m2>1[0-2]|[1-9])月(?P<ki>期)?")
P_FY_END  = re.compile(r"(?:(?P<y4>[0-9]{4})|(?P<y2>[0-9]{2}))?年?(?P<m>1[0-2]|[1-9])月期")
P_YM      = re.compile(r"(?:(?P<era>令和|平成)(?P<ey>[0-9]{1,2})|(?P<y4>[0-9]{4})|(?P<y2>[0-9]{2}))年(?P<m>1[0-2]|[1-9])月(?P<do>度)?")
P_MONTH   = re.compile(r"(?<![0-9年~-])(?P<m>1[0-2]|[1-9])月(?![期度~\-0-9])")
```

| # | パターン | period_type | period_key | period_start / end | 実データでの一致例 |
|---|---|---|---|---|---|
| 1 | `P_FY_YEAR` | `fiscal_year` | `FY2025` | 2025-04-01 / 2026-03-31 | `ECプラットフォーム市場規模（2025年度）は前年度比5.8%増` |
| 2 | `P_HALF` | `half` | `2026-H1` | 2026-01-01 / 2026-06-30 | `貿易赤字、1兆円に半減…―2026年上半期` |
| 3 | `P_RANGE` | span により決定（下表） | `2026-03~2026-05` | 各月初 / 終端月末 | `DCM 決算／3〜5月営業利益17.4%増` |
| 4 | `P_FY_END` | `fiscal_year` | `FY2026-02` | 2025-03-01 / 2026-02-28 | `イオン 決算／2月期増収増益` |
| 5 | `P_YM` | `month` | `2026-02` | 2026-02-01 / 2026-02-28 | `令和8年2月度チェーンストア販売統計`, `ホームセンター月次実績＝2026年6月度` |
| 6 | `P_MONTH` | `month` | `2026-06` | 2026-06-01 / 2026-06-30 | `ショッピングセンター／6月既存店売上1.6％減` |

範囲（`P_RANGE`）の span から period_type を決める規則。span は `(m2 - m1) mod 12 + 1`（年またぎに対応）。

| span | period_type | 実測件数 [代表] | 例 |
|---|---|---|---|
| 3 | `quarter` | 23 | `1〜3月期`, `3〜5月` |
| 6 | `half` | 7 | `9〜2月`（2 月決算企業の上期） |
| 12 | `year` | 0 | — |
| その他（4 / 9） | **解決しない** → `ambiguous_period` | 11（span=9 が 9 件、span=4 が 2 件） | `6〜2月`（3Q 累計）, `2〜5月` |

合計 41 件 [代表]。§4.2 の「月範囲表現 41 件 [代表]」と一致する。

**この分布は `normalize()` を先に通すことが前提**である。NFKC と波ダッシュ統一だけを適用すると、`ビックカメラ 決算／9〜2 月増収増益`（数値と `月` の間に空白）が `P_RANGE` に一致せず、span=6 が 6 件・合計 40 件になる。§4.2 の `_SP_BEFORE_UNIT_RE` による空白除去が効いて初めて 7 件・41 件になる。正規化を挟まない再集計とは 1 件ずれるため、検算には付録 A のスクリプト（`normalize()` を通す）を使うこと。`ambiguous_period` の 11 件は基準によらず不変。

span 9 は 2 月決算企業の第 3 四半期累計であり、意味としては明確だが要件 §4.2 の period_type enum（month / quarter / half / fiscal_year / year）に該当する値が無い。enum を勝手に増やさず `ambiguous_period` として `unresolved` に退避し、§9.4 の U2 に enum 拡張案を記録する。損失は一意 URL 406 件中 11 件（2.7%）。

2 桁年表記（`26年2月期` / `29年2月期`）は 2000 年代として補完する（カタログ §4.2）。`29年2月期` は将来の計画値だが、明示された年を優先するため `FY2029-02` になる。

`P_FY_END` の period_start は「決算期末月の翌月の 1 年前」であり、`2月期` → 2025-03-01 〜 2026-02-28 となる。12 月決算の場合のみ翌月が翌年 1 月になるため、月の繰り上げは `mo % 12 + 1` で行う。

**検証結果**（実データ 16 件でプロトタイプ実行済み）:

| 掲載日 | タイトル（抜粋） | 解決結果 |
|---|---|---|
| 2026-07-25 | `ショッピングセンター／6月既存店売上1.6％減…` | `2026-06` / month |
| 2026-04-11 | `イオン 決算／2 月期増収増益…` | `FY2026-02` / fiscal_year / 2025-03-01〜2026-02-28 |
| 2026-04-15 | `オークワ／26年2月期は増収増益…` | `FY2026-02` / fiscal_year |
| 2026-04-20 | `DCM／29年2月期売上高6500億円…` | `FY2029-02` / fiscal_year |
| 2026-06-27 | `DCM 決算／3〜5月営業利益17.4%増…` | `2026-03~2026-05` / quarter |
| 2026-04-15 | `サイゼリヤ 決算／9〜2月増収増益…` | `2025-09~2026-02` / half |
| 2026-04-15 | `クスリのアオキHD 決算／6〜2月増収増益…` | span=9 → `ambiguous_period` |
| 2026-07-25 | `ECプラットフォーム市場規模（2025年度）…` | `FY2025` / fiscal_year |
| 2026-04-01 | `令和8年2月度チェーンストア販売統計` | `2026-02` / month（元号解決） |
| 2026-01-20 | `12月既存店1.0%減`（年またぎ検証） | `2025-12` / month |

### 4.5 confidence の算出

初期値 1.00 から減点する加算モデル。閾値 **0.70**（要件 FR-07）以上を「確定」とする。

| カテゴリ | 条件 | 減点 |
|---|---|---|
| 業態 | 先頭アンカー（`/` の左）で別名一致 | 0.00 |
| | タイトル中のどこかで別名一致 | 0.05 |
| | 別名一致なし | **解決不能** → `no_segment_match` または `out_of_scope`（§4.3.7 の判定木） |
| 発表主体 | 記事に発表主体の明示あり（`経産省調べ` 等） | 0.00 |
| | カタログ既定値を採用 | 0.00（定義上の既定であり推測ではないため減点しない） |
| 指標 | 左窓の 12 文字以内で別名一致 | 0.00 |
| | 左窓の 13〜25 文字で別名一致 | 0.10 |
| | 別名一致なし | **解決不能** → `no_metric_match` |
| 期間 | `P_YM` / `P_FY_YEAR` / `P_HALF`（年が明示） | 0.00 |
| | `P_MONTH` / `P_FY_END`（年を推定）でラグが 1〜2 カ月 | 0.05 |
| | 同上でラグが範囲外 | 0.25 |
| | `P_RANGE` の span ∈ {3, 6, 12} | 0.05 |
| | パターン不一致 / span 範囲外 | **解決不能** → `ambiguous_period` |
| 値 | `N%増` / `N%減` | 0.00 |
| | `N%上昇` / `N%下落`（方向語が売上以外の語彙） | 0.05 |
| | 金額（`N億円`） | 0.05 |
| | `N割増` / `半減` | 0.10 |
| | `横ばい` | 0.35（+ `needs_source_check = True`） |
| | 定性表現のみ（`増収増益` 等、`sign_only`） | 0.40（+ `needs_source_check = True`） |
| | 数値・定性表現のいずれも無い | **解決不能** → `no_numeric` |
| 残余語 | 解決できた値の左窓に 2 文字以上の未解決残余語がある | **解決不能** → 行全体を `company_disclosure`（§4.3.5 の残余語ガード）。confidence は算出しない |
| 衝突 | 残余語ガード通過後に intra-title で natural key が衝突 | confidence を **0.30 に固定**（減点ではなく上書き） |

**衝突行の位置づけ**（本改訂で変更）。残余語ガードが個社並記を先に落とすため、**現行カタログでは衝突が発火する経路がほぼ無い**（§4.3.5 の「発火条件」参照）。この行は、カタログに内訳カテゴリ指標が追加された後に発火しうる**将来のための安全網**として残しているものであり、v0.1 の実データで 0.30 が観測されることは想定していない。`measure` で発火件数が 0 であることを継続確認する。

代表例の算出結果:

| タイトル | 内訳 | confidence | 判定 |
|---|---|---|---|
| `ショッピングセンター／6月既存店売上1.6％減` | 業態 0.00 + 指標 0.00 + 期間 0.05 + 値 0.00 | **0.95** | 確定 |
| `日本百貨店協会／6月の外国人売上29.8％増、客数0.5％減・客単価30.4％増` | 3 レコードとも同上 | **0.95** | 確定 |
| `カスミ／6月の総売上高233億円、既存店売上2.3％減` | 業態が解決不能・統計語彙あり・数値あり | — | `out_of_scope`（個社開示） |
| `百貨店／3月の販売額2.2％増の5547億円、既存店は3.4％増（経産省調べ）` | 業態 0.00 + 発表主体 0.00 + 指標 0.00 + 期間 0.05 + 値 0.00 / 0.05 | **0.90〜0.95** | 確定（`source_authority = meti` で協会統計と共存） |
| `ファミレス／6月既存店すかいらーく1.7％増、サイゼリヤ9.7％増` | 値① の左窓 `6月既存店` の残余に `すかいらーく` が残る | — | `company_disclosure`（対象外・分母から除外。§4.3.5） |
| `家電大型専門店／4月の販売額は12.1％増、生活家電が15.8％増に（経産省調べ）` | 値① 業態 0.00 + 発表主体 0.00 + 指標 0.00 + 期間 0.05 + 値 0.00。残余は `4月` のみ | **0.95** | 確定。値② `15.8` は `no_metric_match_in_multi_value` で退避 |
| `日本百貨店協会／3月の売上高3.2％増` | 業態 0.00 + 指標 0.00（値の型 ratio で `all-store-sales-yoy` に確定・§4.3.4）+ 期間 0.05 + 値 0.00 | **0.95** | 確定（V12 緩和により解決。改訂前は `no_metric_match`） |
| `ホームセンター月次実績＝2026年6月度` | 業態は解決・数値なし | — | `no_numeric`（分母に残る） |
| `イオン 決算／2月期増収増益` | 業態が解決不能（`イオン` はカタログ未定義） | — | `out_of_scope`（個社開示） |
| `4月都内物価、1.5%上昇＝5カ月連続伸び縮小―総務省` | 業態が解決不能だが `総務省` を含む | — | `no_segment_match`（真の取りこぼし・分母に残る） |

`no_*` は減点ではなく即座に解決不能とし、`unresolved` へ落とすか LLM へ回す。「業態が取れないが指標だけ取れた」といった部分成果を confidence 0.4 で通すことはしない。natural key を構成できない以上、格納先が決まらないためである。

### 4.6 LLM フォールバック（FR-07 / IF-03）

#### 4.6.1 呼び出しインターフェース

```python
# llm.py
from typing import Protocol

class LlmClient(Protocol):
    def extract(self, prompt: str) -> str: ...

class NullClient:
    """--no-llm 用。常に空応答を返す。
    キャッシュ層より下に位置するため、キャッシュヒットした行はここに来ない
    （§2.5 の --no-llm 定義 (A)）。ミスした行のみ unresolved に落ちる。"""
    def extract(self, prompt: str) -> str:
        return "[]"

class ClaudeCliClient:
    """claude CLI の headless モードを subprocess で呼ぶ。
    stderr は握り潰さずそのまま伝播する（NFR-10）。"""
    def __init__(self, model: str = "claude-sonnet-5", timeout_s: int = 120): ...
    def extract(self, prompt: str) -> str: ...
```

要件 7-10（LLM 実行主体）が未決のため、v0.1 は `ClaudeCliClient` によるローカル実行 + キャッシュ commit を既定とし、日次自動実行は `--no-llm`（新規の LLM 呼び出しなし。commit 済みキャッシュのヒットは使う。§2.5 の定義 (A)）とする。この分離により、実行主体の決定が `cli.py` のクライアント選択 1 箇所に閉じる。

#### 4.6.2 プロンプト設計

入力は**未解決の 1 記事**（複数行を束ねない。1 記事 = 1 キャッシュエントリのため）。

**対象外群（`out_of_scope` / `company_disclosure`）と値単位の退避（`no_metric_match_in_multi_value`）は LLM に渡さない**（§4.3.7）。したがって `ファミレス／6月既存店すかいらーく1.7％増、サイゼリヤ9.7％増` のような個社並記の記事はここに到達しない。到達するのは `low_confidence`（横ばい・定性表現・期間ラグ範囲外など）と `ambiguous_period` の記事である。下記の入力例は **`横ばい` による低 confidence を想定した例示**であり、実データから採った行ではない。

```
あなたは日本の小売業界の月次統計記事から構造化データを抽出する専門家です。
以下の記事タイトルから観測値を抽出し、JSON 配列のみを出力してください。
説明文・前置き・コードフェンスを付けないでください。

## 入力
掲載日: 2026-07-25
記事タイトル: コンビニエンスストア／6月既存店売上は横ばい、客数は0.5％減
記事URL: https://www.ryutsuu.biz/sales/sXXXXXX.html
記事要約: 6月の既存店売上は前年並み、客数は0.5%減だった。

## 使用可能な segment_id（これ以外を出力しないこと）
shopping-center: ショッピングセンター（別名: ショッピングセンター）
department-store: 百貨店（別名: 百貨店, 日本百貨店協会）
...（カタログから動的生成。全 13 件）

## 使用可能な metric_id（これ以外を出力しないこと）
existing-store-sales-yoy: 既存店売上高前年比（単位 percent_yoy / 既定スコープ existing_store）
...（カタログから動的生成。全 14 件）

## 抽出ルール
- 記事タイトルに明示されていない値を推測しないこと
- 一覧に無い業態（個社名など）が主語の値は抽出しないこと（空配列でよい）
- **値の直前に一覧に無い語（個社名・商品カテゴリなど）が付いている値は抽出しないこと。**
  その値は業態全体の実績ではなく、その語の実績である（例:「既存店売上ツルハ4.0%増」の
  4.0 はツルハ 1 社の値であり、ドラッグストア業態の値ではない）
- 「既存店」の文字列が無い限り scope に existing_store を使わないこと
- 増は正、減は負の符号を付けること
- 数値化できない定性表現は value を null とし sign_only に "+" / "-" を入れること
- period_key は month なら "YYYY-MM"、quarter/half なら "YYYY-MM~YYYY-MM"、
  会計年度なら "FYYYYY"、決算期なら "FYYYYY-MM" の形式にすること
- 掲載日より後の期間を対象にしないこと（将来計画値は抽出しない）

## 出力スキーマ
[
  {
    "segment_id": "string",
    "metric_id": "string",
    "scope": "existing_store|all_store|total_supply|n_a",
    "period_key": "string",
    "period_type": "month|quarter|half|fiscal_year|year",
    "value": number | null,
    "sign_only": "+" | "-" | null,
    "streak_broken_months": number | null,
    "needs_source_check": boolean,
    "raw_expression": "string",
    "confidence": number
  }
]
抽出できるものが無い場合は [] を出力してください。
```

「一覧に無い業態が主語の値は抽出しないこと」を明示するのは、上の例で LLM が `family-restaurant` に 2 件とも寄せて natural key を衝突させることを防ぐためである。この記事は正しくは空配列（個社が主語）を返すべきであり、結果として `unresolved` に落ちる。

#### 4.6.3 出力スキーマ検証とリトライ

```python
def validate_llm_output(raw: str, catalog: Catalog, pub: datetime.date
                        ) -> tuple[list[dict], list[str]]:
    """(検証済みレコード, エラーメッセージ) を返す。"""
    errors: list[str] = []
    text = _strip_code_fence(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [], [f"JSON としてパースできません: {e}"]
    if not isinstance(data, list):
        return [], ["トップレベルが配列ではありません"]
    ok = []
    for i, rec in enumerate(data):
        errs = _validate_record(rec, catalog, pub, index=i)   # 型・enum・ID 存在・期間形式・符号
        if errs:
            errors.extend(errs)
        else:
            ok.append(rec)
    return ok, errors
```

検証項目: (a) キーの過不足、(b) `segment_id` / `metric_id` がカタログに存在する（FR-24）、(c) `scope` / `period_type` が enum に含まれる、(d) `period_key` が period_type に対応する形式、(e) `period_end` が掲載日を超えない、(f) `value` が数値または null、(g) `value` と `sign_only` の両方が null でない、(h) `confidence` が 0.00〜1.00。

**リトライは 1 回のみ**（FR-07）。1 回目のプロンプト末尾に検証エラーを付けて再送し、それでも失敗すれば `unresolved`（`reason_code = llm_schema_error`）に退避する。リトライ結果も**成否によらずキャッシュに記録する**（空配列を返した記事を毎回再問い合わせしないため。NFR-11 のキャッシュヒット率 95% はこれで達成する）。

### 4.7 抽出キャッシュ（FR-08）

キャッシュに載るのは LLM に渡した記事のみである。対象外群（`out_of_scope` / `company_disclosure`）は LLM に渡さないためエントリを持たない（§4.3.7）。下記は §4.6.2 と同じ**例示のタイトル**であり、実データから採った行ではない。

```json
{
  "schema_version": 1,
  "entries": {
    "3f2a9c1b7e4d8a06": {
      "cache_key": "3f2a9c1b7e4d8a06",
      "article_id": "a1b2c3d4e5f60718",
      "url": "https://www.ryutsuu.biz/sales/sXXXXXX.html",
      "normalized_title": "コンビニエンスストア/6月既存店売上は横ばい、客数は0.5%減",
      "method": "llm",
      "model": "claude-sonnet-5",
      "extracted": [],
      "created_at": "2026-07-25"
    }
  }
}
```

| 項目 | 設計 |
|---|---|
| `cache_key` | `sha256(article_id + "\x1f" + normalized_title)` の先頭 16 桁。区切りに `\x1f`（ASCII Unit Separator）を使うのはリポジトリ規約に合わせたもので、ID 中に現れうる `-` との衝突を避ける |
| キャッシュ対象 | **LLM 抽出のみ**。決定論パースは高速かつ決定論的なので毎回再計算する。キャッシュしないことで、正規表現ルールを追加した際に即座に全件へ反映される（要件リスク 7-7 の改善サイクルを止めない） |
| どの variant のタイトルを使うか | 同一 URL に複数のタイトル variant があるため、**決定論的に 1 つを選ぶ**。選択関数は `max(variants, key=lambda t: (数値トークン数, len(t), t))`。ファイル走査順に依存しないため NFR-06 を満たす |
| 更新 | 追記のみ。既存エントリを書き換えない。`--invalidate-cache` 指定時のみファイル全体を破棄して作り直す |
| Git 管理 | 対象。差分レビュー可能にする（要件リスク 7-6） |

`s041442`（6 日掲載・4 variant）の場合、`カジュアル衣料4社／3月の既存店売上高はユニクロ9.2％増、しまむら8.5％増`（数値トークン 2、最長）が選ばれ、`カジュアル衣料4社／3月の既存店売上高はユニクロ9.2％増`（04-17 の短縮版）は選ばれない。要件 7-2 の「情報量の多い variant を優先する」を、順序に依存しない形で実装したものである。

---

## 5. データストア設計

### 5.1 ファイル構成

`.companies/{org}/docs/retail-stats/data/` 配下。RDB は使わない。

| ファイル | 対応エンティティ | 形状 | バイト一致保証（NFR-06） |
|---|---|---|---|
| `observations.json` | Observation | `{schema_version, observations: [...]}` | **あり** |
| `articles.json` | SourceArticle | `{schema_version, articles: [...]}` | **あり** |
| `extraction-cache.json` | ExtractionCache | `{schema_version, entries: {key: {...}}}` | **あり** |
| `unresolved.json` | UnresolvedRow | `{schema_version, rows: [...]}` | **あり** |
| `manifest.json` | DigestFile | `{schema_version, files: {path: {sha256, mtime_date, row_count}}}` | **あり** |
| `series.json` | 配信用の整形済み時系列（FR-13） | `{schema_version, meta, segments, metrics, series, quality}` | **あり** |
| `runs.json` | ExtractionRun | `{schema_version, runs: [...]}` | **なし**（実行時刻を含むため。直近 180 日で切り詰め） |

`runs.json` を保証対象から外すことを明示するのは、これを含めると「再実行で JSON がバイト一致」が原理的に成立しないためである。

**CI 実装への申し送り（重要）**: 冪等性を検証する CI ステップは、`DATA_DIR` 全体を `diff -rq` してはならない。`runs.json` は実行のたびに `run_id` と `started_at` / `finished_at` が変わるため、**run ログが 1 つでもある限り必ず不一致になり、冪等性チェックが常に fail する**。比較対象は次の 6 ファイル（`IDEMPOTENT_FILES`）に限定すること。除外リスト方式（`diff -rq --exclude=...`）ではなく **allowlist 方式**を採る。将来 `runs.json` 以外の非決定なファイルが増えたとき、除外リスト方式では silent に fail し始めるためである。ループ設計の `RS_REPRO_FILES` と CI/CD の比較対象も、この 6 ファイルに一致させること。

```bash
IDEMPOTENT_FILES="observations.json articles.json extraction-cache.json unresolved.json manifest.json series.json"
python3 -m retail_stats build --rebuild
( cd "$DATA_DIR" && sha256sum $IDEMPOTENT_FILES ) > /tmp/a.txt
python3 -m retail_stats build --rebuild
( cd "$DATA_DIR" && sha256sum $IDEMPOTENT_FILES ) > /tmp/b.txt
diff /tmp/a.txt /tmp/b.txt          # 差分があれば fail
```

実行メタデータのファイル名・形式は **`runs.json`（単一 JSON オブジェクト、`{schema_version, runs: [...]}`）を正**とする。JSON Lines 形式（`.jsonl`）や `extraction-runs.json` という名前は用いない。他文書がこれと異なる名前・形式を記載している場合は本書に合わせること。

### 5.2 論理スキーマの JSON 表現

要件 §4.2 の各テーブルを 1 レコード = 1 JSON オブジェクトに写す。FK は ID 文字列で表現し、参照整合性は `store.validate_integrity()` が保証する。

```json
{
  "schema_version": 1,
  "observations": [
    {
      "observation_id": "7c4e1a02b93f5d68",
      "segment_id": "shopping-center",
      "metric_id": "existing-store-sales-yoy",
      "scope": "existing_store",
      "source_authority": "sc-association",
      "period_key": "2026-06",
      "period_type": "month",
      "period_start": "2026-06-01",
      "period_end": "2026-06-30",
      "value": -1.6,
      "unit": "percent_yoy",
      "streak_broken_months": 51,
      "sign_only": null,
      "needs_source_check": false,
      "raw_expression": "6月既存店売上1.6％減",
      "article_id": "5d8b2f7a1c930e46",
      "extraction_method": "deterministic",
      "confidence": 0.95,
      "manual_override": false,
      "first_seen_date": "2026-07-25",
      "last_updated_date": "2026-07-25"
    }
  ]
}
```

```json
{
  "schema_version": 1,
  "articles": [
    {
      "article_id": "8f31c05ad7b2e94a",
      "url": "https://www.ryutsuu.biz/sales/s041442.html",
      "title_first_seen": "カジュアル衣料4社／3月の既存店売上高はユニクロ9.2％増、しまむら8.5％増",
      "title_variants": [
        "カジュアル衣料4社、3月の既存店売上高はユニクロ9.2%増、しまむら8.5%増",
        "カジュアル衣料4社／3月の既存店売上高はユニクロ9.2％増",
        "カジュアル衣料4社／3月の既存店売上高はユニクロ9.2％増、しまむら8.5％増",
        "カジュアル衣料4社／3月既存店 ユニクロ9.2%増、しまむら8.5%増"
      ],
      "source_name": "流通ニュース",
      "source_name_normalized": "流通ニュース",
      "first_published_date": "2026-04-15",
      "appeared_dates": ["2026-04-15", "2026-04-16", "2026-04-17",
                         "2026-04-18", "2026-04-22", "2026-04-23"]
    }
  ]
}
```

`article_id` = `sha256(url)` の先頭 16 桁。URL が一意キーであり、タイトルは一意キーにしない（要件 7-2）。`title_variants` は原文のまま保持し、**辞書順でソートして格納する**（走査順に依存させないため）。`source_name_normalized` は `{"ダイヤモンド・チェーンストア": "DCS", "DCS": "DCS", ...}` の対応表で吸収する。実データでは同一 URL が 2026-07-25 に `DCS`、2026-07-26 に `ダイヤモンド・チェーンストア` として出現しており、正規化しないと出典名が揺れる。

### 5.3 natural key による upsert

```python
NATURAL_KEY_FIELDS = ("segment_id", "metric_id", "scope", "period_key", "source_authority")

def natural_key(o: Observation) -> str:
    return "\x1f".join(getattr(o, f) for f in NATURAL_KEY_FIELDS)

def observation_id(o: Observation) -> str:
    return hashlib.sha256(natural_key(o).encode("utf-8")).hexdigest()[:16]

def upsert(index: dict[str, Observation], new: Observation) -> UpsertResult:
    key = natural_key(new)
    old = index.get(key)
    if old is None:
        index[key] = replace(new, observation_id=observation_id(new),
                             first_seen_date=new.first_seen_date,
                             last_updated_date=new.first_seen_date)
        return UpsertResult(action="created", key=key, before=None, after=index[key])

    # FR-23: 手動補正は自動 upsert で上書きしない
    if old.manual_override:
        return UpsertResult(action="skipped_manual", key=key, before=old, after=old)

    if _wins(new, old):
        merged = replace(new,
                         observation_id=old.observation_id,
                         first_seen_date=min(old.first_seen_date, new.first_seen_date),
                         last_updated_date=max(old.last_updated_date, new.first_seen_date))
        index[key] = merged
        return UpsertResult(action="updated", key=key, before=old, after=merged)

    # 負けた場合でも観測日レンジは伸ばす
    index[key] = replace(old, last_updated_date=max(old.last_updated_date, new.first_seen_date))
    return UpsertResult(action="unchanged", key=key, before=old, after=index[key])


def _wins(new: Observation, old: Observation) -> bool:
    """FR-09: confidence が高い方。同値なら掲載日が新しい方。それも同値なら既存を維持。"""
    if new.confidence != old.confidence:
        return new.confidence > old.confidence
    if new.first_seen_date != old.first_seen_date:
        return new.first_seen_date > old.first_seen_date
    return False
```

`_wins()` が最後に `False` を返す（既存を維持する）ことが重要である。完全同点で新側を採るとファイル走査順に依存し、NFR-06 が崩れる。

`action == "updated"` かつ `before.value != after.value` の場合は、差分レポートに「上書き」として値の前後を必ず出力する（要件リスク 7-8：速報→確報の改定や誤記訂正の検知）。

**発表主体が異なる観測は上書き対象にならない**。`source_authority` が natural key に含まれるため、`(department-store, existing-store-sales-yoy, existing_store, 2026-03, department-store-association)` と `(department-store, existing-store-sales-yoy, existing_store, 2026-03, meti)` は別キーとなり、`upsert()` は 2 レコードを共存させる。これが要件 7-14 に対する構造的な対処であり、`_wins()` の勝敗判定に発表主体を持ち込まない（どちらが「正しい」かを本システムは判定しない）。

一方、**`_wins()` による上書きは同一発表主体内でのみ起こる**ため、上書きが検出されたときは速報→確報の改定か記事の誤記訂正のいずれかに絞り込める。差分レポートの解釈が v0.1 の 4 項キー時代より明確になる。

### 5.4 冪等性の担保（NFR-06 のバイト一致）

再実行で JSON がバイト一致するために、以下 6 点を守る。1 つでも欠けると一致しない。

| # | 規則 | 理由 |
|---|---|---|
| 1 | **時刻を実行時に取得しない**。`first_seen_date` / `last_updated_date` / `created_at` は全て digest ファイル名の日付から導く | `datetime.now()` を 1 箇所でも使うと毎回差分が出る。`runs.json` のみ例外 |
| 2 | **書き出し前に全コレクションをソートする**。observations は `(segment_id, metric_id, scope, period_key, source_authority)`、articles は `article_id`、unresolved は `(article_id, reason_code, 値トークンの開始位置)`（値単位の退避が 1 行から複数出るため。§4.3.7）、cache は `cache_key` の昇順 | dict の挿入順やファイル走査順への依存を断つ |
| 3 | `json.dump(..., ensure_ascii=False, indent=2, sort_keys=True, separators=(",", ": "))` + 末尾に改行 1 個 | キー順とインデントを固定する。`ensure_ascii=False` は日本語を Git 差分で読めるようにするため |
| 4 | **float の丸めを書き出し時に行う**。`value` は `metric.precision` に従い `round(v, precision)` した結果を格納する | `-1.6000000000000001` のような表現差を防ぐ |
| 5 | **改行は LF 固定**（`newline="\n"` で open） | Windows / WSL 混在環境での差分を防ぐ |
| 6 | **アトミック書き込み**。`{path}.tmp` に書いてから `os.replace()` | 生成途中で失敗した場合に成果物を空で壊さない（NFR-12） |

冪等性の CI 検証（対象は §5.1 の `IDEMPOTENT_FILES` 6 ファイル。ここで独自の集合を定義しない）:

```bash
IDEMPOTENT_FILES="observations.json articles.json extraction-cache.json unresolved.json manifest.json series.json"
python3 -m retail_stats build --rebuild
( cd "$DATA_DIR" && sha256sum $IDEMPOTENT_FILES ) > /tmp/a.txt
python3 -m retail_stats build --rebuild
( cd "$DATA_DIR" && sha256sum $IDEMPOTENT_FILES ) > /tmp/b.txt
diff /tmp/a.txt /tmp/b.txt      # 差分があれば fail
```

### 5.5 参照整合性の検査

書き出し直前に `store.validate_integrity(catalog)` を実行し、違反があれば **書き出さずに exit 1**（FR-24 / NFR-12）。

| 検査 | 内容 |
|---|---|
| I1 | 全 observation の `segment_id` / `metric_id` がカタログに存在する |
| I2 | 全 observation の `article_id` が `articles.json` に存在する |
| I3 | `observation_id` が natural key のハッシュと一致する |
| I4 | natural key に重複が無い |
| I5 | `unit` が `catalog.metric(metric_id).unit` と一致する |
| I6 | `value` と `sign_only` の少なくとも一方が非 null |
| I7 | `period_start <= period_end`、かつ `period_key` が `period_type` の形式に適合する |
| I8 | `source_authority` が IF-02 発表主体対応表の値のいずれかである（自由記述の混入を防ぐ） |
| I9 | `unresolved_rows` の `reason_code` が enum の **9 値**（要件 §4.2）のいずれかである |
| I10 | **FR-10 の不変条件**: パーサは切り出した値トークンごとに `disposition` を記録する（`observation` = 採用 / `parked` = 値単位で `unresolved` に退避 / `row_dropped` = 行単位の `unresolved` エントリに含めて落とした）。**`disposition` が未設定の値トークンが 1 つでもあれば exit 1** で停止する。件数の等式ではなくトークン単位の帰属で検査するのは、`sign_only`（値トークンを持たない observation）や `横ばい`（既存 observation への付帯）が等式を成り立たなくするためである。§1.2 の絶対条件を機械的に担保する唯一の検査であり、`\|\| true` 等で握り潰さない（NFR-10） |

---

## 6. HTML 生成設計

### 6.1 配信 JSON（`series.json`）の形

HTML に埋め込む JSON は observations の生テーブルではなく、描画に必要な形へ整形したものとする（FR-13）。理由は、ブラウザ側でのグルーピング処理を無くして初期表示 1.5 秒（NFR-03）を確実にするため。

```json
{
  "schema_version": 1,
  "meta": {
    "generated_from_digest_max_date": "2026-07-26",
    "digest_files_scanned": 102,
    "digest_files_with_section": 93,
    "observation_count": 128,
    "unresolved_count": 357,
    "catalog_sha256": "…"
  },
  "segments": [
    {"segment_id": "shopping-center", "name": "ショッピングセンター",
     "entity_type": "association", "display_order": 10,
     "default_source_authority": "sc-association"}
  ],
  "authorities": [
    {"source_authority": "sc-association", "label": "日本ショッピングセンター協会",
     "kind": "association"},
    {"source_authority": "meti", "label": "経済産業省（商業動態統計）",
     "kind": "government"}
  ],
  "metrics": [
    {"metric_id": "existing-store-sales-yoy", "name": "既存店売上高前年比",
     "unit": "percent_yoy", "value_type": "ratio",
     "direction_hint": "higher_is_better", "precision": 1}
  ],
  "periods": {
    "month": ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
  },
  "series": [
    {
      "segment_id": "shopping-center",
      "metric_id": "existing-store-sales-yoy",
      "scope": "existing_store",
      "source_authority": "sc-association",
      "period_type": "month",
      "points": [
        {"period_key": "2026-05", "value": 9.9, "article_id": "…",
         "method": "deterministic", "raw": "5月既存店売上9.9％増",
         "streak_broken_months": null, "needs_source_check": false},
        {"period_key": "2026-06", "value": -1.6, "article_id": "…",
         "method": "deterministic", "raw": "6月既存店売上1.6％減",
         "streak_broken_months": 51, "needs_source_check": false}
      ]
    }
  ],
  "articles": [
    {"article_id": "…", "url": "https://www.ryutsuu.biz/sales/s072477.html",
     "title": "ショッピングセンター／6月既存店売上1.6％減、夏物振わず51カ月ぶりに前年割れ",
     "source": "流通ニュース", "first_published_date": "2026-07-25",
     "appeared_count": 2}
  ],
  "quality": {
    "by_method": {"deterministic": 118, "llm": 8, "manual": 2},
    "by_reason_code": {"no_segment_match": 6, "no_metric_match": 3, "no_numeric": 10,
                       "ambiguous_period": 11, "low_confidence": 4,
                       "out_of_scope": 323, "company_disclosure": 0,
                       "no_metric_match_in_multi_value": 0},
    // by_reason_code の合計 = meta.unresolved_count。out_of_scope / company_disclosure も
    // unresolved.json に保持するため（破棄しない・NFR-10）合計に含まれる
    // company_disclosure / no_metric_match_in_multi_value の値は §4.3.5 の残余語ガードで
    // 追加された分類であり、上の例示値は M3 の measure で再計測して差し替える
    "nfr05": {"denominator": 83, "numerator": 64, "rate": 0.771, "target": 0.80,
              "met": false},
    // nfr05 の分母は行単位。company_disclosure は分母から除外し、
    // no_metric_match_in_multi_value は分母にも分子にも加算しない（§4.3.7）
    "out_of_scope_breakdown": {"company_disclosure_by_subject_guard": 154,
                               "non_statistical": 169},
    // 上は out_of_scope（業態未解決）の内訳を raw_line から再計算したもの。
    // reason_code = company_disclosure（残余語ガード）とは検出位置が異なる別集計
    "duplication": {"unique_articles": 406, "total_rows": 595,
                    "duplicate_rows": 189, "max_appeared": 6},
    "unresolved_samples": [
      {"article_id": "…", "digest_date": "2026-07-25",
       "reason_code": "no_numeric", "raw_line": "…", "occurrences": 2}
      // occurrences は series.json（配信用の集計値）にのみ持つ。
      // 永続層 unresolved.json は要件 §4.2 のスキーマどおり 5 列で、この項目を持たない
    ]
  }
}
```

`series` の一意キーは `(segment_id, metric_id, scope, source_authority, period_type)` である。同一業態・同一指標でも発表主体が異なれば**別系列**になる（要件 7-14）。

`series[].points` は **欠測期間を含めない**。`periods.month` が全期間の軸を持ち、`points` に無い期間は「データなし」として描画される（FR-20）。欠測を `null` で埋めた配列にすると、ライブラリ設定を誤ったときに補間が復活しうるため、そもそもデータを渡さない形にした。

### 6.2 単一 HTML への埋め込み

`html/build.py` は `template.html` のプレースホルダを置換するだけの処理に徹する。

```
template.html
  <style>/*__STYLES__*/</style>
  <script>/*__CHARTJS__*/</script>
  <script type="application/json" id="rst-data">__DATA_JSON__</script>
  <script>/*__APP_JS__*/</script>
```

| プレースホルダ | 置換元 | 概算サイズ |
|---|---|---|
| `__STYLES__` | `styles.css` | 約 12 KB |
| `__CHARTJS__` | `vendor/chart.umd.min.js` | 約 205 KB |
| `__DATA_JSON__` | `series.json`（`indent` なしの最小化版） | 現時点で約 90 KB、3 年分想定で約 700 KB |
| `__APP_JS__` | `app.js` | 約 35 KB |

合計は現時点で約 350 KB、3 年後想定で約 1 MB。NFR-03 の 2 MB 以内に収まる。

`__DATA_JSON__` は `<script type="application/json">` の中に入るため、`</script>` によるコンテキスト脱出を防ぐエスケープを必ず行う。

```python
def escape_json_for_script(payload: str) -> str:
    return (payload.replace("<", "\\u003c")
                   .replace(">", "\\u003e")
                   .replace("&", "\\u0026"))
```

記事タイトルに `<` `>` は現れていないが、将来混入した際に white screen になるより確実に防ぐ（NFR-12 のエラー表示方針と同じ考え方）。

**外部参照は一切持たない**。`<link rel="stylesheet" href="...">` / `<script src="...">` / `fetch()` / Web Font / 外部画像を使わない。CSP `default-src 'self'` 相当で全機能が動くこと（NFR-08）を、生成後に次のチェックで機械的に検証する。

```bash
# 一致（exit 0）= NFR-08 違反。不一致（exit 1）= 自己完結を満たす
grep -nE '(src|srcset)="https?:|<link[^>]+href="https?:|fetch\(|XMLHttpRequest|import\(|@import' \
  docs/retail-stats/index.html && exit 1
```

記事出典の `<a href="https://...">` はリンクとして必須（FR-17）なので検査対象から外す。**この除外は「`href` 全般を見ない」のではなく「`<link>` の `href` だけを見る」形でパターン自身に表現する**。当初は `href="https?:(?![^"]*")` と否定先読みで書いていたが、(1) `grep -E`（ERE）は `(?!...)` を解釈できず `invalid syntax` で exit 2 になり検査そのものが走らない、(2) `-P` に替えても正常な `<a href="https://…">` に対して先読みが常に成立し一度も発火しない死んだ枝になる、という二重の欠陥があった。

なお、この grep は**補助的な検査**である。属性値中の空白や大文字小文字、複数行にまたがるタグには行指向の正規表現では対応しきれない。正式な判定はループ設計 ⑥ H1 の `html.parser` による属性ベース解析（`a[href]` は検査対象外）を正とし、本コマンドは生成直後の手元確認および CI/CD 設計 §3.1「Machine checks」の 1 次フィルタとして用いる。

### 6.3 チャート描画の抽象化

要件 §5.4 は Chart.js のインライン埋め込みを指定している。ただし将来の差し替え（§9.4 の U7）に備え、`app.js` 内では次の 1 関数だけがライブラリ API に触れる構造にする。

```javascript
/**
 * 唯一の Chart.js 依存点。ここ以外から Chart を参照しない。
 * param {HTMLCanvasElement} canvas
 * param {{series: Array<{label, points, dash, marker}>, xLabels: string[],
 *          yAxisLabel: string, secondAxis?: {...}}} spec
 */
function renderLineChart(canvas, spec) { /* ... */ }
```

系列スタイルは色に依存させない（NFR-13）。

| 系列 index | 線種（borderDash） | マーカー（pointStyle） |
|---|---|---|
| 0 | 実線 `[]` | `circle` |
| 1 | `[6, 3]` | `triangle` |
| 2 | `[2, 2]` | `rect` |
| 3 | `[10, 3, 2, 3]` | `rectRot` |
| 4 | `[8, 4, 2, 4, 2, 4]` | `star` |
| 5 以降 | 上記を巡回 | 上記を巡回 |

欠測は `spanGaps: false` と、そもそも欠測期間のデータ点を配列に入れないことの二重で防ぐ（FR-20）。

### 6.4 画面の実装方針

ルーティングは `location.hash` を監視し、`#/overview` `#/trend` `#/compare` `#/table` `#/sources` `#/quality` でセクションの表示を切り替える。SPA フレームワークは使わない。

#### 全画面共通: 発表主体の混在禁止（要件 7-14）

カタログ §3-8 のとおり、協会統計（会員社ベース）と政府統計（全国調査ベース）は母集団が異なり伸び率が一致しないことが常態である。同一チャートに並べると、乖離を「異常値」と誤読させる。

| 規則 | 実装 |
|---|---|
| R1 | **1 つのチャートに載る系列の `source_authority` は必ず単一**にする。`renderLineChart()` の呼び出し前に `spec.series` の `source_authority` が 1 種類であることを assert し、違反時は描画せずエラー表示に落とす（silent に混ぜない） |
| R2 | 各画面に**発表主体セレクタ**を置く。既定値は、選択中の業態の `default_source_authority`（= 協会統計）。ユーザーが明示的に切り替えたときのみ他主体を表示する |
| R3 | 選択中の組み合わせに複数主体のデータが存在する場合、セレクタの脇に `この業態には 日本百貨店協会 / 経済産業省（商業動態統計） の 2 系統があります。母集団が異なるため数値は一致しません。` を常時表示する |
| R4 | 凡例・データテーブル・CSV 出力・出典一覧の全てに発表主体を列として含める。チャートを画像として切り出したときに出所が失われないよう、チャートのサブタイトルにも発表主体を表示する |
| R5 | SC-03（指標横断比較）では、発表主体を**先に単一選択させてから**業態を横並びにする。業態ごとに主体が違う状態で並べない |

#### 全画面共通: 集計粒度の混在禁止（カタログ §1.1 / §1.4）

発表主体とは別の軸として、**集計粒度**による混在も禁止する。カタログ改訂で `meti-commerce-dynamics` は「小売業全体」という独立した集計区分に定義が狭められ、個別業態の親ではなくなった。粒度が 1 段違うものを同じチャートに並べると、業態間の比較に「全体」の系列が紛れ込む。

| 規則 | 実装 |
|---|---|
| R6 | **`meti-commerce-dynamics`（小売業全体）を他業態と同一チャートに並べない**。業態セレクタでは他業態と排他のグループに分け、選択すると他業態の選択が解除される。SC-03 の業態横並びからは既定で除外し、`小売業全体を含める` を明示的にオンにしたときのみ**単独系列として**表示する |
| R7 | R6 の除外は silent にしない。業態セレクタの当該項目に `小売業全体（他業態と粒度が異なるため単独表示）` のラベルを付ける |
| R8 | `parent_segment_id` によるロールアップ集計は行わない（§3.3）。「小売業全体」の値は経産省の公表値そのものであり、業態別内訳の合計として算出しない。仮に両方を持っていても足し合わせない |

`entity_type = macro` の 2 件（`ec-platform` = 年度粒度、`cpi` = 物価指数）についても、カタログ §1.2 のとおり業態トレンドとは別軸で表示する（要件 7-4）。R6 と合わせると、SC-02 / SC-03 の既定候補は **`entity_type = association` かつ `meti-commerce-dynamics` を除いた 10 業態**となる。

#### SC-01 概観ダッシュボード

| 要素 | 実装 |
|---|---|
| 最新月サマリーカード | `entity_type == "association"` の業態について、`existing-store-sales-yoy` の最新 `period_key` の値を符号付きで表示。前月値がある場合のみ `（前月 -0.3 → 当月 -1.6）` を併記。値が無い業態は「データなし」と明記してカード自体は出す |
| ハイライト帯 | §6.5 参照 |
| 更新ステータス | `meta` の各値をそのまま表示 |
| データ範囲表示 | `periods.month` の最小・最大を表示し、「収録期間外は表示しません」と注記 |

#### SC-02 業態別トレンド

- 業態セレクタは `display_order` 昇順、既定で `entity_type == "association"` かつ `meti-commerce-dynamics` を除いた 10 業態を候補にする（要件 7-4 / R6）。`macro` と `小売業全体` はそれぞれ別のチェックボックスで追加する
- 発表主体セレクタは R2 に従う。`home-center` のように業界紙集計と経産省統計が並立する業態（カタログ §1.4）では R3 の注記が出る
- 指標セレクタで複数指標を選んだ際、`unit` が 2 種類になったら第 2 軸へ分離。3 種類以上は選択させない（警告を出して最後の選択を拒否）
- 内訳パネル: `customer-count-yoy` と `spend-per-customer-yoy` が同一 `(segment, period)` で揃う期間について、`(1+客数/100) * (1+客単価/100) - 1` を百分率にした参考値と、実際の売上前年比を並べて表示する。**「参考値」であることを明記**し、差分がある場合も警告を出さない（乗法近似であり定義上一致しない）
- 抽出方法バッジは `points[].method` を凡例に反映する
- チャートの直下に同内容のデータテーブルを常設する（NFR-13）

#### SC-03 指標横断比較

- 指標は単一選択、既定は `existing-store-sales-yoy`
- **`period_type` が異なる系列を同一チャートに載せない**。選択指標に複数の `period_type` が存在する場合、`period_type` のタブを出して 1 つに絞らせる（要件 7-5）
- **`source_authority` が異なる系列も同一チャートに載せない**（R1 / R5）。指標 → 発表主体 → 期間種別 の順に単一選択させてから、業態を横並びにする
- 順位テーブルは選択期間の値降順。`direction_hint == "lower_is_better"` の指標では昇順に切り替える
- 期間レンジは `periods[period_type]` の添字によるスライダー 2 本

#### SC-04 データテーブル / SC-05 出典一覧

- SC-04 は全 observation の一覧。業態・指標・期間・抽出方法・`needs_source_check` で絞り込み
- CSV 出力（FR-19）は `Blob` + `URL.createObjectURL` のみを使う。BOM 付き UTF-8（`﻿`）で出力し、Excel で開いたときに文字化けしないようにする。改行は CRLF、値のクォートは RFC 4180 準拠
- SC-05 は `articles` の一覧。各記事から生成された observation を子行として展開し、逆に SC-02 のデータ点クリックで `#/sources?article={id}` に遷移して当該記事にスクロール + ハイライトする（FR-17）

#### SC-06 データ品質

パネルを **3 つに分ける**。「未解決（要改善）」と「対象外（意図的除外）」を同じ表に混ぜないことが、この画面の設計上の要点である。混ぜると 323 件（個社開示 154 + 非統計記事 169）に `company_disclosure`（§4.3.5 の残余語ガードで落ちた行）を加えた対象外が未解決件数として表示され、システムが壊れているように見える。

| パネル | 内容 |
|---|---|
| P1 抽出品質 | `quality.by_method` の件数と比率。`quality.nfr05` を「対象内行 83 件中 64 件を抽出（77.1% / 目標 80% / **未達**）」の形で表示し、**分母の定義（発表主体が協会統計・マクロ統計である行）と達成可否を画面上に明記**する。目標未達の期間は達成率を強調表示し、`no_metric_match` の件数を隣に併記して回収余地が読み取れるようにする |
| P2 未解決（要改善） | `no_segment_match` / `no_metric_match` / `no_numeric` / `ambiguous_period` / `low_confidence` / `llm_schema_error` / **`no_metric_match_in_multi_value`** を `reason_code` 別にグルーピングし、`raw_line` の原文を `<pre>` で表示する。ルール改善・カタログ追加のバックログとして使う。特に `no_segment_match` は「カタログに業態行を追加すべき候補」と明記する（例: `4月都内物価…―総務省`）。**`no_metric_match_in_multi_value` は「カタログに内訳カテゴリの指標を追加すれば回収できる値」と明記**し、`NFR-05 の分母には加算していません（行としては抽出に成功しています）` を併記する。行内のどの値が退避されたのかが読み取れるよう、`raw_line` 中の該当値を強調表示する |
| P3 **対象外（意図的除外）** | `out_of_scope` を `out_of_scope_breakdown` の 2 区分（個社開示 / 非統計記事）で、**`company_disclosure`（残余語ガードで落ちた行）を第 3 の区分**として表示する。冒頭に `これらは抽出の失敗ではなく、本システムの対象範囲外として意図的に除外した記事です。NFR-05 の分母には含みません。` を固定表示し、代表例を各 10 件まで列挙する。`company_disclosure` には `業態名が主語ですが、値の直前に個社名等の未解決語が残るため業態の観測値としませんでした。` を添え、**主語位置ガードで落ちた行（`out_of_scope` の個社開示）と検出理由が異なることを画面上で判別可能**にする |

- 欠測マップは 業態（行）× 期間（列）のテーブル。セルの状態は記号と文字の併記（`値あり` / `—（データなし）` / `!（未解決あり）`）で、色のみに依存させない（NFR-13）。発表主体セレクタで切り替える（R2）
- 重複掲載統計は `quality.duplication` を表示し、`延べ 595 行 → 一意 406 記事 → observation N 件` の縮約が起きていることを確認できるようにする
- 発表主体の内訳表を置き、`department-store` や `home-center` のように複数主体を持つ業態を一覧できるようにする（要件 7-14 の効果確認用）

### 6.5 ハイライト帯の文章生成

`streak_broken_months` と `sign_only` を v0.1 から使う（要件 §5.3 SC-01 / 7-11）。生成は JavaScript ではなく **`html/build.py` 側で文章を確定させ、`series.json` の `highlights` 配列に入れる**。理由は、文章生成規則が変わったときに Git 差分で文章の変化を追えるようにするため。

```python
def build_highlights(obs: list[Observation], catalog: Catalog,
                     latest_period: str) -> list[dict]:
    """SC-01 ハイライト帯の文章を決定論的に生成する。"""
    out: list[dict] = []

    # (1) 連続記録の途切れ — 最優先。提案の場で最も訴求力がある
    for o in _sorted(obs, latest_period):
        if o.streak_broken_months:
            seg = catalog.segment(o.segment_id).name
            out.append({
                "kind": "streak_broken",
                "priority": 1,
                "text": f"{seg}が{o.streak_broken_months}カ月ぶりに前年割れ"
                        f"（{o.period_key} {_signed(o)}）",
                "article_id": o.article_id,
            })

    # (2) 符号の反転
    for o in _sorted(obs, latest_period):
        prev = _previous_period_value(obs, o)
        if prev is not None and o.value is not None and _sign(prev) != _sign(o.value):
            seg = catalog.segment(o.segment_id).name
            met = catalog.metric(o.metric_id).name
            direction = "プラスに転じた" if o.value > 0 else "マイナスに転じた"
            out.append({
                "kind": "sign_flip",
                "priority": 2,
                "text": f"{seg}の{met}が{direction}（{_signed(prev)} → {_signed(o.value)}）",
                "article_id": o.article_id,
            })

    # (3) 定性表現のみの観測
    for o in _sorted(obs, latest_period):
        if o.value is None and o.sign_only:
            seg = catalog.segment(o.segment_id).name
            met = catalog.metric(o.metric_id).name
            word = "増" if o.sign_only == "+" else "減"
            out.append({
                "kind": "sign_only",
                "priority": 3,
                "text": f"{seg}の{met}は{word}（数値未確認）",
                "article_id": o.article_id,
            })

    out.sort(key=lambda h: (h["priority"], h["text"]))     # 決定論的な順序
    return out[:6]


def _signed(o) -> str:
    v = o.value if hasattr(o, "value") else o
    return f"{v:+.1f}"      # -1.6 → "-1.6" / 2.3 → "+2.3"（矢印・絵文字は使わない）
```

実データで生成される文章の例:

- `ショッピングセンターが51カ月ぶりに前年割れ（2026-06 -1.6）`
- `スーパーマーケットが40カ月ぶりに前年割れ（2026-06 -0.3）`
- `ショッピングセンターの既存店売上高前年比がマイナスに転じた（+9.9 → -1.6）`

数値は常に符号付き、矢印記号・絵文字は使わない（要件 §5.4 / NFR-13）。

### 6.6 エラー時の表示

`app.js` の起動処理を `try / catch` で包み、失敗時は白画面にせず次を表示する（要件 §5.4）。

```
データの読み込みに失敗しました。
  原因: <エラーメッセージ>
  最終正常更新: <meta.generated_from_digest_max_date>
  このページの再生成は次のコマンドで行えます:
    python3 -m retail_stats html
```

`meta` は `<script type="application/json">` とは別に `<meta name="rst-generated" content="...">` にも書き出し、JSON のパースに失敗しても最終更新日を表示できるようにする。

### 6.7 印刷スタイル

```css
media print {
  page { size: A4 landscape; margin: 12mm; }
  .rst-nav, .rst-controls, .rst-csv-button { display: none; }
  .rst-chart-wrap { break-inside: avoid; width: 100%; }
  .rst-data-table { break-inside: auto; font-size: 9pt; }
  .rst-data-table thead { display: table-header-group; }   /* 改ページ時にヘッダ再掲 */
  a[href^="http"]::after { content: " (" attr(href) ")"; font-size: 8pt; }
}
```

出典 URL を印刷時に展開するのは、提案資料に転記した際にトレーサビリティ（FR-17）が紙の上でも残るようにするためである。

---

## 7. テスト設計

### 7.1 方針

| 対象 | 方針 |
|---|---|
| `textnorm` / `period` / `parser` | **単体テストで固める**。純関数（文字列 + 掲載日 → 結果）であり、ファイル I/O を伴わない。正規表現ルールは追加され続けるため、ここが回帰の防波堤になる |
| `catalog` | フィクスチャ MD に対する正常系 + 異常系。**異常系で必ず例外が上がることを検証する**（欠損列を既定値で埋めて続行しないこと） |
| `digest` | フィクスチャ MD に対するセクション抽出・行数の検証 |
| `store` | 純粋な dict 操作としてテストする。upsert の勝敗規則と冪等性 |
| `html/build` | 生成 HTML に外部参照が含まれないこと、`</script>` 脱出が起きないことの検証。描画そのものは自動テストしない（目視確認とする） |
| フレームワーク | 標準ライブラリの `unittest`。外部依存を増やさない（NFR-08 の思想を開発環境にも適用）。実行は `python3 -m unittest discover -s scripts/retail-stats-tracker/tests` |

### 7.2 必ず含めるテストケース

#### T-1 冪等性: 同一記事 6 日重複（`s041442`）

要件 NFR-07 が名指ししているケース。掲載日は 04-15 / 16 / 17 / 18 / 22 / 23 の **非連続 6 日**であり、連続日を前提にした実装では落ちる。

```python
def test_s041442_six_day_duplication(self):
    result = run_pipeline(digest_dir=FIXTURES / "digests", catalog=CATALOG)
    art = result.article_by_url("https://www.ryutsuu.biz/sales/s041442.html")

    # 1 記事に収束する
    self.assertEqual(len(result.articles_with_url(art.url)), 1)
    # 6 日分の掲載日が全て記録される（非連続）
    self.assertEqual(art.appeared_dates,
                     ["2026-04-15", "2026-04-16", "2026-04-17",
                      "2026-04-18", "2026-04-22", "2026-04-23"])
    self.assertEqual(art.first_published_date, "2026-04-15")
    # 4 つの title variant が全て保持される（同一タイトルの日は重複排除）
    self.assertEqual(len(art.title_variants), 4)
    # 業態 "カジュアル衣料4社" はカタログ未定義 → observation は 0 件
    self.assertEqual(len(result.observations_for_article(art.article_id)), 0)
    # unresolved.json は 6 行ではなく 1 エントリに集約される（要件 §4.2 の 5 列のまま）
    unres = result.unresolved_for_article(art.article_id)
    self.assertEqual(len(unres), 1)
    # 発表主体マーカー（協会・省庁）を含まず統計語彙と数値を持つ → 対象外（個社開示）
    self.assertEqual(unres[0].reason_code, "out_of_scope")
    # 掲載回数は unresolved.json に持たず、article の appeared_dates から導出する
    self.assertEqual(len(art.appeared_dates), 6)
    self.assertEqual(unres[0].digest_date, "2026-04-15")   # 初出日
    # NFR-05 の分母に含まれないこと
    self.assertNotIn(art.article_id, result.nfr05_denominator_article_ids())
```

#### T-2 冪等性: 2 回実行してバイト一致

```python
def test_rebuild_is_byte_identical(self):
    with tempfile.TemporaryDirectory() as d:
        run_build(out_dir=d, rebuild=True)
        first = {p.name: p.read_bytes() for p in Path(d).glob("*.json")
                 if p.name != "runs.json"}
        run_build(out_dir=d, rebuild=True)
        second = {p.name: p.read_bytes() for p in Path(d).glob("*.json")
                  if p.name != "runs.json"}
        self.assertEqual(first, second)
```

#### T-3 全角 / 半角の混在

同一 URL `s072212` が 2026-07-23 に `1.7％減`（全角）、07-24 に `1.7%減`（半角）で出現する実例を使う。

```python
def test_fullwidth_halfwidth_converge_to_one_observation(self):
    result = run_pipeline(...)
    obs = result.observations_by_key(
        "chain-store", "existing-store-sales-yoy", "existing_store", "2026-06")
    self.assertEqual(len(obs), 1)
    self.assertAlmostEqual(obs[0].value, -1.7)

def test_normalize_table(self):
    cases = [
        ("1.6％減",        "1.6%減"),
        ("６月",            "6月"),          # 全角数字（現行データでは未出現）
        ("日本百貨店協会／", "日本百貨店協会/"),
        ("3〜5月", "3~5月"), ("3～5月", "3~5月"),
        ("51ヶ月",  "51カ月"), ("19ヵ月", "19カ月"), ("3カ月", "3カ月"),
        ("2 月期",  "2月期"),                 # イオン記事の実例
        ("9〜2 月", "9~2月"),                 # ビックカメラ記事の実例
        ("1兆4,505億円", "1兆4505億円"),      # \b バグの回帰テスト（CJK 直前に境界なし）
        ("8,577億円",   "8577億円"),
        ("12,345,678円", "12345678円"),
        ("1,23億円",    "1,23億円"),          # 3 桁でないので除去しない
        ("2026,1",      "2026,1"),           # 同上
    ]
    for src, want in cases:
        with self.subTest(src=src):
            self.assertEqual(textnorm.normalize(src), want)

# 金額換算。旧実装が silent に誤値を返した 8 パターンを必ず含める（§4.3.2 の表）
JPY_CASES = [
    ("233億円", 233.0), ("1兆4505億円", 14505.0),
    ("1兆4,505億円", 14505.0),      # 旧: 505.0（カンマ未除去 → 30 倍の誤差）
    ("8,577億円", 8577.0),          # 旧: 577.0
    ("4560億1000万円", 4560.1), ("31億8500万円", 31.85),
    ("453億6000万円", 453.6), ("256億3466万円", 256.3466),
    ("13兆4470億円", 134470.0), ("1兆円", 10000.0),
    ("約1.5兆円", 15000.0),         # 旧: 50000.0（整数部を捨て 5兆円 に一致）
    ("1.45兆円", 14500.0),          # 旧: 450000.0
    ("2.55兆円", 25500.0),          # 旧: 550000.0
    ("11.9兆円", 119000.0),         # 旧: 90000.0
    ("1.234兆円", 12340.0),         # 旧: 2340000.0
    ("12,345,678万円", 1234.5678),  # 旧: 0.0678（1 つ目のカンマのみ除去 → 678万円 に一致）
]

def test_jpy_conversion(self):
    """silent に誤値が蓄積する経路の回帰テスト。例外が出ないため
    テストで固定しない限り誤りに気づけない（§4.3.2）。"""
    for src, want in JPY_CASES:
        with self.subTest(src=src):
            n = textnorm.normalize(src)
            ms = [m for m in parser.VALUE_JPY_RE.finditer(n)
                  if any(m.group(g) for g in ("cho", "oku", "man"))]
            self.assertEqual(len(ms), 1, f"{src}: 一致数が 1 でない")
            self.assertAlmostEqual(parser.to_jpy_oku(ms[0]), want, places=4)
```

#### T-4 複数指標の分解（FR-11）

```python
def test_split_into_three_observations(self):
    row = DigestRow(
        digest_date="2026-07-25",
        title="日本百貨店協会／6月の外国人売上29.8％増、客数0.5％減・客単価30.4％増",
        url="https://www.ryutsuu.biz/sales/s072448.html", ...)
    obs, unres = parser.parse(row, CATALOG)
    self.assertEqual(len(obs), 3)
    self.assertEqual([o.metric_id for o in obs],
                     ["inbound-sales-yoy", "customer-count-yoy",
                      "spend-per-customer-yoy"])
    self.assertEqual([o.value for o in obs], [29.8, -0.5, 30.4])
    self.assertTrue(all(o.segment_id == "department-store" for o in obs))
    self.assertTrue(all(o.period_key == "2026-06" for o in obs))
    self.assertEqual(len({o.natural_key() for o in obs}), 3)   # 衝突しない

def test_absolute_and_ratio_split(self):
    """カタログ §2.2 申し送り: 総売上高と既存店売上が併存 → 2 レコード"""
    row = DigestRow(digest_date="2026-07-22",
                    title="カスミ／6月の総売上高233億円、既存店売上2.3％減", ...)
    obs, unres = parser.parse(row, CATALOG_WITH_KASUMI)   # 個社を足したカタログ
    self.assertEqual(len(obs), 2)
    self.assertEqual({o.metric_id for o in obs},
                     {"sales-amount-absolute", "existing-store-sales-yoy"})
    self.assertEqual({o.scope for o in obs}, {"n_a", "existing_store"})

def test_residue_guard_drops_company_enumeration(self):
    """(a) 個社の並記: 1 件目も業態の観測値にしない（§4.3.5 / Issue #728）"""
    row = DigestRow(digest_date="2026-07-25",
                    title="ファミレス／6月既存店すかいらーく1.7％増、サイゼリヤ9.7％増", ...)
    obs, unres = parser.parse(row, CATALOG)
    self.assertEqual(obs, [])
    self.assertEqual([u.reason_code for u in unres], ["company_disclosure"])
    self.assertIn("サイゼリヤ", unres[0].raw_line)   # 原文ごと保持する（FR-10）

def test_residue_guard_keeps_segment_level_breakdown(self):
    """(b) 業態内の内訳: 1 件目は採用し、2 件目は退避する（捨てない）"""
    row = DigestRow(
        digest_date="2026-05-20",
        title="家電大型専門店／4月の販売額は12.1％増、生活家電が15.8％増に（経産省調べ）", ...)
    obs, unres = parser.parse(row, CATALOG)
    self.assertEqual(len(obs), 1)
    self.assertEqual(obs[0].segment_id, "electronics-retailer")
    self.assertEqual(obs[0].value, 12.1)
    self.assertEqual(obs[0].source_authority, "meti")
    self.assertGreaterEqual(obs[0].confidence, parser.CONFIDENCE_THRESHOLD)
    # 15.8 を silent に捨てない
    self.assertEqual([u.reason_code for u in unres],
                     ["no_metric_match_in_multi_value"])

def test_no_value_token_is_ever_silently_dropped(self):
    """FR-10 の不変条件。全値トークンが disposition を持つこと（§5.5 I10）"""
    for title in MULTI_VALUE_TITLES:            # Issue #728 の実測 16 行を全て含める
        with self.subTest(title=title):
            row = DigestRow(digest_date="2026-07-25", title=title, ...)
            obs, unres, tokens = parser.parse_traced(row, CATALOG)
            self.assertTrue(all(t.disposition is not None for t in tokens),
                            "disposition 未設定の値トークンがある（silent loss）")

def test_intra_title_collision_lowers_confidence(self):
    """衝突検出は残余語ガード通過後にのみ適用する。現行カタログでは発火経路がほぼ無い
    ため、内訳カテゴリ指標を足した仮カタログで経路そのものを固定する（§4.3.5）"""
    row = DigestRow(digest_date="2026-05-20",
                    title="家電大型専門店／4月の販売額は12.1％増、生活家電が15.8％増に", ...)
    obs, unres = parser.parse(row, CATALOG_WITH_APPLIANCE_SUBCATEGORY)
    self.assertTrue(all(o.confidence == 0.30 for o in obs))
    self.assertTrue(all(o.confidence < parser.CONFIDENCE_THRESHOLD for o in obs))

def test_collision_does_not_fire_on_current_catalog(self):
    """回帰: 現行カタログで衝突が発火しないことを固定する（発火したら設計の前提が崩れている）"""
    self.assertEqual(run_pipeline(...).quality["collision_count"], 0)

def test_metric_alias_resolved_by_value_kind(self):
    """V12 緩和後: 同一別名 '売上高' を値の型で振り分ける（§3.3 / §4.3.4 / Issue #729）"""
    ratio, _ = parser.parse(DigestRow(
        digest_date="2026-04-22",
        title="日本百貨店協会／3月の売上高3.2％増", ...), CATALOG)
    self.assertEqual(ratio[0].metric_id, "all-store-sales-yoy")
    self.assertEqual(ratio[0].value, 3.2)
    self.assertEqual(CATALOG.metric(ratio[0].metric_id).unit, "percent_yoy")

    absolute, _ = parser.parse(DigestRow(
        digest_date="2026-04-15",
        title="日本百貨店協会／3月の売上高は1兆4505億円", ...), CATALOG)
    self.assertEqual(absolute[0].metric_id, "sales-amount-absolute")
    self.assertEqual(absolute[0].value, 14505.0)

def test_ratio_never_stored_in_jpy_oku_metric(self):
    """率を億円として蓄積しないこと。型フィルタ欠如時に実際に起きた誤格納の回帰テスト"""
    for o in run_pipeline(...).observations:
        unit = CATALOG.metric(o.metric_id).unit
        self.assertEqual(o.value_kind, "ratio" if unit.startswith("percent") else "absolute",
                         f"{o.metric_id} に型の異なる値が格納されている")
```

#### T-5 期間解決の各パターン

```python
PERIOD_CASES = [
    # (掲載日, タイトル, period_key, period_type, period_start, period_end)
    ("2026-07-25", "ショッピングセンター／6月既存店売上1.6％減",
     "2026-06", "month", "2026-06-01", "2026-06-30"),
    ("2026-01-20", "（検証用）12月既存店1.0%減",
     "2025-12", "month", "2025-12-01", "2025-12-31"),          # 年またぎ
    ("2026-04-11", "イオン 決算／2 月期増収増益",
     "FY2026-02", "fiscal_year", "2025-03-01", "2026-02-28"),
    ("2026-04-15", "オークワ／26年2月期は増収増益",
     "FY2026-02", "fiscal_year", "2025-03-01", "2026-02-28"),  # 2 桁年
    ("2026-04-20", "DCM／29年2月期売上高6500億円",
     "FY2029-02", "fiscal_year", "2028-03-01", "2029-02-28"),  # 将来期
    ("2026-06-27", "DCM 決算／3〜5月営業利益17.4%増",
     "2026-03~2026-05", "quarter", "2026-03-01", "2026-05-31"),
    ("2026-04-15", "サイゼリヤ 決算／9〜2月増収増益",
     "2025-09~2026-02", "half", "2025-09-01", "2026-02-28"),   # 年またぎ範囲
    ("2026-07-25", "ECプラットフォーム市場規模（2025年度）は前年度比5.8%増",
     "FY2025", "fiscal_year", "2025-04-01", "2026-03-31"),
    ("2026-04-01", "令和8年2月度チェーンストア販売統計",
     "2026-02", "month", "2026-02-01", "2026-02-28"),          # 元号
    ("2026-07-25", "ホームセンター月次実績＝2026年6月度",
     "2026-06", "month", "2026-06-01", "2026-06-30"),
    ("2026-07-23", "貿易赤字、1兆円に半減＝―2026年上半期",
     "2026-H1", "half", "2026-01-01", "2026-06-30"),
]

PERIOD_UNRESOLVED_CASES = [
    ("2026-04-15", "クスリのアオキHD 決算／6〜2月増収増益", "ambiguous_period"),  # span=9
    ("2026-04-11", "イオン 決算／2〜5月営業利益33.6%増",   "ambiguous_period"),  # span=4
]

def test_range_pattern_beats_fiscal_year_end(self):
    """P_RANGE を P_FY_END より先に評価しないと 3月期 に誤マッチする"""
    p = period.resolve("楽天の2026年1-3月期（1Q）の流通総額は約1.5兆円で4.8%増",
                       pub=date(2026, 5, 20))
    self.assertEqual(p.period_type, "quarter")
    self.assertEqual(p.period_key, "2026-01~2026-03")
```

#### T-6 カタログ未定義 ID の検出（FR-24）

```python
def test_undefined_segment_id_in_llm_output_is_rejected(self):
    raw = '[{"segment_id": "convenience-store-2", "metric_id": "existing-store-sales-yoy", ...}]'
    ok, errors = llm.validate_llm_output(raw, CATALOG, pub=date(2026, 7, 25))
    self.assertEqual(ok, [])
    self.assertIn("未定義の segment_id", errors[0])

def test_missing_required_column_raises(self):
    with self.assertRaises(CatalogError) as cm:
        catalog.load(FIXTURES / "catalog" / "missing_column.md")
    self.assertIn("既定スコープ", str(cm.exception))

def test_duplicate_heading_raises(self):
    with self.assertRaises(CatalogError):
        catalog.load(FIXTURES / "catalog" / "duplicate_heading.md")

def test_integrity_check_blocks_write(self):
    """未定義 ID を含む observation があると書き出さずに例外を上げる"""
    store_obj = Store(observations=[OBS_WITH_UNKNOWN_METRIC])
    with self.assertRaises(IntegrityError):
        store_obj.validate_integrity(CATALOG)

def test_v12_allows_same_alias_across_value_types(self):
    """V12 改訂: 値種別が異なれば別名の重複を許す（§3.3 / Issue #729）"""
    # sales-amount-absolute (absolute) と all-store-sales-yoy (ratio) が
    # ともに別名 '売上高' を持つ現行カタログが通ること
    cat = catalog.load(CATALOG_PATH)
    self.assertEqual(
        {m for m in cat.metrics if "売上高" in m.aliases and m.value_type == "ratio"},
        {cat.metric("all-store-sales-yoy")})

def test_v12_still_rejects_same_alias_within_value_type(self):
    """V12 後半の禁止は維持する。ここを緩めると NFR-09 が崩れる"""
    with self.assertRaises(CatalogError) as cm:
        catalog.load(FIXTURES / "catalog" / "dup_alias_same_value_type.md")
    self.assertIn("value_type", str(cm.exception))
```

#### T-7 発表主体の解決と共存（要件 7-14）

natural key の 5 項化が正しく効いていることを、**上書きが起きないこと**として検証する。

```python
def test_association_and_meti_coexist(self):
    """同一業態・同一指標・同一期間でも発表主体が異なれば 2 レコードになる"""
    rows = [
        DigestRow(digest_date="2026-04-25",
                  title="日本百貨店協会／3月の売上高3.4％増、既存店は3.4％増", ...),
        DigestRow(digest_date="2026-05-30",
                  title="百貨店／3月の販売額2.2％増の5547億円、既存店は3.4％増（経産省調べ）", ...),
    ]
    result = run_pipeline_rows(rows, CATALOG)
    obs = result.observations_by_partial_key(
        "department-store", "existing-store-sales-yoy", "existing_store", "2026-03")
    self.assertEqual(len(obs), 2)
    self.assertEqual({o.source_authority for o in obs},
                     {"department-store-association", "meti"})
    # 上書きが起きていないこと（両方の値が残る）
    self.assertEqual(len({o.observation_id for o in obs}), 2)

def test_authority_default_from_catalog(self):
    """記事に発表主体の明示が無ければカタログ既定値を使う"""
    row = DigestRow(digest_date="2026-07-25",
                    title="ホームセンター月次実績＝2026年6月度", ...)
    seg = CATALOG.segment("home-center")
    self.assertEqual(seg.source_authority, "trade-press")

def test_authority_override_by_article(self):
    """記事の 経産省調べ が既定値を上書きする"""
    auth, penalty = parser.resolve_authority(
        "ホームセンター/3月の販売額は3.4%増2868億円、店舗数は0.7%増(経産省調べ)",
        "", CATALOG.segment("home-center"))
    self.assertEqual(auth, "meti")
    self.assertEqual(penalty, 0.00)

def test_source_name_is_not_authority(self):
    """掲載媒体（流通ニュース）が source_authority に混入しない"""
    result = run_pipeline_rows([SC_ROW], CATALOG)
    o = result.observations[0]
    self.assertEqual(o.source_authority, "sc-association")
    self.assertEqual(result.article(o.article_id).source_name, "流通ニュース")

def test_unknown_authority_in_catalog_raises(self):
    """IF-02 発表主体対応表に無い値はエラー停止（V13）"""
    with self.assertRaises(CatalogError) as cm:
        catalog.load(FIXTURES / "catalog" / "unknown_authority.md")
    self.assertIn("未知の発表主体", str(cm.exception))

def test_chart_spec_rejects_mixed_authority(self):
    """R1: 複数の発表主体を 1 チャートに混ぜようとしたら描画しない"""
    spec = build_chart_spec(series=[SERIES_ASSOCIATION, SERIES_METI])
    self.assertFalse(spec.renderable)
    self.assertIn("発表主体", spec.error_message)

def test_home_center_two_authorities_coexist(self):
    """カタログ §1.4: 業界紙集計と経産省統計が別系列として両方残る"""
    rows = [
        DigestRow(digest_date="2026-07-25",
                  title="ホームセンター月次実績＝2026年6月度", ...),
        DigestRow(digest_date="2026-08-01",
                  title="ホームセンター／6月の販売額は3.4％増2868億円（経産省調べ）", ...),
    ]
    result = run_pipeline_rows(rows, CATALOG)
    auths = {o.source_authority for o in result.observations
             if o.segment_id == "home-center"}
    self.assertEqual(auths, {"trade-press", "meti"})

def test_drugstore_company_disclosure_excluded(self):
    """カタログ §1.4: コスモス薬品等の個社決算は drugstore 系列に混ざらない"""
    row = DigestRow(digest_date="2026-07-23",
                    title="コスモス薬品、本決算は売上高・利益ともに堅調な伸び", ...)
    obs, unres = parser.parse(row, CATALOG)
    self.assertEqual(obs, [])
    self.assertEqual(unres[0].reason_code, "out_of_scope")
```

#### T-8 スコープ外の分類（要件 7-15）

```python
SCOPE_CASES = [
    # (タイトル, 期待する分類)
    ("ショッピングセンター／6月既存店売上1.6％減",       "in_scope"),
    ("ホームセンター月次実績＝2026年6月度",               "no_numeric"),
    ("4月都内物価、1.5%上昇＝5カ月連続伸び縮小―総務省",   "no_segment_match"),
    ("農水省・食品等取引実態調査、家庭用値上げ不足24％",   "no_segment_match"),
    ("しまむら 決算／2月期増収増益",                      "out_of_scope"),
    ("カスミ／6月の総売上高233億円、既存店売上2.3％減",    "out_of_scope"),
    ("買い物は「コスパ」、家事は「タイパ」、休息は「メンパ」", "out_of_scope"),
    ("NRF forecasts 4.4% retail sales growth this year",  "out_of_scope"),
]

def test_scope_classification(self):
    for title, want in SCOPE_CASES:
        with self.subTest(title=title):
            self.assertEqual(parser.classify_scope(title, CATALOG), want)

SEGMENT_FALSE_POSITIVE_CASES = [
    # カタログの汎用別名がタイトル本文に一致するが、業態が主語ではない記事。
    # 主語位置ガード（§4.3.3）が無いと個社の値が業態の観測値として格納される
    ("ワタミ 決算／3月期営業利益5.9％増、国内外食好調で客数増",            "外食"),
    ("薬王堂HD 決算／2月期増収減益、ドラッグストア事業「フード」売上高は10.5%増", "ドラッグストア"),
    ("J.フロント 決算／2月期営業利益15.8％減、SC好調も百貨店・デベロッパー事業減益", "百貨店"),
    ("セブン＆アイ 決算／2月期は減収増益、国内コンビニ事業は1.2%増収",      "コンビニ"),
    ("三陽商会 決算／2月期減収減益、大江伸治社長「百貨店不振の影響受けた」",   "百貨店"),
    ("3月消費支出、2.9％減＝節約志向で外食マイナス―総務省",               "外食"),
]

def test_generic_alias_does_not_match_outside_subject(self):
    """汎用別名の誤マッチで個社・家計調査の値が業態に帰属しないこと（§4.3.3）"""
    for title, alias in SEGMENT_FALSE_POSITIVE_CASES:
        with self.subTest(title=title):
            n = textnorm.normalize(title)
            self.assertIn(alias, n, "前提: 別名はタイトル本文に含まれる")
            seg, _ = parser.resolve_segment(n, CATALOG)
            self.assertIsNone(seg, f"{alias} が主語でないのに業態が解決された")

def test_authority_head_exception_is_preserved(self):
    """主語が発表主体名なら本文中の業態名を採る（経産省 商業動態統計の 4 件）"""
    for title in [
        "経済産業省／2月の商業動態統計、小売業販売額は0.2％減の12兆1550億円",
        "経済産業省／5月の商業動態統計、小売業販売額5.3％増の13兆4470億円",
    ]:
        with self.subTest(title=title):
            seg, penalty = parser.resolve_segment(textnorm.normalize(title), CATALOG)
            self.assertEqual(seg.segment_id, "meti-commerce-dynamics")
            self.assertEqual(penalty, 0.05)

def test_multi_subject_values_are_not_misattributed(self):
    """D5 / 旧 U10: 1 記事に複数主体の値が並ぶとき、片方だけを業態値として採らない"""
    row = DigestRow(digest_date="2026-03-31",
                    title="ドラッグストア／2月既存店売上ツルハ4.0%増、コスモス薬品7.0%増", ...)
    obs, unres = parser.parse(row, CATALOG)
    # (1) ツルハの 4.0 が drugstore の既存店売上として格納されないこと
    self.assertEqual(obs, [], "個社の値が業態の観測値になっている")
    self.assertEqual([u.reason_code for u in unres], ["company_disclosure"])
    # (2) コスモス薬品の 7.0 が痕跡なく消えないこと（FR-10 の silent loss）
    self.assertIn("コスモス薬品7.0%増", unres[0].raw_line)

def test_authority_marker_evaluated_before_company_rule(self):
    """判定順序の回帰テスト。総務省の記事が個社扱いで黙って除外されない"""
    self.assertEqual(
        parser.classify_scope("4月都内物価、1.5%上昇―総務省", CATALOG),
        "no_segment_match")

def test_out_of_scope_is_persisted_not_discarded(self):
    """対象外行を破棄しない（FR-10 / NFR-10）"""
    result = run_pipeline(...)
    oos = [u for u in result.unresolved
           if u.reason_code in ("out_of_scope", "company_disclosure")]
    self.assertGreater(len(oos), 0)
    self.assertTrue(all(u.raw_line for u in oos))

def test_out_of_scope_never_calls_llm(self):
    """対象外行に LLM コストを払わない（NFR-11）"""
    client = CountingLlmClient()
    run_pipeline(..., llm_client=client)
    self.assertEqual(client.calls_for_reason("out_of_scope"), 0)

def test_nfr05_denominator_excludes_out_of_scope(self):
    q = run_pipeline(...).quality
    self.assertEqual(q["nfr05"]["denominator"],
                     q["counts"]["in_scope_extractable"]
                     + q["by_reason_code"]["no_numeric"]
                     + q["by_reason_code"]["no_segment_match"]
                     + q["by_reason_code"]["no_metric_match"])
    # company_disclosure は対象外群なので分母に入らない。
    # no_metric_match_in_multi_value は値単位の退避なので分母にも分子にも入らない（§4.3.7）
    for code in ("out_of_scope", "company_disclosure",
                 "no_metric_match_in_multi_value"):
        self.assertNotIn(code, q["nfr05"].get("denominator_codes", []))
    # 現時点の確定値は 0.771（64/83）で未達（§4.3.7 / §9.4 U9）。
    # 0.697 / 0.753 は §4.3.7 推移表の中間値であり、閾値の根拠に使わない。
    # 閾値 assert は U9 の解決後に有効化する
    self.assertEqual(q["nfr05"]["met"], q["nfr05"]["rate"] >= 0.80)
```

#### T-9 集計粒度の混在禁止（カタログ §1.1 / §1.4 の構造変更）

```python
def test_meti_commerce_dynamics_excluded_from_default_segments(self):
    """R6: 小売業全体は業態横並びの既定候補に入らない"""
    defaults = build_default_segment_candidates(CATALOG)
    self.assertNotIn("meti-commerce-dynamics", {s.segment_id for s in defaults})
    self.assertEqual(len(defaults), 10)   # association 11 件 - 小売業全体 1 件
    # 内訳: shopping-center / department-store / chain-store / convenience-store /
    #       supermarket / family-restaurant / home-center / drugstore /
    #       co-op / electronics-retailer

def test_chart_spec_rejects_mixed_granularity(self):
    """R6: 小売業全体と個別業態を 1 チャートに混ぜようとしたら描画しない"""
    spec = build_chart_spec(series=[SERIES_DEPARTMENT_STORE, SERIES_METI_TOTAL])
    self.assertFalse(spec.renderable)
    self.assertIn("粒度", spec.error_message)

def test_no_parent_rollup(self):
    """R8: parent_segment_id による値の足し上げを行わない"""
    # 将来 種別=company 行が入っても、親業態の値が子の合計で書き換わらないこと
    result = run_pipeline_rows([SEVEN_ELEVEN_ROW, CVS_ASSOCIATION_ROW],
                               CATALOG_WITH_COMPANY_ROWS)
    cvs = result.observations_by_partial_key(
        "convenience-store", "existing-store-sales-yoy", "existing_store", "2026-06")
    self.assertEqual(len(cvs), 1)
    self.assertEqual(cvs[0].value, -0.1)      # 協会公表値のまま。子の合算をしない

def test_catalog_has_no_parent_links_today(self):
    """現行カタログでは 13 行すべての 上位業態 が空欄であることの回帰テスト。
    将来リンクが復活したら気づけるようにする（集約に使わない方針の確認）"""
    self.assertTrue(all(s.parent_segment_id is None for s in CATALOG.segments))
```

#### T-10 その他の必須ケース

| ID | 内容 |
|---|---|
| T-10a | 決算・統計章が存在しない日（2026-04-14）でエラーにならず、`files_without_section` が加算される |
| T-10b | ヘッダ行の列順を入れ替えたフィクスチャで、列位置が動的に解決される（FR-02） |
| T-10c | ヘッダ行の列名を `記事` → `Article` に変えても解決される（許容リスト） |
| T-10d | ヘッダ行の列名を未知の名前に変えたら **停止する**（silent な欠測を防ぐ、要件 7-12） |
| T-10e | `manual_override = true` の observation が自動 upsert で上書きされない（FR-23） |
| T-10f | confidence 同値・掲載日同値の場合に既存側が維持される（走査順非依存） |
| T-10g | 生成 HTML に `src="http` / `fetch(` / `import(` が含まれない（NFR-08） |
| T-10h | `streak_broken_months` がカタログ §4.1 のとおり `existing-store-sales-yoy = -1.6` かつ `51` として格納される |
| T-10i | `増収増益` が `operating-revenue-yoy` / `operating-profit-yoy` の 2 件、`value = None`、`sign_only = "+"`、`needs_source_check = True` になる |
| T-10j | 金額換算は `test_jpy_conversion`（T-3）で 16 パターンを固定する。旧実装が silent に誤値を返した 8 パターン（`1兆4,505億円` / `8,577億円` / `約1.5兆円` / `1.45兆円` / `2.55兆円` / `11.9兆円` / `1.234兆円` / `12,345,678万円`）を必ず含める |

### 7.3 テストデータの置き場所と切り出し

**置き場所**: `scripts/retail-stats-tracker/tests/fixtures/`。実データのコピーを Git 管理する。

**なぜコピーするか**: 実ファイル（`.companies/.../daily-digest/*.md`）を直接読むテストは、日次ダイジェストが毎日追加・修正されるため再現性を持たない。テストが「昨日は通ったのに今日落ちる」状態になると、決定論パースのルール追加サイクル（要件リスク 7-7）が回らない。

**切り出しツール**: `tests/make_fixtures.py` が実データから決算・統計章のみを抜き出して最小の MD を生成する。

```bash
python3 scripts/retail-stats-tracker/tests/make_fixtures.py \
  --dates 2026-04-14,2026-04-15,2026-04-16,2026-04-17,2026-04-18,2026-04-22,2026-04-23 \
  --dates 2026-07-22,2026-07-23,2026-07-24,2026-07-25,2026-07-26 \
  --out scripts/retail-stats-tracker/tests/fixtures/digests/
```

生成物は `# 日次ダイジェスト YYYY-MM-DD` 見出し + `## B. 小売ドメイン` + `### B5. 決算・統計` の表のみを含む。A 章・C 章・D 章は落とす。

**フィクスチャに選んだ日付とその理由**:

| 日付群 | 検証対象 |
|---|---|
| 2026-04-15 / 16 / 17 / 18 / 22 / 23 | `s041442` の非連続 6 日重複、4 つの title variant、短縮 variant（04-17） |
| 2026-04-14 | 決算・統計章そのものが存在しない日 |
| 2026-07-22 〜 07-26 | 主要 4 業態の 6 月既存店、全角 / 半角混在（`s072212` / `s072211`）、複数指標分解（`s072448`）、`51カ月ぶりに前年割れ`（`s072477`）、`40カ月ぶりに前年割れ`（`s072116`）、生協の総供給高（`s072117`）、金額 + 率の併存（`s072111`）、`ホームセンター月次実績＝2026年6月度`（数値なし）、`ECプラットフォーム市場規模（2025年度）`（年度）、出典名の揺れ（`DCS` / `ダイヤモンド・チェーンストア`） |

**カタログのフィクスチャ**: 実カタログの `## 1.` `## 2.` セクションのみを写した `valid.md` を基本とし、そこから 1 箇所だけ壊した異常系 4 種（`missing_column.md` = 既定スコープ列を削除、`duplicate_heading.md` = `## 3. 業態区分の補足` を追加して多重一致させる、`undefined_id.md` = 上位業態に存在しない ID を書く、`unknown_authority.md` = 発表主体列に対応表外の組織名を書く）を作る。異常系は「1 箇所だけ違う」ことで、テスト失敗時に原因が一意に決まるようにする。

**個人情報の扱い**: フィクスチャに含まれるのは公開記事の見出しと URL のみであり、個人情報・顧客固有情報は含まない（NFR-15）。

---

## 8. 実装ステップ（マイルストーン）

各ステップの終わりに「動くもの」が残ることを条件に順序を決めた。M3 が判断の分岐点であり、ここで NFR-04 / NFR-05 の見込みが立たなければ M4 以降の設計を見直す。

### M1. 骨格と入力の確定

| 項目 | 内容 |
|---|---|
| 作るもの | `config.py` / `models.py` / `textnorm.py` / `digest.py` / `cli.py`（`build --dry-run` のみ） |
| 完了条件 | `python3 -m retail_stats build --dry-run --rebuild` が 102 ファイルを走査し、決算・統計章を持つ 93 ファイル / 表を持つ 89 ファイル / データ行 595 行 / リンク抽出成功 595 件 を標準出力に出す。章が無い 9 日を `files_without_section` として列挙する |
| テスト | `test_textnorm.py`（T-3 の正規化表）、`test_digest.py`（T-10a〜T-10d） |
| 想定作業量 | 小 |

### M2. カタログローダ

| 項目 | 内容 |
|---|---|
| 作るもの | `catalog.py`、フィクスチャ 4 種 |
| 完了条件 | 実カタログから 業態 13 件 / 指標 14 件 を読み込み、`--dry-run` の出力に ID 一覧と発表主体コードの一覧を出す。異常系フィクスチャ 4 種で例外が上がる |
| テスト | `test_catalog.py`（T-6 の V1〜V13、T-7 の `test_unknown_authority_in_catalog_raises`、T-9 の `test_catalog_has_no_parent_links_today`） |
| 想定作業量 | 小 |

### M3. 決定論パースと分布計測（**判断の分岐点**）

| 項目 | 内容 |
|---|---|
| 作るもの | `period.py` / `parser.py` / `report.py` / `cli.py` の `measure` サブコマンド |
| 完了条件 | `python3 -m retail_stats measure --rebuild` が 595 行全件を処理し、次を出力する:<br>・**NFR-05 の分母 / 分子 / 達成率**（対象内行のみ。設計時実測は 64/83 = 77.1% で**未達**。§9.4 の U9 参照）<br>・`reason_code` 別の件数（`no_segment_match` / `no_metric_match` / `no_numeric` / `ambiguous_period` / `low_confidence` / `out_of_scope` / **`company_disclosure`** / **`no_metric_match_in_multi_value`**）<br>・`out_of_scope` の内訳（個社開示 / 非統計記事）と `company_disclosure` を分母から除外した件数として別枠表示<br>・**残余語ガードの発火件数と、落とした行の原文**（§4.3.5。(a) の除外が過剰でないことを目視で確認する）<br>・**intra-title 衝突の発火件数**（現行カタログでは 0 が期待値）<br>・**FR-10 の不変条件（§5.5 I10）を満たすこと**。`disposition` 未設定の値トークンが 1 つでもあれば `measure` は非 0 で終了する<br>・主要 4 業態 × 月次既存店指標のカバー率（NFR-04 の判定）<br>・発表主体別の observation 件数と、**複数主体を持つ業態の一覧**（要件 7-14 の効果確認）<br>・未解決行の原文を reason_code 別に上位 20 件ずつ |
| 判定 | NFR-04（主要 4 業態で 90% 以上）と NFR-05（対象内行で 80% 以上）の双方を満たすこと。いずれかが未達なら M3 に留まり、`no_segment_match` に出た業態をカタログに追加するか正規表現ルールを追加する |
| テスト | `test_period.py`（T-5）、`test_parser.py`（T-4、T-7 の発表主体解決、T-8 のスコープ分類、T-10h〜T-10j） |
| 想定作業量 | 大（本システムの中核） |

要件リスク 7-7 が指定する「初期構築時に 588 行を全件処理し reason_code 別の未解決分布を計測する」は、**この M3 の完了条件そのもの**として組み込む。独立した PoC フェーズを設けず、`measure` サブコマンドとして製品コードに残す。以後、正規表現ルールを追加するたびに同じコマンドで効果を測れるようにするためである。

### M4. 永続化と冪等性

| 項目 | 内容 |
|---|---|
| 作るもの | `store.py` / `cache.py`、`build`（`--no-llm`）の完全動作 |
| 完了条件 | `observations.json` / `articles.json` / `unresolved.json` / `manifest.json` / `runs.json` が生成される。`--rebuild` を 2 回連続実行して `runs.json` 以外がバイト一致する |
| テスト | `test_store.py`（T-10e、T-10f、T-7 の `test_association_and_meti_coexist`）、`test_idempotency.py`（T-1、T-2） |
| 想定作業量 | 中 |

### M5. LLM フォールバック

| 項目 | 内容 |
|---|---|
| 作るもの | `llm.py`（`NullClient` / `ClaudeCliClient`）、スキーマ検証、キャッシュ書き込み |
| 完了条件 | M3 で `low_confidence` に落ちた行に対して LLM を 1 回だけ呼び、結果がキャッシュされる。2 回目の実行で LLM 呼び出しが 0 件になる（キャッシュヒット率 100%）。`--no-llm` でパイプラインが完走する |
| テスト | T-6 の LLM 出力検証、キャッシュキーの決定性（variant 選択が走査順に依存しない） |
| 想定作業量 | 中 |

### M6. 配信 JSON と単一 HTML

| 項目 | 内容 |
|---|---|
| 作るもの | `series.json` 生成、`html/build.py` / `template.html` / `app.js` / `styles.css`、Chart.js の vendoring |
| 完了条件 | `docs/retail-stats/index.html` が生成され、**ネットワークを切った状態**で `file://` から開いて SC-01 / SC-02 / SC-03 / SC-04 / SC-05 / SC-06 が動作する。HTML 総サイズが 2 MB 以内。A4 横で印刷してチャートとテーブルが崩れない |
| テスト | T-10g、T-7 の `test_chart_spec_rejects_mixed_authority`、T-9（R6 の粒度混在禁止・既定候補 10 業態）、`series.json` のスキーマ検証、ハイライト文章の決定性、SC-06 の 3 パネル分離（`out_of_scope` が未解決件数に混ざらないこと） |
| 想定作業量 | 大 |

### M7. 運用への接続

| 項目 | 内容 |
|---|---|
| 作るもの | `--report-json` の PR 本文向け整形、`--fail-on-unresolved-rate`、`docs/index.html` へのリンク追加、`README.md` |
| 完了条件 | 差分レポートに 新規 / 更新 / 未解決 の件数と、値が変わった observation の前後（要件リスク 7-8）が出る |
| 引き継ぎ | GitHub Actions ワークフロー（FR-21 / IF-04）の定義は ci-cd-engineer に引き渡す。本ステップでは CLI が返す終了コードと `--report-json` の形式を確定させるところまでを担当する |
| 想定作業量 | 小 |

### 依存関係

```
  M1 ──▶ M2 ──▶ M3 ──▶ M4 ──▶ M5
                 │       │      │
                 │       └──────┴──▶ M6 ──▶ M7
                 │
                 └─ 判定: NFR-04 未達なら M3 に戻り正規表現ルールを追加
```

M5（LLM）と M6（HTML）は M4 完了後に並行可能。M6 は `--no-llm` で得た observations だけでも着手できるため、LLM 実行主体の未決（要件 7-10）が解決するのを待たない。

---

## 9. 前提・制約・未決事項

### 9.1 前提

| # | 内容 |
|---|---|
| P1 | 実装言語は Python（要件 補足 A）。標準ライブラリのみを使用し、外部パッケージを追加しない。実行環境は Python 3.10 以上（開発環境の実測値は 3.12.13）。`unicodedata` / `re` / `json` / `hashlib` / `datetime` / `calendar` / `argparse` / `pathlib` / `unittest` のみ |
| P2 | カタログ（`retail-monthly-kpi-catalog.md`）は小売ドメイン室の管轄であり、本システムは読み取り専用。業態 13 件 / 指標 14 件の定義は本システムが持たない（FR-03 / FR-24） |
| P3 | 日次ダイジェスト MD は読み取り専用（IF-01）。本システムは一切書き換えない |
| P4 | 決算・統計章の表は `#` / `記事` / `ソース` / `要約` の 4 列。実測では表を持つ 89 ファイル全てがこの構成で例外なし。列の追加には動的解決で耐えるが、列名の変更は停止させる（要件 7-12） |
| P5 | Chart.js は MIT ライセンス。vendoring 時に `vendor/LICENSE-chartjs` を同梱し、HTML の footer にライセンス表記を出す |
| P6 | 本書のスコープはアプリケーション本体。Claude Code の hooks / subagent / skill を用いた開発体制、GitHub Actions ワークフローの定義は本書の対象外（ai-developer / ci-cd-engineer 管轄） |

### 9.2 制約

| # | 内容 | 本設計での扱い |
|---|---|---|
| C1 | 入力は記事タイトルと 1 文要約のみ。本文は取得しない（要件 7-3） | タイトルに数値が無い記事からは observation を生成せず `no_numeric` に落とす |
| C2 | 章番号（B5）が安定しない（要件 7-1） | 見出しテキスト `決算・統計` の部分一致で判定。章が無い 9 日はスキップして記録 |
| C3 | 同一 URL でタイトルが日により異なる（要件 7-2） | URL を一意キーとし、variant を全保持。キャッシュキーには「数値トークン数 → 長さ → 辞書順」で決定論的に選んだ 1 variant を使う |
| C4 | 統計値の改定（速報 → 確報）で既存値が上書きされる（要件 7-8） | `_wins()` の規則で上書きし、値が変わった場合は差分レポートに前後を必ず出す。D1 により上書きは同一発表主体内でのみ起こる |
| C5 | 数値パースの副作用リスク | `20%メガポセール` のようにキャンペーン名の数値が混入しうる。左窓に指標別名が無ければ observation を作らないため、現行データでは実害が出ていない。`measure` の未解決一覧で継続監視する |
| C6 | 同一業態に複数の発表主体が並立する（要件 7-14 / カタログ §1.4） | natural key に `source_authority` を含めて共存させる（D1）。画面では §6.4 の R1〜R5 で混在を禁止する |
| C7 | 決算・統計章の約 8 割が本システムの対象範囲外の記事である（要件 7-15） | `out_of_scope` として明示分類し NFR-05 の分母から除外する（D3）。破棄も silent skip もせず SC-06 の P3 パネルに独立表示する |
| C8 | IF-02 発表主体対応表はカタログではなく要件定義側で維持する | カタログ「発表主体」列に検出語の列が無いため。カタログに新しい発表主体が追加された場合は `Catalog.validate()` の V13 がエラー停止で検知する（暗黙受理しない） |
| C9 | `meti-commerce-dynamics`（小売業全体）は他業態と集計粒度が 1 段違う（カタログ §1.1 / §1.4） | §6.4 の R6 / R7 で同一チャート表示を禁止し、既定候補から除外する。除外は silent にせずセレクタにラベルを出す |
| C10 | `parent_segment_id` によるロールアップ集計を行わない（カタログ改訂で `electronics-retailer` の親リンクが削除され、現行は 13 行すべて空欄） | §3.3 / R8。集約すると「小売業全体」と業態別内訳が二重計上される。V9 / V10 は将来の `種別=company` 行に備えた防御的検査として残す |
| C11 | **個社名の辞書が存在しない**（カタログに `種別=company` の行が 0 件） | 値の左窓の残余語が個社名か内訳カテゴリかを機械的に区別できない。区別できないケースは保守的に `company_disclosure`（対象外）へ倒す（D5）。カタログに個社行または内訳カテゴリ指標が追加されれば判定は自動的に改善する（コード変更不要・NFR-09） |
| C12 | **同じ別名が値種別の異なる 2 指標を指しうる**（`売上高` = 率 / 絶対額。カタログ §2.2） | 曖昧性は記事表記の性質でありカタログの不備ではない。V12 を値種別で緩和し、値の型で候補を絞る（D6 / §3.3 / §4.3.4）。値種別が同一の指標間での重複は引き続き禁止する（緩めると NFR-09 が崩れる） |

### 9.3 設計工程で確定させた決定事項

設計書 v0.1 初版では未決（U1 / U3 / U4）として残していた 3 件を、レビューを経て**設計として確定**させた（D1〜D4。要件定義 v0.1.1 に反映済み）。さらに **D5 / D6** は M3 の実装からの報告（Issue #728 / #729）を受けて確定させたもので、要件定義 **v0.1.2** に反映済みである。本書の §3〜§8 はいずれも確定後の内容で記述されている。実装後に判明していれば過去データの汚染や作り直しを伴っていた種類の問題である。

#### D1. natural key に `source_authority` を追加（旧 U3）

**確定内容**: natural key を `(segment_id, metric_id, scope, period_key, source_authority)` の 5 項に拡張する。要件 v0.1.1 §4.2 / FR-09 / 7-14、本書 §4.3.6 / §5.3。

**根拠**: 同一の業態・指標・期間でも発表主体が異なれば母集団の異なる**別の量**である（カタログ §1.1 / §3-8 / §1.4）。4 項キーでは協会統計と政府統計が相互に上書きし、可視化の前段で誤データが混入する。実測では `経産省調べ` / `経済産業省` を含む一意タイトルが 19 件あり、`home-center` は 業界紙集計 と 経産省 の 2 主体が恒常的に並立する。

**波及範囲**: カタログ「発表主体」列を IF-02 の必須列に追加（列自体はカタログに既存のため小売ドメイン室の作業は発生しない）。発表主体対応表を IF-02 に新設。`Catalog.validate()` に V13、`store.validate_integrity()` に I8 を追加。画面側は §6.4 の R1〜R5 で混在を禁止。

**副次効果**: `_wins()` による上書きが同一発表主体内でのみ起こるようになり、差分レポートに出る上書きを「速報→確報の改定」または「記事の誤記訂正」に絞り込めるようになった（要件 7-8 の解釈が明確になる）。

#### D2. `meti-commerce-dynamics` は segment として残すが、個別業態の親ではない（旧 U3 の派生論点）

**確定内容**: `meti-commerce-dynamics` は「小売業全体」という集計区分を表す segment であり、発表主体の軸とは独立に扱う。経産省が業態別内訳を発表した場合は各業態の segment に `source_authority = meti` として記録し、`meti-commerce-dynamics` には計上しない。本書 §4.3.6。

**根拠**: 「小売業全体」は記事の主語であり segment の性質を持つ。一方「誰が発表したか」は直交する軸であり、両者を 1 列に押し込むと `百貨店（協会）` と `百貨店（経産省）` のどちらかが表現できなくなる。

**カタログ側の構造変更（本設計の指摘を受けたドメイン室の再検討結果）**: 「経産省統計を個別業態の親として扱うのはドメイン誤り」との結論に至り、カタログが次のとおり改訂された。本書はこの改訂後の構造に準拠している。

| カタログの変更 | 本書への反映 |
|---|---|
| `meti-commerce-dynamics` の定義を「小売業全体」という独立区分に狭めた | §6.4 の R6 で他業態との同一チャート表示を禁止（粒度が 1 段違うため）。SC-02 / SC-03 の既定候補は `association` 11 件から `meti-commerce-dynamics` を除いた **10 業態** |
| `electronics-retailer` の `上位業態` リンクを削除（**現行カタログでは 13 行すべての `上位業態` が空欄**） | §3.3 に「`parent_segment_id` は集約に使わない」を明記。ロールアップ処理を実装しない。V9 / V10 は将来の `種別=company` 行に備えた防御的検査として残す |
| §1.4 で多発表主体パターン（`home-center` / `drugstore`）を明記 | §4.3.6 に「ドメイン側からの裏付け」節を新設し、D1 の直接の根拠として引用 |
| §1.5 で `種別=company` 行の書き方を規定（`発表主体` は当該企業名そのもの） | §4.3.7 の将来拡張、および IF-02 発表主体対応表の個社向け規則として参照 |

**二重計上のリスク**: 仮に親子集約を実装していると、「小売業全体」の値と各業態の内訳が同一チャート上で二重に載る。R8 でこれを明示的に禁止した。

#### D3. NFR-05 の分母を再定義し、対象外行を `out_of_scope` として明示分類（旧 U1）

**確定内容**: NFR-05 の分母を「発表主体が協会統計・マクロ統計である行」に再定義する。個社決算記事と非統計記事は `out_of_scope` として分母から除外し、**破棄せず件数と原文を保持して SC-06 に独立表示**する。個社の全面カタログ化は行わない。要件 v0.1.1 NFR-05 / §4.2 / 7-15、本書 §4.3.7 / §6.4。

**根拠**: 業態解決率 19.0%（77 / 406 [代表]。§4.3.7）の原因は決定論パースの精度不足ではなく、決算・統計章の約 8 割が本システムの対象範囲外の記事である点にある。ルール追加では解消しない性質の問題であり、分母の定義を実態に合わせるのが正しい対処である。個社の全面カタログ化を採らないのは、本システムの目的が業態トレンドの比較であり（要件 7-4 で業態トレンドの既定を `association` のみと決めている）、数十社分の個社定義の保守コストが目的に見合わないため。

**再定義後の実測**: 分母 83、分子 64 → **77.1%**（カタログ指標別名の追加と §4.3.3 主語位置ガードを反映した確定値）。**目標 80% を下回っており未達**（§9.4 の U9）。分母の再定義自体は妥当だが、これだけでは NFR-05 を満たさない。

**silent fail を作らないための設計**: `out_of_scope` と `no_segment_match` を判定木で厳密に分ける（§4.3.7）。統計の発表主体（協会・省庁）を名乗っているのに業態が取れない行は `no_segment_match` として分母に残し、カタログ追加の候補として SC-06 に出す。実測 6 件（`4月都内物価、1.5%上昇―総務省` 等の地域別 CPI、`6月消費者物価、1.6％上昇―総務省`、`3月消費支出、2.9％減―総務省`）。この順序を逆にすると、カタログの不足が個社扱いで黙って除外され改善の signal が消える。

**将来拡張**: カタログは `種別=company` 行を受理できる状態を維持する（V3 の enum に既に含む）。頻出上位の個社を追加すれば、その記事は自動的に `out_of_scope` から外れる。パーサのコード変更は不要（NFR-09）。書き方の想定はカタログ §1.5 に記載済み。

#### D4. 既定スコープと「既存店の文字列」判定の関係（旧 U4）

**確定内容**: カタログ §2.2 の判定ルールは `existing-store-sales-yoy` という **`metric_id` への昇格**を禁じるものであり、各指標の `既定スコープ` の適用そのものは禁じない。したがって `日本百貨店協会／6月の外国人売上29.8％増、客数0.5％減・客単価30.4％増` は、`既存店` の文字列が無くても各指標の既定値に従い `scope = existing_store` で格納する。本書 §3.3 / §4.3.5 step 6。

**根拠**: 小売ドメイン室がカタログ §2.2 に適用順序を明記した（`既定スコープ` は `metric_id` 採用後に scope へ機械的に割り当てる値であり、`metric_id` の決定には関与しない。`metric_id` の決定は §2.2 の判定ルールが優先する）。本書 v0.1 初版の解釈と一致しており、**確認は完了**している。

**実装への影響**: `resolve_scope()` は現状のままでよい。判定順序を逆にしないこと（既存店表記のない見出しを既存店統計として扱うのが最も頻発する誤読であり、カタログ §3-1 が最上位の落とし穴として挙げている）。

#### D5. FR-10 を無条件の絶対条件とし、残余語ガードを導入（旧 U10 / Issue #728）

M3 の実装で、設計 §4.3 の内部に不整合が見つかったことを受けた確定。実装は設計の条文どおりに書かれており、コード側での回避は行われていない（FR-03 / NFR-09）。

**発端**: §4.3.5 の intra-title 衝突検出は `ファミレス／6月既存店すかいらーく1.7％増、サイゼリヤ9.7％増` で衝突が起きる前提で書かれていたが、**§4.3.1 の左窓規則では 2 件目の左窓が `サイゼリヤ` になり指標が解決できない**。observation は 1 件しか生成されず、**衝突は起きない**。用意した安全網が構造的に発火しない状態だった。

結果として 1 行で 2 つの事故が同時に起きていた。(1) 個社の値が業態の観測値になる、(2) もう一方の値が痕跡なく消える（**silent loss**）。実測 16 行が該当。

**確定内容 1 — FR-10 は無条件の絶対条件**: **値トークンが observation にも `unresolved` にも現れない状態は、いかなる理由があっても許容しない。** §1.2 が本プロジェクト最大の危険と位置づけた silent accumulation の**最も直接的な形**であり、NFR-05 の分子が減ることや実装が複雑になることはこの原則を曲げる理由にならない。§1.2 の設計方針表に絶対条件として明記し、§5.5 の I10 で機械的に検査する。

**確定内容 2 — 一律 `out_of_scope` にはしない**: 該当 16 行には (a) 個社の並記（`ドラッグストア／…ツルハ4.0%増、コスモス薬品7.0%増`）と (b) 業態内の内訳（`家電大型専門店／4月の販売額は12.1％増、生活家電が15.8％増に（経産省調べ）`）が混在する。(b) はカタログ §1.1 が `electronics-retailer` の発表主体を「経済産業省（商業動態統計）」のみと定めている**業態統計そのもの**であり、`out_of_scope` に落とすと本来取るべきデータを捨てることになる。

**確定内容 3 — 判定基準は左窓の残余語**: **指標別名・業態別名・期間表現のいずれにも該当しない残余語が値の左窓にある場合、その値は業態の観測値としない。** §4.3.3 の主語位置ガードの自然な拡張であり（あちらは「主語の位置」で、こちらは「値の直前の修飾語」で個社を弾く）、両者は同じ危険に対する適用位置の異なる 2 つの防壁である。実装は §4.3.5 の残余語ガード。

**確定内容 4 — (b) の 2 件目も捨てない**: `生活家電 15.8` は `no_metric_match_in_multi_value` として `unresolved` に退避し、SC-06 の P2 に表示する。**将来カタログに内訳カテゴリ指標を追加すれば回収できる形**で残す。`reason_code` enum に `company_disclosure` と `no_metric_match_in_multi_value` を追加（要件 §4.2、7 値 → 9 値）。

**確定内容 5 — 判定できないケースは保守的に対象外**: 残余語が個社名か内訳カテゴリかを機械的に区別する手段は無い（カタログに `種別=company` の行が 0 件のため個社名の辞書が無い）。区別できないケースは `company_disclosure` に倒す。ただし `unresolved` への退避は必ず行い、SC-06 で件数を追えるようにする。

**確定内容 6 — 衝突検出は削除しない**: 本方針のもとで発火経路はほぼ無くなるが、カタログに内訳カテゴリ指標が追加されれば (b) の系統で発火しうる。カタログ追記だけで発火条件が成立する以上（NFR-09）、検出を外すとその時点で silent な上書きが復活する。§4.3.5 に「どの条件で発火しうるか」を書き直し、`measure` で発火件数 0 を継続確認する。

**確定内容 7 — NFR-05 への影響は受け入れる**: 本対応で分子が減る。**既に未達（設計確定値 64/83 = 77.1%）であり、正確性を犠牲にして数値を維持しても意味がない。** **「正しく未達」であることの方が、「誤ったデータで達成に見える」ことより価値がある。** 減った分は SC-06 の P3 に `company_disclosure` として明示され、取りこぼしではなく意図的な除外だと画面から判別できる。確定値は M3 の `measure` で再計測する（§9.4 の U9）。

**波及範囲**: §1.2（絶対条件の明記）、§4.3.4（値の型フィルタ）、§4.3.5（残余語ガード・衝突検出の発火条件）、§4.3.7（判定木・reason_code の 3 群分類・永続化）、§4.5（confidence 表）、§5.5（I9 / I10）、§6.1（`quality.by_reason_code`）、§6.4（SC-06 P2 / P3）、§7.2（T-4 / T-8）、§8（M3 完了条件）、要件 §4.2 / FR-10 / NFR-05。

#### D6. V12 を値種別で緩和し、値の型フィルタを正式な解決手段とする（Issue #729）

**発端**: カタログ §2.2 は「単に『売上高』であれば `sales-amount-absolute` または `all-store-sales-yoy`（絶対額か率かでさらに分岐）」と定めているのに、改訂前の V12（別名が指標内で重複しない）が**その表現自体を禁じていた**。**§2.2 と V12 が両立していない**状態であり、`日本百貨店協会／3月の売上高3.2％増` のような率の値が `all-store-sales-yoy` に解決できず `no_metric_match` に落ちていた（実測 3 行。うち 2 行は日本百貨店協会の月次統計そのもので、本システムが最も取りたい種類のデータである）。

さらに深刻な点として、実装側が値の型フィルタを入れる前は **`3.2`（%）が単位 `jpy_oku` の指標に格納されていた**（率を億円として蓄積）。例外にならないため、評価データ（golden-60）が無ければ気づけない誤格納だった。

**確定内容**: V12 を次のとおり改訂する。

```
V12（改訂前）: 別名が 業態内 / 指標内で重複しない（異なる ID が同じ別名を持たない）

V12（改訂後）: 別名が 業態内 / 指標内で重複しない。
               ただし 値種別（ratio / absolute）が異なる指標間では同一別名を許す。
               値種別が同一の指標間では引き続き禁止する。
```

**根拠**: 曖昧性が**記事側に実在する**こと。`売上高3.2％増`（率）と `売上高1兆4505億円`（絶対額）で同じ語が両方を指すのは記事表記の性質であって、カタログの設計不備ではない。カタログ §2.2 が既に分岐条件を言語化しているので、それを V12 の例外条件として書き下ろす形になる。

**後半の禁止を維持することが重要**: 値種別が同一の指標間まで緩めると、値の型で絞っても一意に決まらず、「どの ID に寄せるか」が結局コード側の暗黙ルールになる。**NFR-09 が崩れる境界はこの 1 点**である。

**値の型フィルタの位置づけ**: 実装側が暫定で入れていた「値の型で候補を絞るフィルタ」は、この緩和により**設計上の正式な解決手段**になる（暫定回避ではない）。実装は §4.3.4 の `resolve_metric()` に閉じる。

**波及範囲**: §3.2（`metric_alias_index()` の戻り値が 1 別名 → 複数 ID）、§3.3（V12 の検査条件と説明）、§4.3.4（型フィルタ）、§4.5（代表例）、§7.2（T-4 / T-6）、要件 IF-02（列要件のスキーマ契約）。カタログ側の別名追加（`all-store-sales-yoy` に `売上高`）は小売ドメイン室が担当する。

### 9.4 未決事項

実装着手前に判断が必要な点、および v0.1 で意図的に対応しないと決めた点。

#### U2. period_type enum に 9 カ月累計（3Q）を表す値が無い — **v0.1 では意図的に非対応**

**事実**: 月範囲表現 41 件 [代表] のうち span 9 が 9 件、span 4 が 2 件。span 9 は 2 月決算企業の第 3 四半期累計（`6〜2月`、`7〜3月`、`9〜2月` の一部）であり意味は明確。

**矛盾の所在**: 要件 §4.2 の `period_type` enum は `month / quarter / half / fiscal_year / year` の 5 値。9 カ月累計を表す値が無い。`quarter` に入れると 3 カ月と混在し、SC-03 の「異なる period_type を混在させない」保護が効かなくなる。

**本設計での扱い（確定）**: span ∉ {3, 6, 12} は `ambiguous_period` として `unresolved` に退避する。一意 URL 406 件中 11 件（2.7%）の損失。**v0.1 では意図的に非対応とする**。enum を安易に増やして `quarter` に 3 カ月と 9 カ月を混在させるより、取りこぼしを可視化したまま残す方が誤読を生まないと判断した。`measure` の `ambiguous_period` 件数として常時観測できる。

**v0.2 への提案**: `period_type` に `cumulative` を追加し、`period_key` を `2025-06~2026-02` 形式のまま `period_span_months` フィールドで実際の月数を保持する。SC-03 では `cumulative` 系列を `quarter` / `half` と混在させない。

#### U5. `unresolved_rows.reason_code` に「intra-title の natural key 衝突」を表す値が無い — **D5 で解消**

**当初の記述**: 衝突ケース（`ファミレス／6月既存店すかいらーく1.7％増、サイゼリヤ9.7％増`）を confidence 0.30 に落として `low_confidence` に寄せているが、原因が「信頼度が低い」ではないため `measure` の分布から改善方針が読み取りにくい。v0.2 で `multi_subject_collision` の追加を提案していた。

**解消（D5 / Issue #728）**: 前提が誤っていた。この例では **observation が 1 件しか生成されず衝突は起きない**。複数主体併記は衝突検出ではなく **§4.3.5 の残余語ガード**が `company_disclosure` として捕捉する。enum は 9 値に拡張済みで、`measure` の分布からは残余語ガードの発火（`company_disclosure`）と値単位の退避（`no_metric_match_in_multi_value`）が直接読み取れる。**`multi_subject_collision` の追加は不要**であり、v0.2 への提案は取り下げる。

なお、この「複数主体」は D1 の `source_authority`（発表主体）とは別の問題である。前者は 1 記事に複数の**観測対象**（すかいらーく / サイゼリヤ）が並ぶケース、後者は同一観測対象に複数の**発表元**が存在するケースを指す。

#### U6. 連続記録表現のうち「前年割れ」以外を扱わない

カタログ §4.1 が定義するのは `〜カ月ぶりの前年割れ` のみ。実測では「ぶり」表現が 11 件 [行] / 10 件 [一意]、うち `〜カ月ぶりに前年割れ` の形は 3 件 [行] / 2 件 [一意] にとどまる。残りは `5カ月ぶりプラス` `8カ月ぶり伸び拡大` `2カ月連続でプラス` 等で、`streak_broken_months` の意味（連続記録が途切れた月数）とは方向が逆、または別の事象である。誤った意味付けを避けるため v0.1 では扱わない。カタログ §4.1 に `streak_continued_months` / `streak_positive_months` 相当の定義が追加された時点で対応する。

#### U7. チャートライブラリ（Chart.js vendoring と SVG 自前描画）

要件 §5.4 は Chart.js のインライン埋め込みを指定しており、本設計はそれに従う。ただし次のトレードオフがあるため記録しておく。

| 観点 | Chart.js インライン（要件の指定・本設計の採用） | インライン SVG の自前描画 |
|---|---|---|
| HTML サイズ | +205 KB | +0（描画コードは約 15 KB） |
| 印刷品質 | canvas はラスタライズされるため A4 横印刷で線が粗くなる（要件 §5.4 の「提案資料への転記」用途で不利） | ベクタのため印刷しても劣化しない |
| 実装量 | 小（設定を書くだけ） | 中（軸・目盛・凡例・ツールチップを自作、約 300 行） |
| アクセシビリティ | canvas は DOM に内容が無いため、併置するデータテーブルが必須（要件 §5.4 でも併置を指定済み） | SVG の `<title>` / `<desc>` で要素単位の説明を持てる |
| 第三者コードの持ち込み | MIT ライセンスの 205 KB をリポジトリに commit する | なし |

本設計では `renderLineChart(canvas, spec)` の 1 関数にライブラリ依存を封じ込めており、差し替えはこの関数の書き換えで完結する。M6 で印刷品質を実測し、提案資料の用途に耐えなければ差し替えを検討する。

#### U8. LLM 抽出の実行主体（要件 7-10 の引き継ぎ）

要件で未決のまま。本設計では `LlmClient` プロトコルにより実行主体の決定を `cli.py` の 1 行に閉じ込め、`--no-llm` で日次自動実行が LLM 抜きで完走することを保証した。決定を M5 まで遅らせても他の設計に波及しない状態にしてある。

#### U9. NFR-05（対象内行の抽出成功率 80% 以上）は **未達で確定** — 目標値の扱いを要判断

**確定値**: カタログへの指標別名追加（小売ドメイン室が実施済み）と §4.3.3 の主語位置ガードを反映した最終実測は **64/83 = 77.1%**。目標 80% に 2.9 ポイント届かない。付録 A のスクリプトで再現できる。

**この 77.1% は D5 / D6 を反映していない**（本節の以降の記述も同様）。D5 の残余語ガードは分子と分母をともに減らし、D6 の V12 緩和は 3 行を回収して分子を増やす。実装側の暫定実測は 56/83 = 67.5%（V12 緩和による回収を含まない時点）。**確定値は M3 の `measure` で再計測する。** D5 の確定内容 7 のとおり、この減少は受け入れる — **「正しく未達」であることの方が、「誤ったデータで達成に見える」ことより価値がある。** 数値の増減より、率を億円として蓄積していた誤格納（D6）と、個社の値が業態の観測値になっていた誤帰属（D5）が止まったことの方が重要である。

**分母に残る 19 件の内訳と回収可能性**:

| 分類 | 件数 | 性質 | 回収可能性 |
|---|---|---|---|
| `no_numeric` — タイトルに数値が無い | 4 | `令和8年2月度チェーンストア販売統計`、`コンビニエンスストア統計調査2月度`、`ホームセンター月次実績＝2026年3月度 / 6月度` | **構造的に回収不能**。要件 7-3 のとおり本文取得を行わない以上、タイトルに数値が無い記事からは観測値を作れない |
| `no_numeric` — 定性表現のみ | 2 | `チェーンストア販売、食品・衣料低迷で総額減`、`大手百貨店／4月売上高4社そろって増、免税売上増が貢献` | **回収可能**。カタログ §4.1 の `sign_only` 経路に載せる。ただし value は null のままなので NFR-05 の分子に数えるかは定義次第（§4.3.7 の「抽出成功」の定義を要確定） |
| `no_numeric` / `no_metric_match` — ランキング記事 | 5 | `百貨店決算ランキング2026`、`食品スーパー決算ランキング2026 "1兆円クラブ"` 等 | **回収しない**（小売ドメイン室の判断）。ランキング見出しの慣用句であり特定期間の実績値ではない。ただし業態名が主語位置にあるため現状は分母に残る。**分母から外すべきかは要判断**（外せば 64/78 = 82.1% となり達成するが、これは数値操作に見えるため本書からは提案しない） |
| `no_numeric` — 統計記事でない | 1 | `週刊コンビニエンスストアニュース セブンカフェ…` | 上と同じ。分母に残っている |
| `no_metric_match` | 1 | `3月の百貨店売上高、全社増収＝免税売り上げは5カ月ぶりプラス` | **回収可能**。定性表現（`全社増収`）と指標の結び付けが必要 |
| `no_segment_match` — カタログの業態別名不足 | 3 | `6月消費者物価、1.6％上昇`（`消費者物価` が `cpi` の別名に無い）、`4月都内物価` / `6月都内物価`（東京都区部 CPI） | **カタログ別名追加で回収可能**。ただし後述のとおり別名追加だけでは分子に入らない |
| `no_segment_match` — カタログに業態行が無い | 1 | `3月消費支出、2.9％減―総務省`（総務省 家計調査） | 新規 segment の追加が必要。小売業態統計ではないため追加しない選択もある |
| `no_segment_match` — 小売統計でない | 2 | `農水省・食品等取引実態調査`、`適正原価は計算式で算出へ、国交省が第1回検討会` | 実質 out_of_scope だが `AUTHORITY_MARKER` に一致するため分母に残る |

**80% への到達可能性（実測）**:

| 施策 | 実測 | 備考 |
|---|---|---|
| 確定値 | 64/83 = **77.1%** | — |
| + `cpi` に別名 `消費者物価` / `都内物価` を追加 | 64/84 = 76.2% | **分子が増えない**。業態は解決するが、値トークンの左窓が節境界（`6月消費者物価` `、` `1.6％上昇`）で切れて指標に届かないため `no_metric_match` に移るだけ |
| + 左窓の節境界を跨ぐ後方探索を許可（低 confidence で） | 66/84 = **78.6%** | **目標に届かない**。しかも左窓の距離制限を完全に撤廃した上限も同じ 66/84 = 78.6% であり、これがこの施策単独での天井である（付録 A のスクリプトで再現できる）。**誤った指標を拾うリスクだけが上がって目標には届かない**ため、この施策単独では採らない |

**訂正**: 本表は当初この行を `69/84 = 82.1%` と記載していたが、付録 A のスクリプトで再現できず**誤りだった**。左窓を緩めても回収できない 4 件（`4月都内物価` / `6月都内物価` — `都内物価` は業態別名を足しても指標別名が無い、および ランキング記事 2 件）が残るため、上限が 66 件で頭打ちになる。

**したがって、上表のどの施策も単独では 80% に届かない。** 到達には (a) 左窓の緩和に加えて (b) 定性表現の `sign_only` を分子に数えるかの定義確定、(c) ランキング記事を分母から外すかの合意（U9 の内訳表参照）を**組み合わせる必要がある**。いずれも M3 の `measure` で誤抽出率と併せて検証してからでなければ採用できない。現時点で達成を宣言しない。

**目標値 80% 自体の見解**: **引き下げは提案しないが、判断材料は当初より弱い。** 上表の訂正により、単独で 80% を超える施策は実測では存在しないことが分かった（最良でも 78.6%）。それでも引き下げを提案しないのは、(a)(b)(c) を組み合わせた到達可能性がまだ潰れていないこと、および構造的に回収不能な件数が小さいことによる。未達の主因は要件側の目標設定ではなく、(a) 左窓の節境界ルールが厳しすぎること、(b) 定性表現を指標に結び付けていないこと、(c) 分母にランキング記事等が混ざっていることの 3 点であり、いずれも実装・カタログ側で対処できる。**構造的に回収不能なのは 4 件（タイトルに数値が無い記事）のみで、分母 83 の 4.8% にとどまる**。目標値を下げるとしたら、M3 で (a)(b)(c) をすべて実施してなお届かないことが分かってからであり、その判断は要件のオーナーが行う。

**M3 での確定事項**: (1) 上表の 3 施策を実装して `measure` で再計測する、(2) 「抽出成功」の定義に `sign_only` のみの観測を含めるかを確定する、(3) ランキング記事を分母から外すかを小売ドメイン室と合意する。**それまで NFR-05 は未達として扱う。**

#### U10. 1 記事に複数主体の値が並ぶ場合、片方だけが業態に誤帰属する — **§9.3 の D5 で確定・解消**

**本項は未決ではなくなった。** Issue #728（M3 実装での再現報告）を受け、対処方針は §9.3 の **D5** として確定している。以下は経緯と実測の記録として残す。**「v0.1 での対処」以降に書かれた案（confidence 0.30 に落として LLM へ回す）は D5 に置き換わっており、実装の根拠にしないこと。** 確定した実装規則は §4.3.5 の残余語ガードである。

**事実**: §4.3.5 の intra-title 衝突検出は「同一 natural key が 2 つ以上生成された場合」に発火する設計だが、実データでは**衝突が 0 件**だった。代わりに、**2 つ目以降の値トークンが指標に解決できず黙って捨てられ、1 つ目の値だけが業態の観測値になる**パターンが **30 件**見つかった（付録 A のスクリプトで再現できる）。

```
  ドラッグストア／2月既存店売上ツルハ4.0%増、コスモス薬品7.0%増
    値① 4.0%増  左窓「2月既存店売上ツルハ」→ 既存店売上 に一致 → 採用
    値② 7.0%増  左窓「、コスモス薬品」    → 指標別名なし   → 黙って破棄
    結果: (drugstore, existing-store-sales-yoy, existing_store, 2026-02) = +4.0
          ＝ ツルハ 1 社の値が業態全体の値として confidence 0.95 で格納される
```

**30 件の業態別内訳**（付録 A.3 の出力。括弧内は「未解決トークンが `%` かつ行内に `%` が 2 つ以上」＝同一指標の値が並んでいる疑いが強いもの）:

| 業態 | 件数 | うち同一単位 |
|---|---|---|
| `supermarket` | 7 | 4 |
| `department-store` | 6 | 3 |
| `drugstore` | 5 | 4 |
| `family-restaurant` | 4 | 4 |
| `meti-commerce-dynamics` | 4 | 0 |
| `electronics-retailer` | 3 | 2 |
| `ec-platform` | 1 | 0 |
| **計** | **30** | **17** |

**30 件は 2 種類に分かれる**。

**(1) 複数主体併記 — 13 件（要対応）**。同一単位 17 件の内訳は `ドラッグストア／…ツルハ／コスモス薬品`（4 件）、`スーパーマーケット／…ライフ／ヤオコー`（4 件）、`ファミレス／…すかいらーく／サイゼリヤ`（4 件）、`大手百貨店／…三越伊勢丹／H2O`（1 件）の **13 件**と、後述の誤検出 4 件である。この 13 件が本項の対象で、**例外も未解決行も出ないため §4.3.2 の金額バグと同じ silent accumulation** になる。

**(2) 検出条件の誤検出 — 17 件**。同一単位 17 件のうち残り 4 件は `家電大型専門店／…生活家電が15.8％増`（2 件。主体名でなく**商品カテゴリ**の内訳）と `日本百貨店協会／…インバウンド29.8％増・国内顧客0.2％減`（2 件。**FR-11 の複数指標**であり、カタログ別名が `インバウンド売上` `国内顧客` と完全一致しないために未解決になっているだけ）。残る 13 件（= 30 − 17。同一単位でないもの。要対応の 13 件とは別集合）は、`経済産業省／…小売業販売額0.2％減の12兆1550億円` のように**同一量を率と金額で言い換えた**もので実害がない。

つまり**検出条件は要対応 13 件に対して 30 件を拾う（誤検出 17 件）**。この比率が、下記の「M3 で誤検出率を測ってから閾値を決める」の根拠である。

**当初案（採用しない）**: 衝突検出の条件を「同一 natural key の重複」から「解決した指標数 < 値トークン数 かつ 未解決の値トークンの左窓に 2 文字以上の語がある」に拡張し、該当記事の全 observation を confidence 0.30 に落として LLM フォールバックへ回す案。**却下した**。理由は 2 点。(1) `家電大型専門店／…生活家電が15.8％増` のような**業態内の内訳**まで巻き込み、本来取るべきデータを落とす。(2) LLM が返すべき正解が「対象外」である以上、判定は決定論的に下せる。LLM 呼び出しは非決定性とコストを持ち込むだけで精度は上がらない。

**確定した対処（D5）**: 検出条件は**解決できなかった値トークンの左窓**ではなく、**解決できた値の左窓に残る残余語**で判定する。これにより (a) 個社の並記と (b) 業態内の内訳が分離でき、(b) の 1 件目を正当な観測値として保持できる。上表の「誤検出 17 件」のうち商品カテゴリ 2 件と FR-11 の複数指標 2 件は、この判定基準では**行を落とさず値単位の退避**（`no_metric_match_in_multi_value`）になる。「同一量を率と金額で言い換えた」13 件も同様に値単位の退避となり、silent loss ではなく可視化された退避に変わる（§4.3.5 の「既知の副作用」）。

**M3 で確認する事項**（未決ではなく検証項目）: 残余語ガードの発火件数と落とした行の原文を `measure` に出力し、(a) の除外が過剰でないことを目視で確認する。`RESIDUE_MIN_LEN`（現行 2 文字）の妥当性もここで判断する。

---

## 10. 付録 A: 実測値の再現スクリプト

本書に「実測」と記した数値は、すべて下記スクリプトで再現できる。**読み手が検算できない実測値は根拠にならない**という反省から、v0.1 のレビュー指摘を受けて追加した。実装時は `scripts/retail-stats-tracker/tests/measure_evidence.py` として配置し、数値を更新する際は必ずこれを実行して出力を貼り直す。

### A.1 集計基準

同じ対象でも基準により値が大きく変わるため、本書の実測値は必ずどれかを併記する。

| 記法 | 基準 | 母数（計測日 2026-07-26） |
|---|---|---|
| **[行]** | 決算・統計章のデータ行。同一記事が N 日掲載されれば N 回数える | 595 |
| **[一意]** | 一意 URL。いずれかの title variant が該当すれば 1 件 | 406 |
| **[代表]** | 一意 URL の代表 variant のみ（§4.7 の選択規則） | 406 |

走査対象は原則 **記事タイトルのみ**（要約・ソース名を含めない）。含める場合はその旨を明記する。

### A.2 スクリプト

**実行場所に依存しない**。リポジトリルートを `.git` / `.claude-plugin` の存在で上位に辿って解決するため、cwd がどこでも（また §10 冒頭の指示どおり `scripts/retail-stats-tracker/tests/measure_evidence.py` に配置しても）動く。この解決方法は実装設計 §2.4 の `config.py` と同じ考え方である。スクリプトをリポジトリ外へ切り出して実行する場合のみ、環境変数 `RS_REPO_ROOT` でルートを明示する。

```python
#!/usr/bin/env python3
"""設計書の実測値を再現する。python3 measure_evidence.py で全項目を出力。"""
import os, re, unicodedata, collections
from pathlib import Path

def _find_repo_root() -> Path:
    """.git / .claude-plugin を上位に辿ってリポジトリルートを解決する（§2.4 と同方式）。
    cwd 起点 → スクリプト位置起点の順に探す。cwd 依存で FileNotFoundError にしないため。"""
    if os.environ.get("RS_REPO_ROOT"):
        return Path(os.environ["RS_REPO_ROOT"]).resolve()
    starts = [Path.cwd().resolve()]
    if "__file__" in globals():
        starts.append(Path(__file__).resolve().parent)
    for start in starts:
        for d in (start, *start.parents):
            if (d / ".git").exists() or (d / ".claude-plugin").exists():
                return d
    raise SystemExit(
        "リポジトリルートを解決できません。リポジトリ内で実行するか "
        "RS_REPO_ROOT=/path/to/repo を指定してください。")

REPO_ROOT = _find_repo_root()
ORG = REPO_ROOT / ".companies/domain-tech-collection"
DIG = ORG / "docs/daily-digest"
CAT = ORG / "docs/retail-domain/retail-monthly-kpi-catalog.md"

def scan():
    """FR-01 / FR-02 の規則で決算・統計章のデータ行を抽出する。"""
    rows, files = [], sorted(DIG.glob("*.md"))
    with_sec, with_tbl = set(), set()
    for f in files:
        inside = False
        for ln in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^###\s+(.*)$", ln.strip())
            if m:                                   # 見出しテキストで判定（章番号では判定しない）
                inside = "決算・統計" in m.group(1)
                if inside:
                    with_sec.add(f.stem)
                continue
            if re.match(r"^##\s", ln.strip()):      # 章の切り替わりで打ち切り
                inside = False
                continue
            if inside and ln.strip().startswith("|"):
                with_tbl.add(f.stem)
                if re.match(r"^\|\s*[0-9]+\s*\|", ln):
                    mm = re.search(r"\[(.+?)\]\((https?://[^)]+)\)", ln)
                    rows.append((f.stem,
                                 mm.group(1) if mm else None,
                                 mm.group(2) if mm else None, ln))
    return files, rows, with_sec, with_tbl

FILES, ROWS, WSEC, WTBL = scan()
TITLES = [r[1] for r in ROWS if r[1]]
BYURL = collections.defaultdict(list)
for _, t, u, _ in ROWS:
    if u:
        BYURL[u].append(t)

def pick(variants):
    """§4.7 の代表 variant 選択（数値トークン数 → 長さ → 辞書順）。"""
    return max(variants, key=lambda t: (
        len(re.findall(r"[0-9]+(?:\.[0-9]+)?[%％億兆]", t)), len(t), t))

REPS = {u: pick(v) for u, v in BYURL.items()}

def count(pattern):
    """[行] / [一意] / [代表] / 延べ出現数 を返す。"""
    rx = re.compile(pattern)
    return (sum(1 for t in TITLES if rx.search(t)),
            sum(1 for vs in BYURL.values() if any(rx.search(t) for t in vs)),
            sum(1 for t in REPS.values() if rx.search(t)),
            sum(len(rx.findall(t)) for t in TITLES))

ITEMS = [
    ("全角 ％", r"％"), ("半角 %", r"%"), ("全角数字 [０-９]", r"[０-９]"),
    ("カ月", r"カ月"), ("ヶ月", r"ヶ月"), ("ヵ月", r"ヵ月"), ("か月", r"か月"),
    ("〜 (U+301C)", r"〜"), ("～ (U+FF5E)", r"～"),
    ("- (ASCII hyphen)", r"(?<=[0-9])-(?=[0-9])"),
    ("月範囲 N〜M月", r"[0-9]{1,2}\s*[〜～~-]\s*[0-9]{1,2}\s*月"),
    ("数値中の空白", r"[0-9]\s+[0-9]|[0-9]\s+[月%％期年億兆万円]"),
    ("桁区切りカンマ", r"[0-9],[0-9]{3}(?![0-9])"),
    ("「ぶり」", r"ぶり"),
    ("「ぶり」かつ前年割れ", r"[0-9]+カ月ぶり(?:に|の)?(?:前年割れ|前年同月割れ)"),
    ("横ばい", r"横ばい"), ("経産省/経済産業省", r"経産省|経済産業省"),
    ("割増・割減", r"[0-9]+(?:\.[0-9]+)?割[増減]"), ("半減", r"半減"),
]

# === §4.2 normalize（span 分布・スコープ分類はこれを通すことが前提） ==========
_KA_MONTH_RE = re.compile(r"(?<=[0-9])[カヶヵか](?=月)")
_SP_IN_NUM_RE = re.compile(r"(?<=[0-9])\s+(?=[0-9])")
_SP_BEFORE_UNIT_RE = re.compile(r"(?<=[0-9])\s+(?=[月%期年日度億兆万円])")
_SP_BEFORE_PCT_RE = re.compile(r"\s+(?=%)")
_THOUSAND_SEP_RE = re.compile(r"(?<=[0-9]),(?=[0-9]{3}(?![0-9]))")

def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("〜", "~").replace("～", "~")
    s = s.replace("－", "-").replace("―", "-").replace("–", "-")
    s = _KA_MONTH_RE.sub("カ", s)
    s = _SP_IN_NUM_RE.sub("", s)
    s = _SP_BEFORE_UNIT_RE.sub("", s)
    s = _SP_BEFORE_PCT_RE.sub("", s)
    return _THOUSAND_SEP_RE.sub("", s)

NORM = [normalize(t) for t in REPS.values()]        # [代表] 406 件

# === カタログローダ（§3.1。§1.1 業態一覧 / §2.1 KPI 一覧の 2 表のみを読む） ====
def load_catalog():
    lines = CAT.read_text(encoding="utf-8").splitlines()
    h2 = [i + 1 for i, l in enumerate(lines) if l.startswith("## ")]
    segs, mets, sub = {}, {}, None
    for l in lines:
        if l.startswith("#"):
            m = re.match(r"^###\s+([0-9.]+)", l)
            sub = m.group(1) if m else (None if l.startswith("## ") else sub)
            continue
        if not l.startswith("|") or sub not in ("1.1", "2.1"):
            continue
        c = [x.strip().strip("`").strip() for x in l.strip().strip("|").split("|")]
        if len(c) < 3 or c[0] in ("segment_id", "metric_id") or set(c[0]) <= set("-: "):
            continue                                 # ヘッダ行・区切り行を除く
        aliases = [c[1]] + [a.strip() for a in c[2].split(",") if a.strip()]  # 名称 + 別名
        (segs if sub == "1.1" else mets)[c[0]] = aliases
    return h2, segs, mets

CAT_H2, SEGS, METS = load_catalog()

def alias_index(table, extra=None, drop=None):
    """別名 → ID の索引を長さ降順で返す（§4.3.3 / §4.3.4 が要求する順序）。"""
    out = {}
    for id_, aliases in table.items():
        for a in aliases:
            if drop and (id_, a) in drop:
                continue
            out.setdefault(a, id_)
    for id_, a in (extra or []):
        out.setdefault(a, id_)
    return sorted(out.items(), key=lambda kv: (-len(kv[0]), kv[0]))

SEG_IDX, MET_IDX = alias_index(SEGS), alias_index(METS)

# === §4.4.2 月範囲の span 分布 ==============================================
P_RANGE = re.compile(r"(?<![0-9])(?P<m1>1[0-2]|[1-9])\s*[~-]\s*(?P<m2>1[0-2]|[1-9])月(?P<ki>期)?")

def span_dist():
    d = collections.Counter()
    for n in NORM:
        m = P_RANGE.search(n)
        if m:
            d[(int(m.group("m2")) - int(m.group("m1"))) % 12 + 1] += 1
    return d

# === §4.3.3 / §4.3.4 / §4.3.7 スコープ分類 ==================================
VALUE_PCT_RE = re.compile(r"(?P<num>[0-9]+(?:\.[0-9]+)?)%")
_JPY_NUM = r"[0-9]+(?:\.[0-9]+)?"
VALUE_JPY_RE = re.compile(
    rf"(?<![0-9.])(?:(?P<cho>{_JPY_NUM})兆)?(?:(?P<oku>{_JPY_NUM})億)?"
    rf"(?:(?P<man>{_JPY_NUM})万)?円")
WARI_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?割[増減]")
QUALITATIVE_RE = re.compile(r"増収|減収|増益|減益|横ばい|半減")
AUTHORITY_HEAD_RE = re.compile(
    r"協会|連合会|組合|生協連|経済産業省|経産省|総務省|農水省|農林水産省|財務省|厚労省|国交省")
AUTHORITY_MARKER = re.compile(
    r"協会|連合会|組合|経済産業省|経産省|総務省|農水省|農林水産省|財務省|厚労省|国交省|統計|白書")
STAT_VOCAB = re.compile(
    r"既存店|売上高|売上|販売額|客数|客単価|営業利益|営業収益|供給高|物価|市場規模|店舗数")
CLAUSE_SEP_RE = re.compile(r"[、。・/:：]")
METRIC_WINDOW_FAR = 25

def _subject_head(n):
    if "/" in n:
        return n.split("/", 1)[0]
    if "、" in n:
        return n.split("、", 1)[0]
    return n

def resolve_segment(n, seg_idx, guard=True):
    if not guard:                                    # ガード導入前（推移の再現用）
        return next((s for a, s in seg_idx if a in n), None)
    head = _subject_head(n)
    hit = next((s for a, s in seg_idx if a in head), None)
    if hit:
        return hit
    if AUTHORITY_HEAD_RE.search(head):               # 主語が発表主体名の場合の例外
        return next((s for a, s in seg_idx if a in n), None)
    return None

def value_spans(n):
    sp = [(m.start(), m.end()) for m in VALUE_PCT_RE.finditer(n)]
    sp += [(m.start(), m.end()) for m in VALUE_JPY_RE.finditer(n)
           if m.group("cho") or m.group("oku") or m.group("man")]
    sp += [(m.start(), m.end()) for m in WARI_RE.finditer(n)]
    out = []
    for s, e in sorted(sp):
        if not out or s >= out[-1][1]:               # 重なりを畳む
            out.append((s, e))
    return out

def _window(n, start, stop, cross_clause):
    """左窓。既定は直前の節区切りで切る。cross_clause=True で節境界を跨ぐ。"""
    if cross_clause:
        return n[start:stop]
    last = start
    for m in CLAUSE_SEP_RE.finditer(n, start, stop):
        last = m.end()
    return n[last:stop]

def resolve_metric(window, met_idx):
    for a, mid in met_idx:                           # 長さ降順・右端優先
        i = window.rfind(a)
        if i >= 0 and len(window) - (i + len(a)) <= METRIC_WINDOW_FAR:
            return mid
    return None

def classify(n, seg_idx, met_idx, guard=True, metric_check=True, cross_clause=False):
    """§4.3.7 の判定木。戻り値は 6 分類のいずれか。"""
    seg = resolve_segment(n, seg_idx, guard)
    vs = value_spans(n)
    if seg:
        if not vs:                                   # 定性表現のみは指標に結び付かない（U9）
            return "no_metric_match" if QUALITATIVE_RE.search(n) else "no_numeric"
        if not metric_check:
            return "ok"
        prev = 0
        for s, e in vs:
            if resolve_metric(_window(n, prev, s, cross_clause), met_idx):
                return "ok"
            prev = e
        return "no_metric_match"
    if AUTHORITY_MARKER.search(n):                   # 順序が要点（§4.3.7）
        return "no_segment_match"
    if STAT_VOCAB.search(n) and (vs or QUALITATIVE_RE.search(n)):
        return "oos_company"
    return "oos_nonstat"

IN_SCOPE = ("ok", "no_metric_match", "no_numeric", "no_segment_match")
LABELS = [("ok", "対象内・抽出成功"), ("no_metric_match", "no_metric_match"),
          ("no_numeric", "no_numeric"), ("no_segment_match", "no_segment_match"),
          ("oos_company", "out_of_scope 個社"), ("oos_nonstat", "out_of_scope 非統計")]

def measure(seg_idx=None, met_idx=None, **kw):
    c = collections.Counter(classify(n, seg_idx or SEG_IDX, met_idx or MET_IDX, **kw)
                            for n in NORM)
    den = sum(c[k] for k in IN_SCOPE)
    return c, c["ok"], den, c["ok"] / den * 100

# 推移の再現に使う差分（カタログ指標別名 3 種 / cpi 業態別名 2 種）
ADDED_METRIC_ALIASES = {("all-store-sales-yoy", "外食売上"),
                        ("all-store-sales-yoy", "チェーンストア販売"),
                        ("ec-market-size-yoy", "ECプラットフォーム市場規模")}
MET_IDX_BEFORE = alias_index(METS, drop=ADDED_METRIC_ALIASES)
SEG_IDX_CPI = alias_index(SEGS, extra=[("cpi", "消費者物価"), ("cpi", "都内物価")])

# === §9.4 U10 値トークンの黙殺（silent accumulation）の検出 ==================
_NOISE_RE = re.compile(r"[0-9\s、。・/:：%兆億万円()「」『』…=＝\-~]")

def u10_hits():
    """U10 の検出条件をそのまま実装する。
    「業態が解決でき、解決した指標数 < 値トークン数、かつ未解決の値トークンの
      左窓に 2 文字以上の語がある」行を返す。
    1 つも指標が解決しない行（＝観測値が 1 件も作られない行）は、黙って捨てられる
    という現象が起きないため対象外とする。"""
    hits = []
    for n in NORM:
        seg = resolve_segment(n, SEG_IDX)
        vs = value_spans(n)
        if not seg or len(vs) < 2:
            continue
        prev, solved, unresolved = 0, 0, []
        for s, e in vs:
            if resolve_metric(_window(n, prev, s, False), MET_IDX):
                solved += 1
            else:
                unresolved.append((_window(n, prev, s, False), n[s:e]))
            prev = e
        if solved == 0 or solved == len(vs):
            continue
        if any(len(_NOISE_RE.sub("", w)) >= 2 for w, _ in unresolved):
            # 未解決トークンが % で、行内に % が 2 つ以上 = 同一指標の値が
            # 並んでいる疑いが強い（金額と率の言い換えを除外する）
            same_unit = (any("%" in t for _, t in unresolved)
                         and len(re.findall(r"[0-9.]+%", n)) >= 2)
            hits.append((seg, same_unit, n))
    return hits

STAGES = [
    ("指標解決を検査",           dict(guard=False, met_idx=MET_IDX_BEFORE)),
    ("+ カタログ指標別名の追加",   dict(guard=False)),
    ("+ 主語位置ガード（確定値）", dict()),
    ("+ cpi 別名追加",          dict(seg_idx=SEG_IDX_CPI)),
    ("+ 左窓の節境界を跨ぐ後方探索", dict(seg_idx=SEG_IDX_CPI, cross_clause=True)),
]

if __name__ == "__main__":
    print(f"ファイル {len(FILES)} / 決算・統計章あり {len(WSEC)} / 表あり {len(WTBL)}")
    print(f"データ行[行] {len(ROWS)} / リンク抽出成功 {len(TITLES)} / 一意 URL {len(BYURL)}")
    print(f"{'項目':<24}{'[行]':>7}{'[一意]':>8}{'[代表]':>8}{'出現数':>8}")
    for label, pat in ITEMS:
        print(f"{label:<24}" + "".join(f"{v:>8}" for v in count(pat)))

    d = span_dist()
    print("\n-- 月範囲 span 分布 [代表]（§4.2 normalize 適用後）--")
    print("   " + " / ".join(f"span={k}: {d[k]}" for k in sorted(d)))
    print(f"   合計 {sum(d.values())} / 解決可(3,6,12) "
          f"{sum(v for k, v in d.items() if k in (3, 6, 12))} / "
          f"ambiguous {sum(v for k, v in d.items() if k not in (3, 6, 12))}")

    c, num, den, rate = measure()
    print("\n-- スコープ分類 [代表]（§4.3.7 の判定木・§4.3.3 主語位置ガード適用後）--")
    for key, label in LABELS:
        print(f"   {label:<18}{c[key]:>4}  {c[key] / len(NORM) * 100:4.1f}%")
    print(f"   NFR-05 = {num}/{den} = {rate:.1f}%（目標 80% / {'達成' if rate >= 80 else '未達'}）")
    resolved = sum(c[k] for k in ("ok", "no_metric_match", "no_numeric"))
    print(f"   業態解決率 = {resolved}/{len(NORM)} = {resolved / len(NORM) * 100:.1f}%")

    print("\n-- 段階別の推移 --")
    for label, kw in STAGES:
        _, n_, d_, r_ = measure(**kw)
        print(f"   {label:<26}{n_}/{d_} = {r_:.1f}%")

    hits = u10_hits()
    same = [h for h in hits if h[1]]
    print("\n-- U10 値トークンの黙殺 [代表]（§9.4 U10 の検出条件）--")
    print(f"   検出条件に該当            {len(hits)}")
    print(f"   うち未解決トークンが % かつ行内に % が 2 つ以上   {len(same)}")
    for seg, c in sorted(collections.Counter(s for s, _, _ in hits).items(),
                         key=lambda kv: (-kv[1], kv[0])):
        print(f"     {seg:<24}{c:>3}"
              f"（うち同一単位 {sum(1 for s, u, _ in hits if s == seg and u)}）")

    print("\n-- カタログ H2 見出しの行番号 --")
    print("   " + " / ".join(f"L{n}" for n in CAT_H2))
```

**この 1 本で本書の実測値をすべて再現できる**（`normalize()` とカタログローダを内蔵しているため、`retail_stats` パッケージの実装を待たずに検算できる）。**正規化を通さない再集計とは結果がずれる**点に注意（§4.4.2 の注記を参照）。

**本スクリプトの対象外が 1 項目だけある**。§4.3.7 の推移表の第 1 行「初版の申告（誤り） 75/90 = 83.3%」は、v0.1 初版が**指標の解決可否を検査しない別手順**で算出して申告した値そのものの引用であり、現行の判定木を持つ本スクリプトでは再現しない（同条件＝ガードなし・指標検査なしで走らせると 71/89 = 79.8% になる）。**撤回済みの誤った申告値を歴史的経緯として残しているものなので、再現対象に含めない。** 本書がこの値を根拠に使っている箇所は無い。

### A.3 実行結果（計測日 2026-07-26）

```
ファイル 102 / 決算・統計章あり 93 / 表あり 89
データ行[行] 595 / リンク抽出成功 595 / 一意 URL 406
項目                          [行]    [一意]    [代表]     出現数
全角 ％                         153     127     123     217
半角 %                         172     129      94     228
全角数字 [０-９]                     0       0       0       0
カ月                            11      10      10      11
ヶ月                             0       0       0       0
ヵ月                             1       1       1       1
か月                             0       0       0       0
〜 (U+301C)                    63      39      37      63
～ (U+FF5E)                     4       3       3       4
- (ASCII hyphen)               1       1       1       1
月範囲 N〜M月                      68      41      41      68
数値中の空白                         6       6       6       9
桁区切りカンマ                        1       1       1       1
「ぶり」                          11      10      10      11
「ぶり」かつ前年割れ                     3       2       2       3
横ばい                            3       1       1       3
経産省/経済産業省                     20      19      19      20
割増・割減                          1       1       1       1
半減                             1       1       1       1

-- 月範囲 span 分布 [代表]（§4.2 normalize 適用後）--
   span=3: 23 / span=4: 2 / span=6: 7 / span=9: 9
   合計 41 / 解決可(3,6,12) 30 / ambiguous 11

-- スコープ分類 [代表]（§4.3.7 の判定木・§4.3.3 主語位置ガード適用後）--
   対象内・抽出成功            64  15.8%
   no_metric_match      3   0.7%
   no_numeric          10   2.5%
   no_segment_match     6   1.5%
   out_of_scope 個社    154  37.9%
   out_of_scope 非統計   169  41.6%
   NFR-05 = 64/83 = 77.1%（目標 80% / 未達）
   業態解決率 = 77/406 = 19.0%

-- 段階別の推移 --
   指標解決を検査                   62/89 = 69.7%
   + カタログ指標別名の追加             67/89 = 75.3%
   + 主語位置ガード（確定値）            64/83 = 77.1%
   + cpi 別名追加                64/84 = 76.2%
   + 左窓の節境界を跨ぐ後方探索           66/84 = 78.6%

-- U10 値トークンの黙殺 [代表]（§9.4 U10 の検出条件）--
   検出条件に該当            30
   うち未解決トークンが % かつ行内に % が 2 つ以上   17
     supermarket               7（うち同一単位 4）
     department-store          6（うち同一単位 3）
     drugstore                 5（うち同一単位 4）
     family-restaurant         4（うち同一単位 4）
     meti-commerce-dynamics    4（うち同一単位 0）
     electronics-retailer      3（うち同一単位 2）
     ec-platform               1（うち同一単位 0）

-- カタログ H2 見出しの行番号 --
   L12 / L20 / L84 / L138 / L163 / L234
```

### A.4 v0.1 初版からの訂正一覧

L2 レビューで再現できなかった実測値を、上記スクリプトの出力に合わせて訂正した。**規則そのものの妥当性はいずれも変わらない**が、根拠として掲げた数値の信頼度を回復するために全件を洗い直した。

| 箇所 | 初版の記載 | 訂正後 | 誤りの原因 |
|---|---|---|---|
| §4.2 全角％ / 半角% | 115 件 / 102 件 | [一意] 127 / 129、[代表] 123 / 94、[行] 153 / 172 | 集計基準を明示していなかった。どの基準とも一致しない値だった |
| §4.2 カ月表記 | カ月 24 / ヶ月 1 / ヵ月 1 | カ月 11 / ヶ月 **0** / ヵ月 1 [行] | 要約を含む行全体で数えたうえ、さらに過大だった |
| §4.2 月範囲表現 | 97 件 | 68 [行] / 41 [一意] / 41 [代表] | 同上。§4.4.2 の「41 件」が正しく、書内で矛盾していた |
| §4.3.5 「ぶり」 | 21 件・前年割れ 5 件 | 11 / 3 [行]、10 / 2 [一意] | 同上 |
| §3.1 カタログ見出し行 | KPI 定義 = 行 64 | 行 84 | カタログ改訂で位置が動いたのを追随していなかった |
| §4.3.2 金額換算 | 6 パターン全て正常 | 旧実装は 16 中 **8 パターン**で誤値（旧版 8/16 合格。§4.3.2 の表） | カンマ除去の `\b` バグと小数非対応を検証していなかった |
| §4.3.7 NFR-05 | 75/90 = 83.3%（達成） | 64/83 = **77.1%（未達）** | 指標の解決可否を検査せず、数値の有無だけで「抽出可能」と数えていた。訂正後にカタログ指標別名の追加（+5）と §4.3.3 主語位置ガード（誤って成功に数えていた 3 件を除外）を反映した確定値 |
| §4.3.3 業態の解決 | 別名がタイトル中のどこでも一致してよい | 主語位置での一致を要求（例外: 主語が発表主体名の場合） | 汎用別名（`外食` `百貨店` 等）が個社決算記事の本文に一致し、個社の値を業態の観測値として格納していた（実測 7 件、うち 3 件は抽出成功に計上） |
| §4.4.2 span 分布 | 合計 41（基準の記載なし） | 合計 41 [代表]、ただし `normalize()` 適用が前提 | 正規化の有無で 40 / 41 が変わる点を明示していなかった |

### A.5 v0.1 → v0.1.1 の訂正一覧（M3 実装からの報告）

Issue #728 / #729 で報告された設計の内部不整合に対する訂正。**いずれも実装が設計の条文どおりに書かれた結果として発見されたもの**であり、コード側での回避は行われていない。確定内容は §9.3 の D5 / D6。

| 箇所 | 初版の記載 | 訂正後 | 誤りの原因 |
|---|---|---|---|
| §4.3.5 衝突検出 | `ファミレス／6月既存店すかいらーく1.7％増、サイゼリヤ9.7％増` で natural key が衝突し 0.30 に固定される | **衝突しない**。§4.3.1 の左窓規則では 2 件目の左窓が `サイゼリヤ` になり指標が解決せず、observation は 1 件しか生成されない。残余語ガード（新設）が `company_disclosure` として捕捉する | 左窓規則（§4.3.1）と衝突検出（§4.3.5）を突き合わせていなかった。安全網が構造的に発火しない状態だった（実測 16 行） |
| §4.3.5 / FR-10 | 未解決の値トークンの扱いが未定義 | 値トークンは observation か `unresolved` に**必ず着地する**。§5.5 の I10 で機械的に検査する | 2 件目以降の値トークンが指標未解決のまま黙って捨てられる経路が残っていた（silent loss。FR-10 違反） |
| §4.3.7 reason_code | enum 7 値 | **9 値**（`company_disclosure` / `no_metric_match_in_multi_value` を追加） | 個社並記の行と、業態内の内訳の 2 件目とを区別する分類が無かった |
| §3.3 V12 | 別名が指標内で重複しない | 値種別が異なる指標間では同一別名を許す（同一値種別では引き続き禁止） | カタログ §2.2 の「絶対額か率かでさらに分岐」を V12 が禁じており、**§2.2 と V12 が両立していなかった**。率の値 3 行が `no_metric_match` に落ちていた |
| §4.3.4 指標の解決 | 別名の最長一致のみ | **値の型（ratio / absolute）で候補を絞ってから**最長一致 | 型フィルタが無い状態では `3.2`（%）が単位 `jpy_oku` の指標に格納されうる（率を億円として蓄積）。例外にならないため評価データ無しでは検知できなかった |
| §9.4 U5 | v0.2 で `multi_subject_collision` の追加を提案 | **提案を取り下げ**。前提（衝突が起きる）が誤りだった | 上記 §4.3.5 と同じ原因 |
| §9.4 U10 | 未決（検出条件の閾値と LLM 送りの是非） | **D5 で確定・解消** | — |

---

## 11. 参照

| 文書 | 役割 |
|---|---|
| [小売月次統計トラッカー 要件定義書 v0.1.2](requirements.md) | 上位文書。FR / NFR / データ定義 / IF-02 スキーマ契約。変更点は同書 7.1（v0.1 → v0.1.1）および 7.2（v0.1.1 → v0.1.2）を参照 |
| [小売月次統計 KPI カタログ](../retail-domain/retail-monthly-kpi-catalog.md) | 業態 13 件 / 指標 14 件の定義、発表主体（§1.1）、複数発表主体の並立（§1.4）、`種別=company` 行の将来書式（§1.5）、既定スコープと既存店判定の適用順序（§2.2）、正規化ルール（§4.1〜§4.5）。読み取り専用の外部定義 |
| [parse-wbs.py](../../../../.claude/hooks/parse-wbs.py) | MD テーブルの header-aware パースの既存実装。§2.4 で再利用範囲を明示 |
| [.claude/rules/artifact-placement.md](../../../../.claude/rules/artifact-placement.md) | 成果物配置マトリクス。§2.1 の配置決定の根拠 |
| [.claude/rules/git-workflow.md](../../../../.claude/rules/git-workflow.md) | ブランチ・PR 運用。M7 の差分レポートが PR 本文に載る |

---

_本書は設計のドラフトである。§4 の正規表現・期間解決ロジック・金額換算・発表主体解決・スコープ分類は、**計測日 2026-07-26** の日次ダイジェスト実データ（102 ファイル / 決算・統計章 595 行 / 一意 URL 406 件）に対してプロトタイプを実行し、記載した検証結果を確認したうえで記述している。_

_**測定値についての注記**: 日次ダイジェストは毎日追加されるため、本書および要件定義書に記載した実測値（ファイル数・行数・一意 URL 数・各種比率）は計測日により変動する。要件定義 v0.1 の 101 ファイル / 588 行 / 一意 405 件は 2026-07-25 時点、本書の 102 ファイル / 595 行 / 一意 406 件は 2026-07-26 時点の計測であり、差は 1 日分のダイジェストによるもので母数の性質に変化はない。数値を引用する際は計測日を併記すること（要件定義 7.1 の注記と同旨）。_

_§9.3 の決定事項 D1〜D4 は要件定義 v0.1.1 に、**D5 / D6 は v0.1.2** に反映済みであり、本書の §3〜§8 は確定後の内容で記述されている。§9.4 に残る未決は **U2 / U6 / U7 / U8 / U9** の 5 件（**U5 / U10 は D5 により解消**）。うち U2 / U6 / U7 / U8 は v0.1 の実装を止めない（意図的な非対応、または決定を後続マイルストーンまで遅らせても他の設計に波及しない構造にしてある）。一方 **U9（NFR-05 の未達 — 目標値を下げるか未達のまま進めるかのオーナー判断が要る）は M3 での判断を要する**。D5 / D6 により分子・分母がともに動くため、**U9 の確定値は M3 の `measure` による再計測を待つ**。実装の着手自体は妨げないが、未決のまま M3 を通過させてはならない。_
