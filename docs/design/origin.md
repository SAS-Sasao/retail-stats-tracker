# 設計成果物の出自情報

## ソース

- **リポジトリ**: https://github.com/SAS-Sasao/cc-sier-organization
- **組織**: domain-tech-collection
- **コピー日**: 2026-08-02
- **コピー元コミット**: `2da1c48844ea7cfaa07ef24b3012d3188a76c003`（初回）
- **関連 PR**: #710（設計3冊のマージ） / **関連 Issue**: #711
- **作業者**: SAS-Sasao

## コピーした成果物

| ファイル | コピー元パス | 作成日 | 最終同期 |
|---------|------------|--------|---------|
| `requirements.md` | `.companies/domain-tech-collection/docs/research/retail-stats-tracker-requirements.md` | 2026-07-26 | `2da1c48`（初回） |
| `implementation-design.md` | `.companies/domain-tech-collection/docs/research/retail-stats-tracker-design.md` | 2026-07-26 | `2da1c48`（初回） |
| `loop-engineering-design.md` | `.companies/domain-tech-collection/docs/research/retail-stats-tracker-loop-engineering-design.md` | 2026-07-26 | **`6a9843c`（2026-08-02 再取得）** |
| `cicd-design.md` | `.companies/domain-tech-collection/docs/research/retail-stats-tracker-cicd-design.md` | 2026-07-26 | `2da1c48`（初回） |
| `retail-monthly-kpi-catalog.md` | `.companies/domain-tech-collection/docs/retail-domain/retail-monthly-kpi-catalog.md` | 2026-07-26 | `2da1c48`（初回） |

コピーにあたり、5 文書間の相互参照（ファイル名によるリンク）のみを新ファイル名に機械的に置換した。それ以外の本文・数値・結論は原文のまま変更していない。**再取得時も同じ置換のみを適用する。**

### 同期履歴

| 日付 | 対象 | コミット | 内容 |
|---|---|---|---|
| 2026-08-02 | `loop-engineering-design.md` | `6a9843c` | §2.3 ② の C4 に `発表主体` を追加 + C11 / C12 を新設（[Issue #724](https://github.com/SAS-Sasao/cc-sier-organization/issues/724) → [PR #725](https://github.com/SAS-Sasao/cc-sier-organization/pull/725)）。詳細は D-C |

**同期の確認方法**（5 文書すべての乖離を検出する）:

```bash
gh api "repos/SAS-Sasao/cc-sier-organization/contents/<原本パス>" --jq '.content' \
  | base64 -d | sed -e 's/retail-stats-tracker-requirements\.md/requirements.md/g' \
                    -e 's/retail-stats-tracker-loop-engineering-design\.md/loop-engineering-design.md/g' \
                    -e 's/retail-stats-tracker-cicd-design\.md/cicd-design.md/g' \
                    -e 's/retail-stats-tracker-design\.md/implementation-design.md/g' \
  | diff docs/design/<ローカル名> -
```

差分が出なければ同期済み。2026-08-02 時点で 5 文書すべて差分なし。

## 設計のレビュー状況

- L1: pass
- L2 composite: **0.88 / pass**（3 巡: 0.69 → 0.84 → 0.88）

## 未決事項（実装前にオーナー判断が要る）

- **NFR-05 未達確定**: 64/83 = 77.1%。目標 80% への到達には以下の組み合わせが必要（単独では上限 78.6%）
  - (a) 左窓（数値トークンから左方向に指標別名を探す範囲）の緩和
  - (b) 定性表現（増収増益等、value 化不可の表現）の分子算入の定義確定
  - (c) ランキング記事の分母除外
- **U10（複数主体併記）**: 30 件（要対応 13 / 誤検出 17）で、1 記事に複数の企業名が併記されたとき 2 社目が黙って捨てられる問題がある。現行の衝突検出は実データで 0 件しか発火せず、対策が未実装。

詳細は `loop-engineering-design.md` §1.2 / `implementation-design.md` §4.3.7・§7.2 T-8 を参照。

---

## 実装時の決定事項（本リポジトリ側で決めたもの）

設計原本は cc-sier 側にある。以下は**設計を変更したものではなく**、設計が
前提としていた実行環境（cc-sier-organization リポジトリ）と、本リポジトリが
スナップショットであることの差を埋めるために決めた事項である。cc-sier 側へ
フィードバックすべきものには ⇄ を付す。

### D-A. 入力データの所在（2026-08-02 決定）

**背景**: 設計は `.companies/{org}/` を基点に、入力（`docs/daily-digest/*.md`）と
出力（`docs/retail-stats/data/`）とカタログ（`docs/retail-domain/`）を解決する
前提で書かれている。本リポジトリにはこのツリーが存在せず、カタログのみ
`docs/design/retail-monthly-kpi-catalog.md` にコピーがある。

**選択肢の比較**:

| # | 案 | 採否 | 理由 |
|---|---|---|---|
| 1 | **テストフィクスチャを持つ**（`tests/fixtures/` を唯一のテスト入力にする） | **採用（必須）** | 実装設計 §7.3 が既に「実ファイルを直接読むテストは、日次ダイジェストが毎日追加・修正されるため再現性を持たない」として要求している。本リポジトリの事情とは無関係に、そもそもテストはフィクスチャを読むべきである。これ単独では**実カタログに対する契約検査**（段階 0 の完了条件 (a)）が回らない |
| 2 | **cc-sier を相対参照する**（`../cc-sier-organization/.companies/...`） | 不採用 | 兄弟ディレクトリへのチェックアウトという**暗黙の前提をコードに埋め込む**。CI（`actions/checkout` は単一リポジトリ）で再現せず、開発環境ごとに壊れ方が変わる。「動く人の環境と動かない人の環境がある」状態は、検証信号の一貫性を最優先する loop-engineering-design §1.1 の原則と正面から衝突する |
| 3 | **`--org` に外部パスを渡せるようにする** | 不採用 | 実装設計 §2.5 は `--org SLUG` を「処理対象組織。`.companies/{slug}/` を基点にする」と定義している。パスを受理させると `{slug}` が「組織名」と「パス」の 2 つの意味を持ち、`.companies/{slug}/` というレイアウト前提そのものが壊れる。将来 cc-sier 上で `--org other-org` を指定する本来の用途とも衝突する。**§2.5 の設計意図と矛盾するため採らない** |
| 4 | **ワークスペースルートだけを環境変数で差し替える**（`RETAIL_STATS_WORKSPACE`） | **採用** | 差し替えるのは「`.companies/` を含むディレクトリ」だけであり、`--org` は組織スラグのまま・`.companies/{org}/docs/...` の相対構造もそのまま。§2.5 の引数表に一切触れずに、データ層が別リポジトリにある状況を吸収できる。cc-sier 上で実行するときは未設定でよく、そのとき挙動は設計どおり（ワークスペースルート = リポジトリルート） |
| 5 | **カタログのみリポジトリ内スナップショットへフォールバック** | **採用（限定）** | 段階 0 の完了条件 (a)「現行カタログが C1〜C10 を全て pass する」を本リポジトリ単体で満たすために必要。**カタログに限る**（ダイジェスト・データ出力にはフォールバックを設けない）。どちらを読んだかは `config.resolved_inputs()` が `catalog_source: canonical / repo-snapshot` として返し、CLI が必ず表示する — どの入力を読んだか分からないまま処理が進むことを許さない（§1.2 silent accumulation への配慮） |

**採用した方針は 1 + 4 + 5 の組み合わせ**である。実装は `retail_stats/config.py` に集約した
（同モジュールの責務は §2.3 で「リポジトリルート解決、org スコープのパス生成」と定義されている）。

| 対象 | 解決順 |
|---|---|
| カタログ | ① `{workspace}/.companies/{org}/docs/retail-domain/retail-monthly-kpi-catalog.md` → ② `{repo_root}/docs/design/retail-monthly-kpi-catalog.md` |
| ダイジェスト | `{workspace}/.companies/{org}/docs/daily-digest/`（フォールバックなし） |
| データ出力 | `{workspace}/.companies/{org}/docs/retail-stats/data/`（フォールバックなし。書き込み先を曖昧にしない） |
| 配信 HTML | `{repo_root}/docs/retail-stats/index.html`（org 非依存。workspace 差し替えの対象外） |
| テスト | 常に `tests/fixtures/` を直接指す。実データの所在に依存しない |

`workspace` は `RETAIL_STATS_WORKSPACE` が設定されていればその値、未設定なら
リポジトリルート。cc-sier の作業コピーで実データを流すときは次のように使う。

```bash
RETAIL_STATS_WORKSPACE=/path/to/cc-sier-organization \
  python3 -m retail_stats build --dry-run --rebuild
```

**⇄ cc-sier 側への申し送り**: `--org` の意味は変えていないため設計改訂は不要。
ただし実装設計 §2.5 の引数表に「パスではなく組織スラグである」ことと、
データ層の所在は環境変数で差し替える旨を注記できると、同じ検討を
繰り返さずに済む。

### D-B. 設計書に無い実装上の判断

| # | 判断 | 理由 |
|---|---|---|
| B1 | `CatalogError` の実体を `models.py` に置き、`catalog.CatalogError` を同じクラスへの別名にした | 実装設計 §3.3 は `Catalog.validate()` が `CatalogError` を送出すると定めている。§3.1 のとおり `catalog.py` に定義すると、レイヤ 0 の `models.py` が `catalog.py` を import することになり §2.3 の依存方向（models は何にも依存しない）が壊れる。クラスは 1 つだけで、どちらの import パスでも同じものを指す |
| B2 | `config.py` が `os.environ` を参照する（§2.3 の依存先は「pathlib のみ」） | D-A の `RETAIL_STATS_WORKSPACE` に必要。標準ライブラリのモジュール参照であり「外部パッケージを追加しない」（NFR-08 / P1）方針には抵触しない |
| B3 | 行番号つきの違反メッセージは `catalog.load()` が、ID ベースの違反メッセージは `Catalog.validate()` が出す | §3.3 の違反メッセージ例は行番号を含むが（`不正な ID 形式: 'Shopping Center' (行 28)`）、`Catalog` dataclass は §3.2 で 4 フィールドに固定されており行番号を保持できない。判定そのものは両者で述語ヘルパを共有しており一致する。`validate()` は Catalog だけを引数に取る独立した検査として残る |
| B4 | `validate_catalog.py` は `retail_stats.catalog` の定数（列名許容リスト・単位対応表・発表主体対応表）を import して使う | 同じ契約を 2 か所に書くと「hook は通すのにローダが落ちる（逆も）」という最悪の食い違いが生まれる。段階 0 では検査だけが先に存在する想定だが、本作業では M2 と同時に着手したため実装済みの定数を正とした |
| ~~B5~~ | `validate_catalog.py` の C4 必須列に `発表主体` を含めた | **決着済み（2026-08-02）。** 暫定判断として要件 v0.1.1（上位文書）を正としたもの。Issue #724 → PR #725 で**設計原本の C4 が 6 列に修正され**、実装と一致した。現在は設計どおりであり独自判断ではない（D-C 参照） |
| B6 | `validate_catalog.py` の C9 enum 検査に `種別`（entity_type）と `表示順` を追加した | 必須列として要求しておいて値を検査しないのは片手落ち。理由コードは既存の `enum_invalid` を共用する |
| B12 | `digest.parse_file()` は、列マップを解決できなかったとき **ヘッダ行自身も** malformed に入れる | 列マップを解決できない以上、その行がヘッダなのかデータなのかを判別する根拠が無い。判別できないものを落とすのは要件 7-12 が禁じる欠測にあたる。実装設計 §4.1 規則 5 は「データ行」としか書いていないため、この解釈を記録する |
| B13 | `_common.sh` に `rs_is_digest()` を追加し、`RETAIL_STATS_WORKSPACE` を指した場合の**絶対パス**もダイジェスト判定の対象にした | ① guard-readonly-inputs はリポジトリ相対パスしか見ていなかった。D-A で外部ワークスペースを指せるようにした以上、そこを見ないと IF-01 の読み取り専用契約が環境によって効いたり効かなかったりする |
| B14 | `tests/test_golden60.py`（候補ファイルの構成を固定するテスト）を追加した | 設計のテスト一覧には無い。G1 の区分別件数は評価の妥当性そのもので、**末尾 3 区分 14 件が欠けると評価が「取れた数」だけを報酬にしてしまう**（G1 本文）。ファイルが静かに差し替わったことを検出できるようにした。期待値の中身には踏み込まない |
| B15 | `digest.parse_file()` は、リンクを抽出できない行がヘッダとして解決できる場合、**ヘッダとして扱い直す** | 1 つの章に表が 2 つ以上あると、2 つ目のヘッダ行は列マップを持ち越したまま「リンクの無いデータ行」として誤認される。実データでは章あたり表は 1 つ（malformed 0 件）だが、誤認すると本物のデータ行と見分けがつかない形で件数がずれる。実装設計 §4.1 規則 5 は表が 1 つである前提を明示していない |
| B16 | golden-60 の「期間表記の全 5 種」を カタログ §4.2 の行に 1:1 で対応させた（`month` / `fiscal_period`（◯年◯月期）/ `quarter` / `half` / `fiscal_year`（◯◯年度）） | G1 は「月次 / 決算期 / 四半期 / 半期 / 年度」の 5 種としか書いておらず、判定パターンは定義されていない。**決算期と年度を 1 つに畳むと種類数が 4 になり、枠数 8 を割り振ったときに最多の「月次」が 0 件になって「全 5 種」を満たせない**。また `1~6月期`（半期）は `[0-9]{1,2}月期`（決算期）にも `[0-9]{1,2}~[0-9]{1,2}月`（四半期）にも一致するため、**狭いパターンから先に評価する**必要がある（順序を誤ると半期が構造的に 0 件になる。回帰テストあり） |
| ~~B7~~ | **C11**（発表主体対応表への写像）を追加した | **決着済み（2026-08-02）。** PR #725 で C11 が設計原本に新設され、理由コード `authority_unmapped` も実装と一致した |
| ~~B8~~ | **C12**（ローダ受理。C1〜C11 が全て通ったときだけローダを実行する）を追加した | **決着済み（2026-08-02）。** PR #725 で C12 が設計原本に新設された。原本は「C 番号を V 番号に 1:1 で増やす案は採らない（ローダ側に V14 以降が追加されるたび同じ乖離が再発する）」として、ローダ自身を通す方式を採用しており実装と一致。**理由コードは `loader_rejects` → `loader_rejected` に修正済み**（原本の表記に合わせた）。実装は `Catalog.validate()` ではなく `catalog.load()` を呼ぶが、`validate()` を呼ぶには結局 `load()` が要るため検査範囲は同じ |
| B9 | `settings.json` に A 系統 hook（`capture-interaction.sh` / `quality-gate.sh` / `session-boundary.sh`）を書かなかった | ループ設計 §2.2 の JSON は cc-sier 側の既存 40 行への**追記**として示されたものであり、本リポジトリにこれらのスクリプトは存在しない。存在しないスクリプトを配線すると全ツール呼び出しで hook エラーが出る。`env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` も同様（§6「組織運営が使うため既存のまま残す」= 本リポジトリの関心事ではない） |
| B10 | ⑦ `gate-coverage-regression.sh` を「配線だけ」の最小実装で置き、`runs.json` が**存在するのに S1〜S4 が未実装**なら `rs_block` するようにした | §2.2 の配線上の注意が、配線を先送りすると「発火しないゲートが仕様上は存在する」状態になると明示しているため段階 0 で置く。ただし判定できない状態を pass と報告するのは、本設計が最大の危険とする silent accumulation そのもの。よって「判定対象なし → exit 0 / 判定対象あり かつ 未実装 → block」とした。Stop 配下のため読み取り専用（`$RS_DATA_ROOT` に書かない）を厳守している |
| B11 | `_common.sh` に `RS_CATALOG_SNAPSHOT` と `rs_is_catalog()` / `rs_relpath()` を追加した | D-A のカタログ解決順を hook 側にも反映するため。`config.py` の解決順と一致させること（片方だけ直すと hook が発火しなくなる） |

### D-C. 設計書間の不整合（cc-sier 側へ報告済み・**決着済み**）

| # | 箇所 | 内容 | 状態 |
|---|---|---|---|
| C-1 | `loop-engineering-design.md` §2.3 ② の **C4** | 業態表の必須列を「`segment_id`/`業態ID`, `名称`/`正式名称`, `別名`/`表記ゆれ`, `種別`, `表示順`」の 5 種としており、**`発表主体` が抜けていた**。要件 v0.1.1 で `発表主体` が必須列に昇格した際の追随漏れ（要件 §6 IF-02「業態定義表の必須列」表と、同 §9 差分表 #3「`発表主体` を必須列に追加」が正。実装設計 §3.1 段階 3 も「**`発表主体` は無視してはならない**」と明記）。放置すると natural key の第 5 要素を供給する列が欠けたカタログを段階 0 のゲートが通してしまう | **解決済み（2026-08-02）**。[Issue #724](https://github.com/SAS-Sasao/cc-sier-organization/issues/724) で報告 → [PR #725](https://github.com/SAS-Sasao/cc-sier-organization/pull/725) でマージ。C4 が 6 列に修正され、あわせて **C11 / C12 が新設**された |

**C-1 の解決にあたって原本が示した判断**（本リポジトリの実装はこれに一致している）:

- C4 は上位文書（要件 v0.1.1）を正として 6 列に修正。現行カタログ 13 業態はすべて `発表主体` を持つため、**カタログ側の改訂は発生しない**（検査の穴を塞ぐだけ）
- C11（発表主体対応表への写像 / `authority_unmapped`）を新設
- C12（C1〜C11 通過後にローダ自身を実行 / `loader_rejected`）を新設。**「C 番号を V 番号に 1:1 で増やす案は採らない」**——ローダ側に V14 以降が追加されるたび同じ乖離が再発し、追随漏れが構造的に起きるため（C4 欠落がまさにその形で発生した）。代わりにローダ自身を通すことで包含関係をコードの重複なしに保証する
- C1〜C11 を先に評価する理由も明記された。ローダは最初の `CatalogError` で停止するため、列欠落のような自明な不備があると理由コードが 1 件しか得られない。C1〜C11 は独立に全件評価できるので、編集者に一度で全ての不備を返せる

**スナップショットへの反映**: `docs/design/loop-engineering-design.md` を PR #725 マージ後の原本（コミット `6a9843c`）から取り込み済み。取り込み時は初回コピーと同じ 5 文書間の相互参照ファイル名の機械的置換のみを適用し、それ以外の本文は変更していない。他の 4 文書は原本と内容差分なし（差分はすべて初回コピー時の意図的なファイル名置換）。

**実装側の追随**: 理由コードを `loader_rejects` → `loader_rejected` に修正した。それ以外の実装変更は不要だった（暫定判断がすべて原本の判断と一致していたため）。

### D-D. 段階 0 の完了条件のうち、本リポジトリでは確認できないもの

| 完了条件 | 状態 |
|---|---|
| (a) 現行カタログが C1〜C10 を全て pass する | **達成**（C1〜C12 で pass。`python3 scripts/retail-stats-tracker/validate_catalog.py`） |
| (b) golden-60 の期待値が人手で確定し、末尾 3 区分 14 件を含む | **未着手・本リポジトリでは不可能**。`.companies/{org}/docs/daily-digest/` の実データ（102 ファイル / 595 行）が必要。cc-sier 側、または `RETAIL_STATS_WORKSPACE` で作業コピーを指した状態で行う |
| (c) ダイジェストへの書き込みが実際に拒否されることを確認 | **hook 単体では確認済み**（`agent_type=retail-stats-qa` + `$RS_DIGEST_DIR` 配下のパスで `permissionDecision: "deny"` を返すことを検証）。ただし `$RS_DIGEST_DIR` が実在する状態での end-to-end 確認は cc-sier 側で行う必要がある |

### D-E. ネクストアクション（2026-08-02 時点）

**完了済み**: M2（カタログローダ）/ M1 のうち `config.py` のパス解決 / 段階 0 の hooks 配線
（① guard-readonly-inputs / ② verify-catalog-contract + `validate_catalog.py` / `_common.sh` /
`settings.json` / ⑦ の配線）/ 段階 0 完了条件 (a)。テスト 89 件（カタログ関連 49 件が green、
残り 40 件は後続マイルストーンの skip）。

#### N-1. 実データが無いと進めないもの（**2026-08-02: N-1b/c/d 完了、N-1a はオーナー確定待ち**）

`.companies/{org}/docs/daily-digest/` の実データ（102 ファイル / 595 行）が必要。cc-sier 側で
実行するか、本リポジトリで `RETAIL_STATS_WORKSPACE=/path/to/cc-sier-organization` を指す。

| # | 内容 | 根拠 | 状態 |
|---|---|---|---|
| N-1b | **M1 の残り**（`textnorm.py` / `digest.py` / `cli.py` の `build --dry-run`） | 実装設計 §8 M1 | **完了**。設計の実測値を完全再現（102 / 93 / 89 / 595 / 595、一意 406、ヘッダ 1 種、章が無い 9 日も設計の列挙と一致） |
| N-1c | **`tests/fixtures/digests/` の生成**（`make_fixtures.py`） | 実装設計 §7.3 | **完了**。12 日分。`s041442` の非連続 6 日・4 variant を再現（T-1 の前提） |
| N-1d | 段階 0 完了条件 (c) の **end-to-end 確認** | 段階 0 完了条件 (c) | **完了**。実在する digest への書き込みが `permissionDecision: deny` を返し、メインセッションは素通し、入力の sha256 が不変であることを確認 |
| N-1a | **golden-60 の凍結**。期待値を人手で確定し、末尾 3 区分 14 件を含める | 段階 0 完了条件 (b)。§3.3 規律 G1 | **候補選定まで完了・期待値はオーナー確定待ち**。下記 |

**N-1a の現状**: `tests/make_golden60.py` が G1 の選定基準表どおり 8 区分・合計 60 件を
機械的に選び、`tests/fixtures/golden-60.candidates.jsonl` に出力する（再実行でバイト一致）。
**期待値は意図的に空**（`expected: null` / `status: "needs_human_review"`）である。G1 は
選定を「機械的に決める」、期待値を「人手で確定」と明確に分けており、期待値を機械が
推測して埋めると「実装に引きずられた期待値」になって評価が成立しないため。
オーナーが `expected` を埋め `status` を `confirmed` にして `golden-60.jsonl` として凍結する。

選定時に判明した、**オーナー判断が要る 3 点**:

| # | 内容 |
|---|---|
| G-1 | **`主要4業態 × 既存店` に一致する一意 URL は 12 件しかない**（G1 は 18 件を要求）。不足 6 件は「主要 4 業態の月次指標（既存店表記なし = 全店系）」で補い、`selected_because` に明記した。18 件すべてを既存店指標にしたい場合は母集団の期間を広げる必要がある |
| G-2 | **`no_numeric` の 4 件がすべてランキング記事になった**。これは未決事項 (c)「ランキング記事の分母除外」と直接ぶつかる。除外すると決めるなら、この 4 件は `no_numeric` ではなく `out_of_scope` が期待値になる |
| G-3 | G1 が名指しする代表例 `ホームセンター月次実績＝2026年6月度` は候補プールに存在し条件も満たすが、URL 昇順のタイブレークで上位 4 件に入らなかった。凍結時に差し替えるかはオーナー判断（候補ファイルの編集で足りる） |

**順序（2026-08-02 訂正）: N-1b → N-1a → M3。** 当初「N-1a を N-1b より先に」と書いたが誤りだった。
規律 G1 の本文は「**パーサのコードを 1 行も書く前に**完了させる」であり、制約の対象は `parser.py`（M3）である。
`textnorm.py` / `digest.py` / `cli.py`（M1）は含まれない。むしろ **golden-60 の選定には `digest.py` が必要**で、
595 行を列挙できなければ「代表 60 行を機械的に選ぶ」こと自体ができない。したがって M1 → golden-60 凍結 →
M3 の順になる。G1 が守ろうとしているのは「期待される observation の値がパーサ実装に引きずられないこと」であり、
行の切り出し（どの行が存在するか）はパーサの解釈を含まないため、この順序で規律は損なわれない。

#### N-2. 実装判断が要るもの

| # | 内容 | 状態 |
|---|---|---|
| N-2a | **別名索引の正規化方針**（M3 の前提）。`Catalog` の別名索引はカタログ原文のまま保持しており（`チェーンストア（総合小売含む）` のように全角括弧を含む）、`parser.py` は `textnorm.normalize()`（NFKC）を通した文字列で照合するため構造的に一致しない。照合直前に別名側も正規化するか、索引構築時に正規化するかを決める。**実装設計 §3.2 / §4.2 のどちらにも記述がない** | 未決。M3 着手前に決め、D-B に記録して cc-sier に報告する |
| N-2b | **B6（C9 の enum 検査に `種別` / `表示順` を追加）を cc-sier に戻すか**。C4 / C11 / C12 が原本に反映された今、これが唯一残る「設計に無い判断」 | 未報告。C-1 と同じ形（issue）で報告するかを判断する |
| N-2c | `cli.py` の `--dry-run` 出力に `config.resolved_inputs()` を必ず含める（D-A の「どの入力を読んだか分からないまま処理が進むことを許さない」の実装面） | N-1b と同時に実装する |

#### N-3. 段階 1 以降で入れる検証 hooks

| # | 内容 | 導入段階 |
|---|---|---|
| N-3a | ③ `verify-parser-tests.sh`（触ったモジュールのテスト実行）+ ⑧ `gate-signal-tampering.sh`（検証信号の改変検知）+ `/retail-stats-verify` 骨格 | 段階 1 |
| N-3b | ④ `gate-dataset-integrity.sh` / ⑤ `gate-idempotency.sh`（**Stop では読み取り専用**、破壊的な R1/R2 は `--full` に限定）/ `retail-stats-qa` / `/retail-stats-build` | 段階 2 |
| N-3c | ⑦ `gate-coverage-regression.sh` の **実効化**（S1〜S4 の実装）。現在は配線のみで、`runs.json` が生成されたら block するスタブ（D-B B10） | 段階 2 |

⑧ を段階 1（最初期）に置くのは意図的（§2.4）。後から入れると、それまでに緩められた閾値が
「既存行」として免責される。

#### N-4. オーナー判断待ち（実装では解決できない）

本書「未決事項」節のとおり。**NFR-05 未達（64/83 = 77.1%）** と **U10（複数主体併記）** は
M3 の判断分岐点に直結する。ループ設計 §7.1 の U3（LLM 抽出の実行主体）は段階 4 着手前まで。

#### N-5. 設計同期

`loop-engineering-design.md` は 2026-08-02 に `6a9843c` へ同期済み（同期履歴の節を参照）。
以後も cc-sier 側で設計が動きうるため、マイルストーンの区切りごとに「同期の確認方法」の
コマンドを 5 文書に対して実行すること。

## 更新ルール

- 設計原本は **cc-sier 側**（`.companies/domain-tech-collection/docs/research/` および `docs/retail-domain/`）にある。本リポジトリはスナップショットである。
- 設計変更が発生した場合は cc-sier 側で更新し、このリポにも反映すること（二重管理を避けるため、原本は常に cc-sier）
- このリポで設計を直接変更した場合は、cc-sier 側にもフィードバックすること
- `origin.md` は削除しないこと（設計のトレーサビリティ維持のため）
