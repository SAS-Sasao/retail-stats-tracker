# 小売月次統計トラッカー ループエンジニアリング設計書

## `.claude` 構成詳細 — 検証 hooks / SKILL カタログ / maker-checker 分離 / 開発ループ

| 項目 | 内容 |
|------|------|
| ドキュメント種別 | 設計書 v0.1.4（ドラフト） |
| 作成日 | 2026-07-26 |
| 改訂 | v0.1.1（2026-07-26）— 要件定義 v0.1.1 の 2 変更に追随。natural key を 5 要素化（§2.3 ④ D2/D3）、L_extract の分母を対象内行に再定義（§1.2 / §2.3 ⑦ S3・S4）、および付随して分母操作への防御を追加（§2.3 ⑧ T3 / §4.2 SP2b / §3.3 G1）<br>v0.1.2（2026-07-26）— L2 レビュー指摘に対応。⑦ を settings.json に配線（§2.2 / §2.4）、ゲート数を 7 に統一、実行メタデータを `runs.json` に統一し冪等性比較から除外（§2.3 ⑤）、テストランナーを unittest に決着（U2）、`permanently_unresolvable` の永続化先を定義（§3.2）<br>v0.1.3（2026-08-01）— L2 再レビュー指摘に対応。**(1)** 契約外の CLI 引数 `--out` を廃し、⑤ を「退避 → 再実行 → 比較 → 復元」方式に書き換え副作用の封じ込め策を明記（§2.3 ⑤）**(2)** `RS_REPRO_FILES` を実装設計 §5.1 と同じ 6 ファイルに統一（§2.1 / §2.2）**(3)** NFR-05 の分母を一意 URL [代表] 基準に統一し行ベースの式を撤回（§1.2 / §2.3 ⑦ S3・S4）**(4)** 主語位置ガード導入前の旧内訳を確定値 154/169/77 件（19.0%）・64/83 = 77.1% に更新（§1.2）**(5)** 要件参照を v0.1.1 に、golden-60 の母数を 595 行（計測日 2026-07-26）に統一（§3.3 / §7.3 / §8）**(6)** Stop のブロック可否と `stop_hook_active` の実在を公式ドキュメントで検証し、仕様リファレンス §1.1 の誤りを注記（§1.3 / §2.6 / §7.2）<br>v0.1.4（2026-08-01）— L2 最終レビュー（composite 0.88 / pass）後の任意修正。**(1)** hook は**並列実行**であることを公式で確認（仕様リファレンス §1.7 の誤り）。逐次前提が崩れるため **⑤ の破壊的検査（R1/R2）を Stop から外し、`--full` モードとして `/retail-stats-verify` と CI に移設**。Stop 配下 5 本を全て読み取り専用に統一し、不変条件を ⑧ T7 で機械的に守る（§2.2 ★ / §2.3 ⑤ / §2.3 ⑧）**(2)** Subagent の `when_to_use:` を削除し `description` に畳み込み（公式 16 フィールドに存在しない。§4.1）**(3)** Stop の `matcher` を削除（matcher 非対応・silently ignored。§2.2）**(4)** `permanently-unresolvable.json` を含む `DATA_DIR` 期待値 8 種 / バイト一致比較 6 種の切り分けを明記（§3.2）**(5)** 仕様リファレンスの確認済み誤り 4 件を §7.2 A9 に集約 |
| 作成者 | 技術リサーチ室（ai-developer） |
| 対象システム | retail-stats-tracker（Claude Code 開発基盤） |
| ステータス | レビュー待ち |
| 上位ドキュメント | [要件定義書 v0.1.1](./requirements.md) |
| 並行ドキュメント | [実装設計](./implementation-design.md)（system-architect 執筆中） / [CI/CD 設計](./cicd-design.md)（ci-cd-engineer 執筆中） |
| 前例 | [ai-virtual-office ループエンジニアリング設計書](./ai-virtual-office-loop-engineering-design.md) |
| 仕様の根拠 | Claude Code Specification Reference (v2.1+)（claude-code-guide 作成）。**ただし §1.1 の Stop ブロック可否と §1.3 のフィールド一覧に誤り・欠落を確認済み**（§1.3 ★ / §2.6）。本書が依拠する仕様は [公式ドキュメント](https://code.claude.com/docs/en/hooks) で個別に裏を取っている |
| 思想的ベース | [Loop Engineering (Addy Osmani)](https://addyosmani.com/blog/loop-engineering/) / [スキル自動最適化とループエンジニアリング (LayerX)](https://zenn.dev/layerx/articles/9f25ec86a31730) |

**本書のスコープ外**: GitHub Actions ワークフロー（FR-21 / IF-04）および日次自動更新の実行基盤設計は本書では扱わない。ci-cd-engineer が `cicd-design.md` に並行執筆中であり、そちらに委ねる。ただし**検証 hooks とその実体スクリプトは本書の担当**であり、同一スクリプトを CI ステップからも再利用する前提で設計する（§2.7）。

**実装設計との関係**: 本書 v0.1 は `implementation-design.md` の完成前に書かれ、要件定義 v0.1 を根拠にしていた。v0.1.1 で実装設計と要件定義 v0.1.1 に追随済みである。具体的には natural key の 5 要素化（§2.3 ④）、NFR-05 分母の再定義（§1.2 / §2.3 ⑦）、コード配置パスの確定（§2.1、実装設計 §2.1）を反映した。

---

## 1. 背景と設計原則

### 1.1 ループエンジニアリングの適用方針

2 記事から採用する原則と、本プロジェクトへの反映:

| # | 原則 | 出典 | 本設計への反映 |
|---|---|---|---|
| P1 | ルールはプロンプト空間ではなく決定論的検証に置く | Osmani（Verification） | 要件定義の IF-02 スキーマ契約・NFR-06/07/08 を検証 hooks に機械化（§2） |
| P2 | 評価（検証信号）をスキル本文より先に作る | LayerX | golden-60 評価データセット先行の規律（§3.3） |
| P3 | maker と checker を分離する | Osmani（Sub-agents） | 既存 maker 4 種 + 検証専任 `retail-stats-qa` を新設（§4） |
| P4 | 停止条件は機械的合否で表現する | Osmani（/goal） | `/retail-stats-verify` を exit code で合否が出る script に（§3.1） |
| P5 | スキルの全面リライトは劣化を招く。差分編集のみ | LayerX + cc-sier PR #251→#254 教訓 | SKILL.md 編集規律（§3.4） |
| P6 | 無人ループには人間の観測面が必須 | Osmani（"A loop running unattended is also a loop making mistakes unattended"） | 人間のトリアージ点を 3 箇所に固定（下記） |
| P7 | 検証信号は「絶対値」ではなく「回帰」で見る | 本プロジェクト固有（§1.2） | カバレッジ回帰ゲート（§2.2 ⑦） |

#### 人間（オーナー）の観測・トリアージ点

**「無人で回るループは無人で間違え続ける」**（P6）を本プロジェクトに適用すると、無人化してよい範囲は「決定論パースの実行」までであり、以下の 3 点は**構造的に人間へ残す**。機械には判断材料が存在しないためである。

| # | トリアージ点 | 頻度 | なぜ機械に委ねられないか | 実装 |
|---|---|---|---|---|
| H1 | **未解決行の「解けない／まだ解いていない」判別** | 週次 | 制約 3（タイトルに数値が無い記事）は原理的に解けない。機械は「ルールが足りない」と「情報が存在しない」を区別できず、放置すると永久に改善バックログに滞留し、未解決率という損失関数がノイズ化する | `/retail-stats-triage`（§3.1）で reason_code 別に提示し、人間が `permanently_unresolvable` をマークする |
| H2 | **upsert による既存値の書き換えの承認** | 差分発生時 | リスク 8（速報→確報の改定／記事側の誤記訂正）と、パーサのバグによる誤上書きは、出力だけを見ると区別がつかない | 差分レポート（FR-22）に「上書きされた observation の変更前後」を必ず列挙し、PR 本文で目視する。件数 0 の日はレポートも出さない（読むべき日を減らす） |
| H3 | **検証ゲートが 2 回連続 fail した case のエスカレーション** | 発生時 | 自動修正 1 回で直らない失敗は、多くの場合「要件の理解違い」または「そもそも要件が誤っている」。自動リトライを重ねるほど劣化する | PR を draft に落として停止（§4.2 リトライポリシー） |

なお、**「ダッシュボードを常時公開すること」は観測点ではない**。読まれない可視化は観測面として機能しない。SC-06（データ品質画面）は事後の裏取り用と位置づけ、**能動的な通知は例外時のみ**（未解決率が NFR-05 の閾値を超えたときに限り Issue を立てる）とする。

### 1.2 このプロジェクト固有のループ特性と損失関数

本システムは他の開発プロジェクトと決定的に異なる性質を 1 つ持つ。**入力が毎日勝手に増える**ことである。

- 開発ループ（コードを変える）が止まっていても、日次ダイジェストは毎日生成され、決算・統計章に新しい行が積まれ続ける
- そのためパースの失敗は**イベントとして現れない**。例外も落ちず、終了コードも 0 のまま、単に「その行が observations に入らない」という**不在**として蓄積する
- 生成される HTML は古いデータのまま正常に描画され続けるため、画面を見ても壊れていることが分からない

これが本プロジェクトにおける最大の危険であり、**silent accumulation（沈黙する取りこぼしの蓄積）**と呼ぶ。要件定義 FR-10（未解決行を破棄しない）と NFR-10（`2>/dev/null` / `|| true` の禁止）は、この危険に対する要件レベルの回答であるが、要件は自動的には守られない。ループの損失関数として明示的に測る必要がある。

#### 損失関数の定義

各実行（`runs.json` の 1 レコード。実装設計 §5.1）で以下の 4 つを必ず算出し、時系列で保存する。**すべて「絶対値の閾値」ではなく「直近履歴に対する回帰」で判定する**（P7）。理由は制約 1 にある: 決算・統計章そのものが欠落する日（2026-04-14 等）が存在するため、単日のゼロは正常でありうる。絶対値で閾値を切ると誤検知だらけになり、誰も見なくなる。

| 記号 | 損失 | 定義 | 判定 | 対応する要件 |
|---|---|---|---|---|
| **L_silent** | 沈黙損失 | 対象セクションを検出できたファイル数、および `rows_parsed` | 直近 7 実行の**中央値**に対し -20% 以上の減少、または「対象セクション 0 件」が 3 実行連続 | 制約 1 / FR-01 |
| **L_extract** | 抽出損失 | **対象内**の未解決率 = `(nfr05.denominator - nfr05.numerator) / nfr05.denominator`。分母は発表主体が協会統計・マクロ統計である**一意 URL [代表]**（要件 v0.1.1 NFR-05 / 実装設計 §4.3.7、確定値 83）。実装は `series.json` の `quality.nfr05` をそのまま読み、式を再実装しない。**`rows_parsed`（延べ行）とは単位が異なる**（§2.3 ⑦ S3） | 20% 超で fail。`out_of_scope`（個社決算・非統計記事）と、H1 で `permanently_unresolvable` とマークされた行は、いずれも分母・分子の双方から除外する | NFR-04 / NFR-05 |
| **L_repro** | 再現損失 | 同一入力・同一キャッシュでの再実行が JSON バイト一致するか | 不一致で即 fail（0/1 判定） | NFR-06 / FR-09 |
| **L_prov** | 出典損失 | `article_id` を持たない observation、または `articles.json` に存在しない `article_id` を参照する observation の件数 | 1 件でも fail（0/1 判定） | FR-17 / §4.3 |

L_repro と L_prov を 0/1 判定にしているのは、これらが「少しなら許容できる品質指標」ではなく**契約**だからである。出典のないデータ点が 1 件でも混ざった瞬間、「提案の場で出典 URL 付きで語れる」という目的（要件 §1.2-3）が成立しなくなる。

#### なぜ L_extract を「率」で持ち、対象外行を分母から外すのか

未解決の**件数**で管理すると、入力が増え続ける本システムでは件数が単調増加し、閾値が形骸化する。率で持つことで、ルール改善（分子を減らす）と入力増加（分母を増やす）の双方が正しく反映される。ただし H1 の永久未解決行を除外しないと、解けない行が分子に固定され、率が下がらなくなって同じく形骸化する。**除外の判断が人間に残っている**のはこのためである。

分母を全パース行にしないのは、決算・統計章の大半が本システムの対象範囲外だからである。設計工程の実測（一意 URL 406 件 [代表] / 計測日 2026-07-26 / 実装設計 §4.3.7 の確定値）では、カタログ定義済み業態を主語とする行は **77 件（19.0%）** にとどまり、残りは**個社開示 154 件・非統計記事 169 件**だった。うち NFR-05 の分母に載るのは 83 件（対象内成功 64 + `no_metric_match` 3 + `no_numeric` 10 + `no_segment_match` 6）で、達成率は **64/83 = 77.1%（目標 80% に対し未達）** である。個社決算記事は日次ダイジェストに常時大量に含まれるため、全パース行を分母にすると**個社記事が増えるだけで L_extract が悪化して fail する**。ループが正常な状態でも恒常的に fail 側へ張り付き、損失関数として機能しなくなる。

`out_of_scope` の除外は、H1 の `permanently_unresolvable` と**意味が異なる**ことに注意する。前者は決定論的な判定木（設計書 §4.3.7）による機械的分類であり、後者は人間の判断である。前者を分母から外すことは silent fail ではない — 件数と原文は保持され、SC-06 に「対象外」として取りこぼし（`no_segment_match`）と区別可能な形で独立表示される（FR-10 / NFR-10）。**この区別が崩れると分母が操作可能になる**ため、§2.3 ⑧ の T3 と §4.2 の SP2 で両方向から守る。

### 1.3 hooks の 2 系統（最重要の区別）

前例 §1.2 の区別を本プロジェクトでも前提とする。ただし**本プロジェクトには前例に無い難所が 1 つある**。

前例（ai-virtual-office）では、観測用 hooks は「配布先プロジェクト」、検証用 hooks は「ai-virtual-office 自身のリポジトリ」と、**リポジトリが物理的に分かれていた**。本プロジェクトは cc-sier-organization リポジトリ**内**に実装されるため、既存の観測用 21 hooks と検証用 hooks が**同一の `.claude/settings.json` に同居する**。管轄の分離はパスガードで行うほかない。

| | (A) 観測用 hooks（既存 21 本） | (B) 検証用 hooks（本書で設計） |
|---|---|---|
| 実体 | `.claude/hooks/*.sh`（capture-interaction / quality-gate / session-boundary 等） | `.claude/hooks/verify/retail-stats/*.sh`（新設） |
| 目的 | Case Bank・ダッシュボード・会話ログのイベント収集 | 開発ループの検証信号（§1.2 の損失関数） |
| 失敗時挙動 | **必ず握り潰す**。`quality-gate.sh` は fail 時も `exit 0` で終える（現行実装 154 行目） | **exit 2 で止める／stderr を Claude に返す** |
| 対象の絞り込み | `.companies/{org}/docs/**/*.md` 等 | **retail-stats 関連パス配下に限定**（下記ガード必須） |
| 管轄 | 既存の組織運営基盤 | 本プロジェクト |

**すべての B 系統スクリプトは、冒頭で対象パス外なら無条件に `exit 0` すること。** 本プロジェクトの検証が、日次ダイジェスト生成や `/company-diagram` など無関係な作業をブロックしてはならない。このガードは `_common.sh`（§2.2）に一本化し、各スクリプトで書かない。

#### 仕様上の重要な訂正: PostToolUse は exit 2 でもブロックしない

前例 §2.1 は PostToolUse に exit 2 する検証 hooks を配線しているが、仕様リファレンス §1.4 の "Never Blockable" 一覧に **PostToolUse は明記されている**。PostToolUse で exit 2 しても、**すでに実行されたツールは取り消されず、stderr が Claude に表示されて処理は継続する**。

したがって本設計では役割を明確に分ける。

| イベント | ブロック可否（仕様 §1.4） | 本設計での役割 | 時間予算 |
|---|---|---|---|
| **PreToolUse** | ブロック可 | **禁止操作の阻止**（読み取り専用契約の防衛） | < 100 ms |
| **PostToolUse** | **ブロック不可** | **即時フィードバック**（書かれた内容の検査結果を stderr で Claude に返し、自己修正を促す） | < 15 秒 |
| **Stop** | ブロック可（★下記） | **エポック終端ゲート**（応答を終わらせない。ここが唯一の実質的な停止点） | 合計 < 60 秒 |

「編集した瞬間に止める」ことは Claude Code の hook 機構では実現できない。**止まるのは応答の終わりだけ**である。この事実を前提に、PostToolUse には「早く気づかせる」役割だけを与え、**合否の責任はすべて Stop に集約する**。PostToolUse で検出した違反は Stop でも必ず再検査される設計とし、PostToolUse を素通りしても Stop で捕まる二重構造にする。

**★ 仕様リファレンスの自己矛盾と、公式ドキュメントによる決着（2026-08-01 確認）**

仕様リファレンスは Stop のブロック可否について相反する記載をしている。§1.1 のイベント一覧表は Stop を `Blockable = No` とし、§1.4 の "Blockable by Exit 2" 一覧には Stop が**含まれている**。本設計は合否の責任を Stop に集約するため、この 1 点が崩れると設計の根幹が成立しない。したがって公式ドキュメント（[code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks)）を直接参照して裏を取った。

公式ドキュメントの "Exit code 2 behavior per event" 表は次のとおりであり、**Stop はブロック可**である。

| Event | Blocks? | Effect |
|---|---|---|
| `Stop` | **Yes** | Prevents Claude from stopping, continues the conversation |
| `SubagentStop` | Yes | Prevents the subagent from stopping |
| `PostToolUse` | No | （上記のとおりブロックしない） |

加えて Stop の "decision control" 節が `decision: "block"`（+ 必須の `reason`）で応答終了を阻止できると明記しており、exit 2 と JSON の双方に停止阻止の経路がある。**仕様リファレンス §1.1 の `Blockable = No` が誤り**であり、§1.4 が正しい。以後、仕様リファレンス §1.1 と §1.4 が食い違う項目については §1.4（Exit Codes & Behavior）を正とする。

なお公式ドキュメントには **「8 回連続でブロックすると Claude Code 側が hook を上書きしてターンを終了させる」** という上限がある。§2.6 の再入ガード（上限 2 回）はこの上限より内側にあるため、この上限に触れることはない。

---

## 2. 検証 hooks 設計

### 2.1 パス定義（単一定義点）

実装コードの配置は実装設計 §2.1 で `scripts/retail-stats-tracker/`（Python パッケージは `retail_stats/`）に確定している（U1 決着済み）。全スクリプトが参照するパスは `_common.sh` の 1 箇所にのみ書き、変更が生じた場合もここだけを直す。

```bash
# .claude/hooks/verify/retail-stats/_common.sh  （抜粋。実体は 2.2 に全体を示す）
RS_ORG="domain-tech-collection"
RS_CODE_ROOT="scripts/retail-stats-tracker"                                  # 実装コード（設計書 §2.1 で確定）
RS_DATA_ROOT=".companies/${RS_ORG}/docs/retail-stats/data"                   # 中間データ（要件 §1.4）
RS_CATALOG=".companies/${RS_ORG}/docs/retail-domain/retail-monthly-kpi-catalog.md"
RS_DIGEST_DIR=".companies/${RS_ORG}/docs/daily-digest"
RS_HTML="docs/retail-stats/index.html"                                       # 配信物（IF-05）
# 冪等性・再現性の比較対象。実装設計 §5.1 の IDEMPOTENT_FILES と同一の 6 ファイル。
# runs.json は実行時刻を含むため必ず除外する（§2.3 ⑤）
RS_REPRO_FILES="observations.json articles.json extraction-cache.json unresolved.json manifest.json series.json"
```

### 2.2 settings.json への配線

既存の `.claude/settings.json`（現行 40 行）に対する**追記**として示す。仕様リファレンス §1.6 の書式に従う。`hooks` は user / project / local スコープでマージされる（仕様 §5.1）ため、既存の A 系統エントリを消さずに配列要素を足す形になる。

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  },
  "alwaysThinkingEnabled": true,
  "effortLevel": "high",
  "permissions": {
    "allow": [
      "Bash(python3 -m unittest *)",
      "Bash(python3 -m retail_stats *)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/verify/retail-stats/guard-readonly-inputs.sh",
            "timeout": 10,
            "statusMessage": "入力の読み取り専用契約を検査中..."
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/capture-interaction.sh"
          }
        ]
      },
      {
        "matcher": "Write|str_replace_based_edit_tool|create_file",
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/quality-gate.sh"
          }
        ]
      },
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/verify/retail-stats/verify-catalog-contract.sh",
            "timeout": 30,
            "statusMessage": "カタログ IF-02 契約を検査中..."
          },
          {
            "type": "command",
            "command": "bash .claude/hooks/verify/retail-stats/verify-parser-tests.sh",
            "timeout": 60,
            "statusMessage": "パーサのテストを実行中..."
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/session-boundary.sh"
          }
        ]
      },
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash .claude/hooks/verify/retail-stats/gate-dataset-integrity.sh",
            "timeout": 120,
            "statusMessage": "データ整合性ゲート..."
          },
          {
            "type": "command",
            "command": "bash .claude/hooks/verify/retail-stats/gate-idempotency.sh",
            "timeout": 30,
            "statusMessage": "冪等性ゲート（読み取り専用モード）..."
          },
          {
            "type": "command",
            "command": "bash .claude/hooks/verify/retail-stats/gate-html-selfcontained.sh",
            "timeout": 60,
            "statusMessage": "HTML 自己完結性ゲート..."
          },
          {
            "type": "command",
            "command": "bash .claude/hooks/verify/retail-stats/gate-coverage-regression.sh",
            "timeout": 30,
            "statusMessage": "カバレッジ回帰ゲート..."
          },
          {
            "type": "command",
            "command": "bash .claude/hooks/verify/retail-stats/gate-signal-tampering.sh",
            "timeout": 30,
            "statusMessage": "検証信号の改変を検査中..."
          }
        ]
      }
    ]
  }
}
```

配線上の注意:

- **同一イベントにマッチする hook は「並列」実行される（★下記）。** Stop の 5 本は同時に走る。時間予算は「合計」ではなく**各 hook の個別予算**であり、応答終了までの待ち時間は 5 本の**最大値**（最長は ④ の 120 秒）になる。各スクリプトは `git diff` ガードで大半のセッションで即 `exit 0` する
- **Stop エントリに `matcher` を書かない。** 公式 matcher 対応表は `UserPromptSubmit` / `PostToolBatch` / `Stop` / `TeammateIdle` / `TaskCreated` / `TaskCompleted` / `WorktreeCreate` / `WorktreeRemove` / `MessageDisplay` を「matcher 非対応。常に毎回発火し、**書いても silently ignored**」としている。既存 A 系統の Stop エントリは `"matcher": ".*"` を持つが、これは無視されるだけで害はないため触らない（B 系統の新規エントリからのみ落とす）
- **⑦ `gate-coverage-regression.sh` も最初から配線する。** §2.4 の導入段階では ⑦ の実効化を段階 2（`runs.json` が生成されるようになる段階）としているが、**配線だけは段階 0 で入れる**。対象ファイルが存在しなければ即 `exit 0` するため無害であり、「後で配線する」を残すと、本書が最大の危険と位置づける silent accumulation（§1.2）に対する唯一の能動的防波堤が**配線漏れのまま誰にも気づかれない**という、まさに同型の事故を招く。日次バッチからの呼び出し（運用ループ側）だけが段階 5 である
- `session-boundary.sh`（A 系統）は別エントリのまま残す。**並列実行なので配列上の前後関係に意味はない**が、A 系統は絶対にブロックせず、B 系統が触る `$RS_DATA_ROOT` にも書かないため、同時に走っても干渉しない（当初は「先頭に置けば順序による副作用はない」と順序を根拠にしていたが、根拠を「A 系統は書き込み先が重ならない」に差し替えた）
- `timeout` は既定 600 秒だと Stop が事実上ハングするため、全 hook で明示する（公式 Common fields: command / http / mcp\_tool の既定は 600 秒）
- **同一の `command` 文字列 + `args` を持つ handler は自動的に重複排除される**（公式）。B 系統は 8 本すべてスクリプト名が異なるため重複排除の対象にならないが、将来同じスクリプトを 2 つのイベントに配線しても、イベントが違えば別扱いである
- `permissions.allow` は unittest / パーサ実行の都度承認を消すためのもの。`deny` は既存が無いため触らない（deny が勝つので、追加時は影響を確認すること）

**★ 並列実行の確認と、設計への影響（2026-08-01 訂正）**

本書は当初、仕様リファレンス §1.7 の "Multiple hooks on same event run sequentially (not parallel)" を引いて**逐次実行を前提**にしていた。公式ドキュメント（[hooks リファレンス](https://code.claude.com/docs/en/hooks) "Hook handler fields" 節）を確認したところ、記載は逆である。

> All matching hooks run in parallel, and identical handlers are deduplicated automatically. Command hooks are deduplicated by command string and `args`, and HTTP hooks are deduplicated by URL.

**仕様リファレンス §1.7 が誤り**である（本書が確認した仕様リファレンスの誤り 4 件のうちの 1 つ。一覧は §7.2 A9）。この 1 件は他の 3 件と違い、**記述の訂正だけでは済まない**。逐次実行を前提にした設計判断が 2 つあったためである。

| 崩れた前提 | 影響 | 対応 |
|---|---|---|
| 「Stop の 5 本は**合計**時間予算 60 秒」 | 予算の意味が変わる。並列なので待ち時間は最大値だが、5 本が同時に CPU とディスクを使う | 予算を各 hook の個別値として定義し直した（上記）。⑤ の Stop 側予算を 40 秒 → 3 秒に縮小できたため、実質的な負荷はむしろ下がる |
| **⑤ が `$RS_DATA_ROOT` を破壊的に書き換える間、④ と ⑦ が同じ `data/` を読む** | ④（整合性）と ⑦（カバレッジ回帰）が**再構築途中の中間状態**を読み、false fail / false pass を起こす。⑤ の退避・復元（S-1〜S-4）は「終わったら元に戻す」保証であって、並列に読む他ゲートから中間状態を隠す保護にはならない | **⑤ を Stop では読み取り専用モードに限定**し、破壊的な R1 / R2 を Stop から外した（下記） |

**結論: Stop 配下の 5 本はすべて読み取り専用にする。** これが並列実行下で安全性を根拠づけられる唯一の単純な条件である。「ロックを取って他ゲートを待たせる」案も検討したが、5 本が同時に起動する以上 ④ / ⑦ はほぼ毎回ロック待ちか skip になり、**ゲートが事実上死ぬ**（skip した回は検査していないのに緑になる）。silent accumulation を最大の危険と位置づける本書が、その対策として skip を常態化させる設計を採ることはできない。

| Stop 配下 | 書き込み先 | 並列で安全か |
|---|---|---|
| `session-boundary.sh`（A 系統） | `.session-summaries/` 等（B 系統と重ならない） | ○ |
| ④ `gate-dataset-integrity.sh` | なし（`data/` を読むのみ） | ○ |
| ⑤ `gate-idempotency.sh`（**読み取り専用モード**） | なし（`git diff` と `tests/` の走査のみ） | ○ |
| ⑥ `gate-html-selfcontained.sh` | なし（`$RS_HTML` を読むのみ） | ○ |
| ⑦ `gate-coverage-regression.sh` | なし（`runs.json` を読むのみ） | ○ |
| ⑧ `gate-signal-tampering.sh` | なし（hooks / settings.json / workflow を読むのみ） | ○ |

`rs_stop_guard()` が書く再入カウンタは `${RS_STATE_DIR}/stop/{session_id}.{スクリプト名}.count` とスクリプト名で分かれており、並列でも競合しない（§2.2 `_common.sh`）。

#### `_common.sh`（全スクリプト共通）

```bash
#!/usr/bin/env bash
# .claude/hooks/verify/retail-stats/_common.sh
# B 系統（検証用）hooks の共通ライブラリ。source して使う。
set -euo pipefail

RS_ORG="domain-tech-collection"
RS_CODE_ROOT="scripts/retail-stats-tracker"
RS_DATA_ROOT=".companies/${RS_ORG}/docs/retail-stats/data"
RS_CATALOG=".companies/${RS_ORG}/docs/retail-domain/retail-monthly-kpi-catalog.md"
RS_DIGEST_DIR=".companies/${RS_ORG}/docs/daily-digest"
RS_HTML="docs/retail-stats/index.html"
RS_STATE_DIR=".companies/${RS_ORG}/.retail-stats-verify"

# 冪等性・再現性の比較対象（§2.3 ⑤）。実装設計 §5.1 の IDEMPOTENT_FILES と同一の 6 ファイル。
# runs.json は実行時刻を含むため必ず除外する。
# CI 側もこの定数を source して同じ集合を使うこと（§2.7 の契約）
RS_REPRO_FILES="observations.json articles.json extraction-cache.json unresolved.json manifest.json series.json"

# stdin の hook イベント JSON を 1 度だけ読み、以後は $RS_INPUT を使う
rs_read_stdin() {
  RS_INPUT=$(cat)
  export RS_INPUT
}

# JSON から dot path で値を取り出す（jq 非依存。python3 は既存 hooks も前提にしている）
rs_json() {
  python3 -c '
import sys, json
d = json.load(sys.stdin)
for k in sys.argv[1].split("."):
    if isinstance(d, dict):
        d = d.get(k, "")
    else:
        d = ""
print(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False))
' "$1" <<<"$RS_INPUT"
}

# 編集対象のファイルパス（Write / Edit / NotebookEdit 共通）
rs_file_path() {
  local p
  p=$(rs_json "tool_input.file_path")
  [[ -z "$p" ]] && p=$(rs_json "tool_input.path")
  [[ -z "$p" ]] && p=$(rs_json "tool_input.notebook_path")
  printf '%s' "$p"
}

# 本プロジェクトの管轄パスかどうか（§1.3 の必須ガード）
rs_in_scope() {
  local p="${1#./}"
  p="${p#"$PWD/"}"
  case "$p" in
    "${RS_CODE_ROOT}"/*|"${RS_DATA_ROOT}"/*|"${RS_CATALOG}"|"${RS_HTML}") return 0 ;;
    *) return 1 ;;
  esac
}

# Stop hook の再入ガード。session_id ごとに実行回数を数える（理由は §2.6）
rs_stop_guard() {
  local sid limit=2 n
  # 従: すでに stop hook 起因で継続中なら再検査しない（§2.6）
  [[ "$(rs_json "stop_hook_active")" == "true" ]] && return 1
  sid=$(rs_json "session_id"); [[ -z "$sid" ]] && sid="unknown"
  mkdir -p "${RS_STATE_DIR}/stop"
  local f="${RS_STATE_DIR}/stop/${sid}.$(basename "$0").count"
  n=$(cat "$f" 2>/dev/null || echo 0)
  n=$((n + 1)); printf '%s' "$n" > "$f"
  if (( n > limit )); then
    printf '%s %s 未解決のまま %d 回目の Stop。通過させます\n' \
      "$(date -Iseconds)" "$(basename "$0")" "$n" >> "${RS_STATE_DIR}/unresolved-stops.log"
    return 1   # 呼び出し側は exit 0 する
  fi
  return 0
}

# 変更されたファイルの一覧（作業ツリー + main からの差分）
rs_changed_files() {
  { git diff --name-only HEAD 2>/dev/null || true
    git diff --name-only main...HEAD 2>/dev/null || true
    git ls-files --others --exclude-standard 2>/dev/null || true
  } | sort -u
}

# ブロック終了。stderr が Claude に読まれる
rs_block() {
  printf '\n[retail-stats verify: %s]\n%s\n' "$(basename "$0")" "$1" >&2
  exit 2
}
```

`rs_changed_files` の内部では `|| true` を使っているが、これは NFR-10 が禁じる「**検証結果の**握り潰し」ではない。`git diff main...HEAD` は main 上では常に失敗しうるため、その失敗が「差分なし」を意味することが自明な箇所に限定している。検査本体では一切使わない（§2.2 ⑧ の `gate-signal-tampering.sh` が、この区別を機械的に監視する）。

### 2.3 hook スクリプト仕様

共通契約: stdin に hook イベント JSON（仕様 §1.3）。**exit 0 = pass / exit 2 = ブロックまたは stderr フィードバック**。全スクリプトは `set -euo pipefail`。

---

#### ① `guard-readonly-inputs.sh` — 入力の読み取り専用契約【PreToolUse】

| 項目 | 内容 |
|---|---|
| 目的 | IF-01 / 前提 13「本システムは日次ダイジェスト MD を書き換えない」の機械化 |
| 発火 | PreToolUse |
| matcher | `Write\|Edit\|NotebookEdit` |
| 入力 | `tool_input.file_path`、`agent_type`（仕様 §1.3。subagent 実行時のみ存在） |
| 出力 | JSON stdout（`permissionDecision: "deny"`）。§2.5 参照 |

判定ロジック:

```
1. rs_read_stdin
2. path = rs_file_path。空なら exit 0
3. path が $RS_DIGEST_DIR 配下でなければ exit 0（カタログは対象外。小売ドメイン室が正当に編集する）
4. agent_type を取得
   - 空（メインセッション）→ exit 0。日次ダイジェスト Skill の正当な書き込みを妨げない
   - retail-stats の maker/checker agent（$RS_AGENTS に列挙）→ 拒否
   - それ以外の agent → exit 0
5. 拒否は exit 2 ではなく JSON stdout で返す（§2.5）
```

```bash
#!/usr/bin/env bash
# .claude/hooks/verify/retail-stats/guard-readonly-inputs.sh
set -euo pipefail
source "$(dirname "$0")/_common.sh"
rs_read_stdin

RS_AGENTS="retail-stats-qa retail-stats-extractor backend-developer frontend-developer"

path=$(rs_file_path); [[ -z "$path" ]] && exit 0
case "${path#./}" in "${RS_DIGEST_DIR}"/*) ;; *) exit 0 ;; esac

agent=$(rs_json "agent_type"); [[ -z "$agent" ]] && exit 0
grep -qw -- "$agent" <<<"$RS_AGENTS" || exit 0

cat <<JSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "retail-stats-tracker は日次ダイジェスト MD を読み取り専用で扱う契約（要件 IF-01 / 前提 13）。${path} への書き込みは、ダイジェストの 3 層レビュー結果を無効化するため許可されない。パース側が入力に合わせるのが正しい方向であり、入力をパースしやすい形に書き換えてはならない。"
  }
}
JSON
exit 0
```

---

#### ② `verify-catalog-contract.sh` — カタログ IF-02 スキーマ契約【PostToolUse】

| 項目 | 内容 |
|---|---|
| 目的 | カタログ MD が IF-02 スキーマ契約を満たし続けることの保証。NFR-09（指標追加はカタログ追記のみで完結）の裏付け |
| 発火 | PostToolUse |
| matcher | `Write\|Edit` |
| 入力 | `tool_input.file_path` |
| exit | 0 = pass / 2 = stderr フィードバック（ブロックはしない。§1.3） |

`file_path` が `$RS_CATALOG` でなければ `exit 0`。一致したら `${RS_CODE_ROOT}/validate_catalog.py` を実行し、非 0 終了なら `rs_block` する。

`validate_catalog.py` の検査項目（IF-02 の全条件を機械化する）:

| # | 検査 | fail の理由コード |
|---|---|---|
| C1 | H2 の見出しテキストに `業態区分` を含むものが**ちょうど 1 個**（0 個 / 2 個以上はエラー停止） | `segment_heading_ambiguous` |
| C2 | H2 の見出しテキストに `指標定義` / `KPI 定義` / `KPI定義` のいずれかを含むものが**ちょうど 1 個** | `metric_heading_ambiguous` |
| C3 | 各 H2 配下（次の H2 まで）に MD テーブルが 1 つ以上存在する | `table_missing` |
| C4 | 業態表に必須列（`segment_id`/`業態ID`, `名称`/`正式名称`, `別名`/`表記ゆれ`, `種別`, `表示順`）が**許容名のいずれかで**揃う | `required_column_missing` |
| C5 | 指標表に必須列（`metric_id`/`KPI ID`, 名称, 別名, `単位`, `値種別`, `方向`, `既定スコープ`/`既存店/全店`, `小数桁`）が揃う | `required_column_missing` |
| C6 | `segment_id` / `metric_id` が kebab-case かつ一意 | `id_format` / `id_duplicate` |
| C7 | `単位` セルを区切り文字（`/`・読点・カンマ）でトークン分割し、**各トークン**が単位対応表（`%` / `％` / `億円` / `兆円`）のいずれかに該当する。空欄 `—` はエラー | `unit_unmapped` |
| C8 | `既定スコープ` セルが `既存店` / `全店` / `該当なし` のいずれか | `scope_unmapped` |
| C9 | `値種別` が `ratio` / `absolute`、`方向` が `higher_is_better` / `lower_is_better` / `neutral`、`小数桁` が整数 | `enum_invalid` |
| C10 | **`git show HEAD:$RS_CATALOG` と比較し、既存の `segment_id` / `metric_id` が消滅または改名されていない**（IF-02「既存 ID の意味を変更する改名を行わない」の機械化。削除は新 ID 追加 + 旧 ID 非推奨マークでのみ表現可） | `id_renamed_or_removed` |

C7 が「セル内トークンごと」なのは、現行カタログの `sales-amount-absolute` の単位セルが実際に `億円 / 兆円` の併記だからである（カタログ §2.1）。セル全体の完全一致で照合すると初日から fail する。

C10 が最も重要である。カタログは小売ドメイン室の管轄であり、本システムの都合を知らないまま改訂されうる。ID の改名は observations の natural key（`segment_id`, `metric_id` を含む）を破壊し、**過去データが静かに参照不能になる**。これは §1.2 の silent accumulation と同型の事故であり、編集の瞬間に検出しなければ後から気づけない。

stderr メッセージ例:

```
[retail-stats verify: verify-catalog-contract.sh]
IF-02 カタログ契約に違反しています（3 件）。

  [id_renamed_or_removed] metrics: 'existing-store-sales-yoy' が HEAD に存在するが現版に無い
    → 既存 ID の改名・削除は禁止（IF-02）。observations の natural key が壊れ、過去データが
      参照不能になります。新 ID を追加し、旧 ID には非推奨マークを付ける形で表現してください。
  [unit_unmapped] metrics 行 7: 単位セル '前年比%' のトークン '前年比%' が単位対応表に無い
    → 対応表は % / ％ / 億円 / 兆円 のみ。区切り文字で分割して記載してください。
  [required_column_missing] segments: '表示順' 相当の列が見つからない（許容名: 表示順）

修正後、同じ検査は Stop でも実行されます。
```

---

#### ③ `verify-parser-tests.sh` — 触ったモジュールのテスト実行【PostToolUse】

| 項目 | 内容 |
|---|---|
| 目的 | パーサ変更の即時勾配。編集から数秒で赤が返る状態を作る |
| 発火 | PostToolUse |
| matcher | `Write\|Edit` |
| 入力 | `tool_input.file_path` |
| 時間予算 | 15 秒（timeout 60 秒） |

```
1. path が $RS_CODE_ROOT 配下の *.py でなければ exit 0
2. 対応テストを解決（テストランナーは標準ライブラリ unittest。U2 で決着）:
   - retail_stats/foo.py       → tests.test_foo
   - tests/test_foo.py         → 自分自身
   - 見つからない場合          → tests パッケージ全体を discover
3. cd "$RS_CODE_ROOT" && python3 -m unittest {module} -q     （個別モジュール）
   cd "$RS_CODE_ROOT" && python3 -m unittest discover -s tests -q  （全体）
4. 非 0 なら rs_block（unittest 出力の末尾 30 行を stderr へ）
```

- `unittest` に `pytest -x` 相当の「最初の失敗で停止」は無いため、時間予算は**対象モジュールを絞ること**で確保する。全体 discover に落ちるのは対応テストが特定できなかった場合のみ
- テストが 1 件も存在しないモジュールを編集した場合は `exit 0` としつつ、stderr に警告を出す（ブロックはしない）。golden-60 が揃うまでの立ち上げ期を殺さないため。ただし §4.2 の checker はテスト不在を s1 の減点として扱う
- **テストランナーは標準ライブラリの `unittest` を使い、pytest を導入しない**（U2 で決着）。実装設計 §7.1 / P1 が外部パッケージを追加しない方針を採っており、pytest を入れると CI に `pip install` と依存ピン留めの管理が発生する。`unittest` 形式のテストは pytest でもそのまま走るため、将来 pytest へ移る余地は残る

---

#### ④ `gate-dataset-integrity.sh` — データ整合性ゲート【Stop】

| 項目 | 内容 |
|---|---|
| 目的 | L_prov（出典損失）と FR-24（未定義 ID の暗黙生成禁止）を 0 に保つ。加えて FR-09 natural key の一意性 |
| 発火 | Stop |
| 時間予算 | 3 秒（純粋な JSON 走査） |

```
1. rs_stop_guard に失敗したら exit 0
2. rs_changed_files に $RS_DATA_ROOT / $RS_CODE_ROOT が含まれなければ exit 0
3. observations.json / articles.json / unresolved.json が存在しなければ exit 0（未構築）
4. 以下を検査:
   D1 全 observation が article_id を持ち、articles.json に実在する           → L_prov
   D2 natural key (segment_id, metric_id, scope, period_key, source_authority)
      に重複が無い                                                            → FR-09
   D3 全 segment_id / metric_id がカタログに実在し、source_authority が
      IF-02 発表主体対応表の値である（自由記述の混入を防ぐ）                  → FR-24
   D4 unit / scope / period_type / extraction_method / reason_code が enum 内  → §4.2
   D5 value が null の observation は sign_only または streak_broken_months を
      持ち、needs_source_check = true である                                   → 制約 11
   D6 observations の件数が HEAD 版より減っている場合は理由の明示を要求       → 沈黙削除の検出
5. 違反があれば rs_block（違反種別ごとに件数 + 先頭 5 件の observation_id）
```

D2 の natural key は **5 要素**である（要件 v0.1.1 FR-09 / §4.2）。`source_authority` を含めないと、同一の業態・指標・期間について**発表主体が異なる統計を衝突として扱ってしまう**。協会統計（会員社ベース）と経済産業省 商業動態統計（全国調査ベース）は母集団が異なる別の量であり、一方が他方を上書きすると誤ったデータが静かに混入する（要件 7-14。カタログ §1.4 に `home-center` = 業界紙集計 / 経産省、`drugstore` = 経産省 / 個社開示 の並立が実データとして列挙されている）。4 要素で検査すると、**本来検出すべき衝突を見逃すだけでなく、正当に共存すべき 2 レコードを重複として誤検出する**。この hook は natural key の一意性そのものを検証対象にしているため、キー定義の同期漏れが最も直接的に効く箇所である。

D6 は「未解決を減らすために既存データを消す」経路を塞ぐ。データが減ることは正当でありうる（重複の縮約バグ修正など）が、**機械には善悪が判定できないためブロックして理由の明示を強制する**。判定は人間と checker に残す（P6）。

---

#### ⑤ `gate-idempotency.sh` — 冪等性・再現性ゲート【Stop（読み取り専用）/ `--full`（verify・CI）】

| 項目 | 内容 |
|---|---|
| 目的 | L_repro を 0 に保つ。NFR-06（再実行でバイト一致）/ NFR-07（重複掲載耐性）/ リスク 6（LLM の非決定性） |
| 発火 | **Stop（引数なし = 読み取り専用モード。R3 / R4 のみ）** と、**`--full`（`/retail-stats-verify` Phase 3 と CI から明示的に呼ぶ。R1 / R2 を追加）** |
| 時間予算 | Stop: 3 秒（timeout 30 秒） / `--full`: 40 秒（timeout 180 秒） |

**1 本のスクリプトを 2 モードで持つ。** §2.7 の「終了コードで合否が出る 1 本のスクリプト」という契約を壊さないため、⑤ を 2 ファイルに分割せずモード引数で切り替える。ゲート総数は 7 のまま変わらない。

```
■ 共通（両モード）— 読み取りのみ。並列実行下でも安全
1. rs_stop_guard（Stop モードのみ）/ 差分ガード（④ と同様）
2. 検査 R3: キャッシュ追記のみ
   git diff -U0 HEAD -- "$RS_DATA_ROOT/extraction-cache.json" の削除行に
   cache_key が含まれる → rs_block（リスク 6。破棄は --invalidate-cache 明示時のみ）
3. 検査 R4: 重複掲載テストの存在
   tests/ 配下に 's041442'（実測最大 6 日・非連続）を含むテストが存在しない → rs_block
4. 引数に --full が無ければ ここで exit 0（Stop はここで終わる）

■ --full のみ — $RS_DATA_ROOT を書き換える破壊的検査
5. 排他ロック（多重起動の防止。並列 hook 対策ではない。下記「なぜ Stop から外すか」）
   exec 9>"${RS_STATE_DIR}/idem.lock"
   flock -n 9 || { echo "他の冪等性検査が実行中のためスキップ" >&2; exit 0; }
6. 退避（副作用の封じ込め。下記「副作用の扱い」を必ず参照）
   BK="${RS_STATE_DIR}/idem/$$"
   rs_idem_recover_all                          # 前回の DIRTY 残骸を先に復旧（S-2）
   mkdir -p "$BK/pre" "$BK/run1"
   cp -a "$RS_DATA_ROOT"/*.json "$BK/pre/" || exit 0   # 退避できなければ検査しない（S-3）
   touch "$BK/DIRTY"                            # 復元前に落ちた場合の目印
   trap rs_idem_restore EXIT INT TERM
7. 検査 R1: 決定論性（DATA_DIR を上書きして 2 回実行する）
   python3 -m retail_stats build --rebuild --no-llm
   ( cd "$RS_DATA_ROOT" && sha256sum $RS_REPRO_FILES ) > "$BK/run1.sha"
   cp -a "$RS_DATA_ROOT"/*.json "$BK/run1/"
   python3 -m retail_stats build --rebuild --no-llm
   ( cd "$RS_DATA_ROOT" && sha256sum $RS_REPRO_FILES ) > "$BK/run2.sha"
   diff "$BK/run1.sha" "$BK/run2.sha" が非空 → rs_block
   （辞書順・タイムスタンプ混入・集合の非決定な反復が典型）
   ★ runs.json は比較対象から除外する（実行時刻を含むため必ず不一致になる）
8. 検査 R2: no-drift（作業ツリーの data/ が再生成結果と一致するか）
   $BK/pre と $BK/run1 の $RS_REPRO_FILES を 1 ファイルずつ diff
   （ディレクトリ全体の diff -rq は使わない）
   不一致 → rs_block。「コードを変えたのに data/ を更新していない」または
            「意図しない出力変化」のいずれか。同一 PR で data/ を更新するか、
            変化の理由を応答に明記すること
9. 復元（trap により、rs_block・timeout・例外のいずれでも必ず通る）
   rs_idem_restore: $RS_DATA_ROOT の *.json を消して $BK/pre から書き戻し、
                    DIRTY を削除する。ロックは exit で自動解放される
```

**なぜ R1 / R2 を Stop から外すか（2026-08-01・並列実行の判明を受けた設計変更）**

hook が**並列実行**される（§2.2 ★）以上、`$RS_DATA_ROOT` を書き換える検査を Stop に置くことはできない。⑤ が再構築している最中に ④（整合性）と ⑦（カバレッジ回帰）が同じ `data/` と `runs.json` を読み、中間状態に対して合否を出してしまう。退避・復元（S-1〜S-4）は「⑤ が終わったら元に戻る」ことしか保証せず、**並列に読む他ゲートから中間状態を隠す機能はない**。

ロックで直列化する案は採らない。5 本が同時に起動するため ④ / ⑦ はほぼ毎回ロック待ちか skip になり、待たせれば Stop の待ち時間が積み上がり、skip すれば「検査していないのに緑」が常態化する。silent accumulation を最大の危険とする本書が、その対策としてゲートの skip を常態化させることはできない。

代わりに **R1 / R2 の実行契機を「直列であることが保証された場所」に移す**。

| 契機 | R3 / R4 | R1 / R2 | 直列性の根拠 |
|---|---|---|---|
| **Stop hook** | ○ | × | 並列。読み取り専用のみ許可 |
| **`/retail-stats-verify`**（§3.1） | ○ | ○ | Skill のフェーズとして逐次実行される。⑤ の実行中に他ゲートは走らない |
| **CI（PR ゲート）** | ○ | ○ | job 内の step として逐次実行される。作業ツリーは使い捨て |

`--full` 内の `flock` は**並列 hook 対策ではなく**、`/retail-stats-verify` と CI が同一マシンでたまたま同時に走った場合や、オーナーが手動で二重起動した場合の多重破壊を防ぐための保険である。取得できなければ検査せず `exit 0` する（ここで待たないのは、Stop 経路に破壊的検査がもう無く、待つ理由がないため）。

**失うものと、それが許容できる理由**: 「data/ を更新せずにパーサを変えた」ことが応答終了の瞬間には止まらなくなる。ただし (a) `/retail-stats-verify` は §5.2 の開発ループ Phase 3 で毎周回呼ばれる (b) CI が PR マージ前に必ず実行する (c) Stop 側にも R3（キャッシュ破棄の検知）と R4（NFR-07 テストの存在）は残り、**silent に壊れやすい 2 点は即時に止まる**。合否責任を Stop に集約するという原則（§1.3）からの唯一の例外であり、例外である理由は「並列実行下では Stop で安全に実行できない検査だから」に限定される。この例外を広げないため、⑧ `gate-signal-tampering.sh` の T5 に「B 系統スクリプトが Stop 経路で `$RS_DATA_ROOT` に書き込む変更」を監視対象として追加する（§2.3 ⑧）。

**バイト一致の比較対象（`RS_REPRO_FILES`）**: `observations.json` / `articles.json` / `extraction-cache.json` / `unresolved.json` / `manifest.json` / `series.json` の **6 ファイル**。実装設計 §5.1 の `IDEMPOTENT_FILES`（バイト一致保証ありと明記された 6 ファイル）と同一集合であり、片方だけを変更してはならない。**`runs.json` は除外する。** 実行メタデータは `started_at` / `finished_at` を含むため実行のたびに必ず変わり、これを比較対象に含めると R1 も R2 も恒久的に fail する。**`diff -rq` によるデータディレクトリ全体の比較を使ってはならない**。この定数は `_common.sh` に置き、CI 側からも同じ定数を参照させる（§2.7 の契約）。

**`--out` を使わない（CLI 契約への追随）**: 本節は当初 `build --rebuild --no-llm --out "$T1"` のように出力先を一時ディレクトリへ振り分ける形で書いていたが、**`--out` は実装設計 §2.5 の CLI 引数表に存在しない**（実在するのは `--org` / `--rebuild` / `--since` / `--invalidate-cache` / `--no-llm` / `--dry-run` / `--report-json` / `--fail-on-unresolved-rate` の 8 種のみで、出力先を切り替える手段はない）。CLI 契約は実装設計に一本化されており（§2.1 / §2.7）、本書が契約外の引数を要求することはできない。実装設計へ `--out` の追加を要請する案も検討したが、実装設計（§2.5 引数表・§5.1 の CI 申し送り）と CI/CD 設計（§3.1 / §5.1）の再修正が発生する一方、得られるのは「一時ディレクトリに書ければ退避が要らない」という実装上の簡便さのみであり、**冪等性の検査そのものは退避方式でも同等に成立する**ため見送った。CI/CD 設計が既に採っている「退避 → 再実行 → 比較」に本書を揃える。

**副作用の扱い（重要・`--full` モードのみ）**: この方式は検査中に `$RS_DATA_ROOT` を**実際に上書きする**。`/retail-stats-verify` はオーナーの作業ツリー上で走るため、Git 管理下のデータが検査の副作用で書き換わる（CI では使い捨てのチェックアウトなので問題にならない）。無条件に許容できる副作用ではないため、次の 4 点で封じ込める。

| # | 措置 | 理由 |
|---|---|---|
| S-1 | 検査の**前**に `$RS_DATA_ROOT/*.json` を `$RS_STATE_DIR/idem/{pid}/pre/` へ `cp -a` で退避し、`trap rs_idem_restore EXIT INT TERM` を張る。復元は「`$RS_DATA_ROOT` 直下の `*.json` を削除 → `pre/` から書き戻す」で行い、`rm -rf` でディレクトリごと消す形にはしない（パス展開の事故が致命傷になるため） | `rs_block`（exit 2）・timeout・例外のいずれで終わっても作業ツリーが検査前の状態に戻る |
| S-2 | 退避の直後に `$BK/DIRTY` を作り、復元の最後に消す。**次回の ⑤ は `--full` / Stop のどちらで起動しても、まず `$RS_STATE_DIR/idem/*/DIRTY` の残骸を探し、あれば検査より先に `pre/` から復元する**（`rs_idem_recover_all`） | `trap` は SIGKILL（timeout の強制終了）では発火しない。この 1 点だけが trap で塞げない経路であり、次回起動時の復旧で塞ぐ。Stop モードでも復旧だけは行う（読み取り専用の原則の唯一の例外だが、これは「⑤ 自身が壊した状態を元に戻す」操作であり、他ゲートが読む状態を正しい側へ寄せる） |
| S-3 | 退避に失敗した場合（`$RS_DATA_ROOT` が無い・`cp` が失敗）は**検査を行わず `exit 0`** する。`\|\| true` での握り潰しではなく、「退避できないなら破壊的検査を始めない」という前提条件の判定である（`rs_block` もしない — 検証できないことを違反として扱わない） | 退避なしで再構築を始めることだけは絶対に避ける |
| S-4 | `git status` 上に `data/` の差分がある状態でも `pre/` からの復元によって差分の内容は保存される。ただし `mtime` は変わるため、mtime に依存する外部ツールがある場合は影響を受ける | 残余リスクとして明示する（本システム内では `manifest.json` の `mtime_date` が日付粒度であり影響しない） |

R2 の比較対象を「committed 出力」ではなく **`pre/`（検査開始時点の作業ツリー）** としたのは、`/retail-stats-verify` も CI の PR ゲートも commit / マージより前に走るためである。`git show HEAD:` と比較すると、同一 PR 内で data/ を更新する正しい是正手順（未コミットの再生成）が常に不一致と判定され、是正できないまま詰む。`pre/` と比較すれば、開発者が `build` を実行して data/ を更新した時点で一致し、ゲートを抜けられる。

- `--no-llm` で LLM 経路を切るのは、LLM 呼び出しを含めると R1 の 2 回実行が「キャッシュがある限り一致」という条件付きの検査になり、判定が曖昧になるため。LLM 経路の再現性は R3（キャッシュ追記のみ）で担保する
- **前提**: `--no-llm` は「LLM を新規に呼ばない」であって「`extraction-cache.json` のヒットを使わない」ではない（キャッシュ破棄は `--invalidate-cache` 明示時のみ — 実装設計 §2.5）。この前提が崩れると R2 は LLM 由来の observation 分だけ恒常的に不一致になる。実装時に最初に確認すべき点であり、崩れていた場合は R2 を `--no-llm` なしの実行に切り替える
- **R3 を再構築の前に評価する**のは、R3 が `git diff HEAD -- extraction-cache.json` で作業ツリーとコミット済みを比較する検査だからである。R1 の再構築を先に走らせると、比較対象が「開発者の変更」ではなく「たった今再構築した結果」になり、検査の意味が失われる。両モードで R3 が先に来る構成は、この順序を自然に保証する
- R4 は要件 NFR-07 が名指しで「この非連続 6 日ケースをテストケースに含める。連続日のみを想定した実装にしない」と要求しているものを機械化した。**要件が名指しした 1 件のテストの存在を hook で強制する**のは過剰に見えるが、これは要件が過去の実測から特定した唯一の最悪ケースであり、消えたら誰も気づかない

---

#### ⑥ `gate-html-selfcontained.sh` — 配信 HTML 自己完結性ゲート【Stop】

| 項目 | 内容 |
|---|---|
| 目的 | NFR-08（外部ネットワークアクセス無しで全機能動作）/ FR-14 / NFR-03（2 MB）/ NFR-13（色のみに依存しない）の機械化 |
| 発火 | Stop |
| 時間予算 | 3 秒 |

```
1. rs_stop_guard / $RS_HTML に差分が無ければ exit 0
2. Python 標準ライブラリ html.parser で属性ベース解析（grep では不可。理由は下記）
   H1 リソース読込属性に外部 URL が無い:
      script[src] / link[href] / img[src] / iframe[src] / source[src] / video[poster]
      が http:// https:// // で始まる → fail
      ★ a[href] は検査対象外（出典リンクは FR-17 の必須要件。ここを潰すと目的が消える）
   H2 実行時 fetch が無い: fetch( / XMLHttpRequest / importScripts( / import( / EventSource
   H3 <script type="application/json"> が 1 個以上（FR-14 のデータ埋め込み）
   H4 総サイズ <= 2 MB（NFR-03）
   H5 矢印記号（→ ← ↑ ↓ ▲ ▼）と絵文字が本文に無い（UI 方針・NFR-13。増減は符号付き数値）
   H6 <noscript> または描画失敗時メッセージが存在する（UI 方針「白画面にしない」）
3. いずれか fail → rs_block（該当行番号と要素を列挙）
```

H1 で **`a[href]` を除外する**ことが設計上の要点である。`grep -c "https://"` のような素朴な検査を置くと、出典リンク（FR-17、全データ点から到達可能であること）が違反として検出され、開発者は「検査を通すために出典リンクを消す」という**要件に真っ向から反する修正**に誘導される。検証信号が誤っていると、ループは正しく回りながら間違った場所に収束する。属性ベースで解析するコストはここで払う価値がある。

---

#### ⑦ `gate-coverage-regression.sh` — カバレッジ回帰ゲート【Stop / 日次バッチ内】

| 項目 | 内容 |
|---|---|
| 目的 | L_silent の検出。§1.2 の silent accumulation に対する唯一の能動的な防波堤 |
| 発火 | Stop（開発ループ）+ 日次バッチ内から同一スクリプトを再利用（運用ループ） |
| 時間予算 | 2 秒（`runs.json` の走査のみ） |

```
1. rs_stop_guard / runs.json が存在しなければ exit 0
2. 直近 7 実行（現在の実行を除く）の rows_parsed の中央値 M を算出
3. 判定:
   S1 今回の rows_parsed < M * 0.8              → fail（沈黙損失）
   S2 「対象セクションを検出できたファイル数 = 0」が 3 実行連続 → fail
   S3 (nfr05.denominator - nfr05.numerator) / nfr05.denominator > 0.20 → fail（NFR-05）
       ★ 分母・分子は series.json の quality.nfr05 を**そのまま読む**。
         このゲート内で計算式を再実装しない（定義の二重管理を避ける）
       ★ 単位: nfr05.denominator は**一意 URL [代表] 基準**（実装設計 §4.3.7）。
         S1 の rows_parsed は**延べ行**（実測 595 行 vs 一意 406 件）であり
         単位が異なる。両者を直接比較・加減算してはならない
       ※ permanently_unresolvable（§3.2）の除外は quality.nfr05 の**産出側**で
         適用する。このゲートでは再計算しない（実装設計への申し送り。下記）
   S4 nfr05.denominator が M_denominator（直近 7 実行の中央値）* 0.8 を下回る → fail
       out_of_scope への誤分類で分母だけが縮む事故を検出する
       （S3 と同じ一意 URL [代表] 基準。S1 の中央値 M とは別に持つ）
4. fail → rs_block。stderr に「直近 7 実行の rows_parsed [延べ行] /
   nfr05.denominator [一意 URL 代表] 推移」を
   数値で列挙する
```

**S1 と S3 で分母が異なる**ことは意図的である。S1（L_silent）は入力側の変化を見るため**延べパース行**（`rows_parsed`）を対象にし、S3（L_extract）は抽出品質を見るため**一意 URL [代表] のうち対象内のもの**に限定する。分母を揃えると、個社決算記事の増減という**本システムと無関係な変動**が抽出品質の指標に混入する（§1.2）。

**両者は「対象範囲が違う」だけでなく「単位が違う」**点に注意する。実測（計測日 2026-07-26）では延べ行 595 に対し一意 URL は 406 件であり、NFR-05 の分母 83 はこの 406 件を母集団とする値である（実装設計 §4.3.7 / `quality.duplication`）。同一記事が複数日に再掲される本システムでは延べ行と一意件数が恒常的に乖離するため、`rows_parsed` から `out_of_scope` 件数を引いて分母を作ると NFR-05 の分母とは別物になり、hook と CI と画面で違う達成率が出る。**§1.2 の L_extract も一意 URL [代表] 基準で読むこと。** 分母の定義は §4.2 の SP3 が保護対象としており（変更すれば `s3 = 0`）、単位の取り違えはその保護をすり抜ける形の実質的な定義変更になる。

**実装設計への申し送り**: S3 が `quality.nfr05` を「そのまま読む」以上、`permanently_unresolvable`（§3.2 で本書が定義する人間の判断ファイル `data/permanently-unresolvable.json`）の除外は、`quality.nfr05` を産出する側（`report.py`）で適用されている必要がある。適用箇所が本書側とバラけると、hook が読む値と画面が出す値が食い違う。段階 3（H1 の導入時）に実装設計へ反映すること。それまでは同ファイルが存在しないため、除外の有無は結果に影響しない。

S4 は v0.1.1 の分母再定義に伴って必要になった検査である。分母が可変になった以上、**分子を減らさずに分母だけを縮めれば S3 は改善する**。真の取りこぼし（`no_segment_match`）を `out_of_scope` に付け替えると、未解決率は下がり、しかも件数と原文は保持されているため FR-10 の検査も通ってしまう。分母そのものの急減を独立に監視することでこの経路を塞ぐ。設計書 §4.3.7 の判定木が `no_segment_match` と `out_of_scope` を分ける根拠であり、その判定順序には回帰テストが用意されている（設計書 `test_authority_marker_evaluated_before_company_rule`）。

中央値を使う理由: 制約 1 のとおり決算・統計章が存在しない日があり、平均だとその 0 に引きずられて閾値が下がる。中央値なら単発の 0 に鈍感で、構造的な減少には反応する。

S2 は最も危険なシナリオ（§5.3 のシナリオ 1: 章見出しの改称）に対応する。単日の 0 は正常でありうるが、3 実行連続の 0 は入力仕様が変わったことをほぼ確実に意味する。

**このゲートだけは日次バッチ（運用ループ）からも同一スクリプトを呼ぶ**。開発ループが止まっていても入力は増え続けるため、Stop hook だけでは検出機会が来ないからである。CI からの呼び出し方は ci-cd-engineer の管轄だが、**「終了コードで合否が出る 1 本のスクリプト」として提供する契約は本書が負う**（§2.7）。

---

#### ⑧ `gate-signal-tampering.sh` — 検証信号の改変検知【Stop】

| 項目 | 内容 |
|---|---|
| 目的 | 「検査を通すために検査を緩める」経路を塞ぐ。前例 §2.2 の gate-test-weakening の本プロジェクト版 |
| 発火 | Stop |
| 時間予算 | 2 秒 |

```
1. rs_stop_guard
2. git diff -U0 HEAD -- "$RS_CODE_ROOT" ".claude/hooks/verify/retail-stats" を走査
3. 以下を検出:
   T1 confidence 閾値（既定 0.70 / FR-07）の引き下げ
   T2 NFR 目標値（0.90 / 0.80 / 0.20 / 2 MB など）の緩和
   T3 unresolved への退避をスキップする分岐、unresolved.json からの行削除、
      out_of_scope 判定木（設計書 §4.3.7）の緩和 — 具体的には
      no_segment_match へ落ちる条件を狭める / out_of_scope へ落ちる条件を広げる
      変更、および permanently-unresolvable.json へのエントリ追加
      （いずれも NFR-05 の分母操作）
   T4 テストの skip / xfail 追加、assert の純減
   T5 2>/dev/null / || true / except: pass の追加（NFR-10）
   T6 本 hooks ディレクトリ自身の削除・無効化
   T7 B 系統スクリプトが Stop 経路で $RS_DATA_ROOT に書き込む変更
      （並列実行下で他ゲートに中間状態を見せる。§2.2 ★ / §2.3 ⑤）
4. 検出 → rs_block:
   「検証信号を弱める変更を検出しました。意図的な場合は、
     (a) 変更前後の値 (b) 緩和が正当である理由 (c) 代替の検証手段
     を応答に明記し、retail-stats-qa のレビューを要求してください。
     機械では意図の善悪を判定できないため、判断を人間と checker に戻します。」
```

T1 と T3 が本プロジェクト固有かつ最も起きやすい。未解決率（L_extract）を下げる方法は 3 つあり、**正しいのは 1 つだけ**である。

| 手段 | 効くところ | 正当性 |
|---|---|---|
| 正規表現ルールを増やす | 分子を減らす | **正しい**。§3.3 G2 の 3 点セットで効果を実測する |
| confidence 閾値を下げて低品質な抽出を通す | 分子を減らす | 誤り。誤抽出が増える（T1） |
| 真の取りこぼしを `out_of_scope` に付け替える | 分母を縮める | 誤り。取りこぼしが「対象外」として正当化される（T3） |

後ろ 2 つはいずれも数値上は改善に見え、grep でも見つけにくく、しかも AI にとっては圧倒的に簡単である。特に 3 つ目は要件 v0.1.1 で分母が可変になったことで生まれた新しい経路であり、**件数と原文は保持されるため FR-10（未解決行の非破棄）の検査は通ってしまう**。閾値定数と判定木を「動かしたら止まる」対象として明示的に守る必要がある。機械側の検出は ⑦ S4（分母の急減）と本ゲートの T1 / T3、判断は §4.2 の SP1 / SP2 が担う。

T5 は NFR-10 の機械化だが、`_common.sh` の `rs_changed_files` が `|| true` を使っている（§2.2）。したがって T5 は**追加された差分行**のみを対象とし、既存行は見ない。新規に握り潰しを増やすことだけを禁じる。

T7 は §2.2 ★（hook の並列実行）を受けて新設した。Stop 配下の全ゲートが読み取り専用であることが、並列実行下で ④ / ⑦ が中間状態を読まないことの唯一の根拠になっている。この不変条件は書いておくだけでは守られない — 「Stop でも冪等性を全部見たい」という一見もっともな変更で簡単に破られ、破れても症状は「たまに落ちる／たまに通る」という最も気づきにくい形で出るため、機械で守る。

### 2.4 hook 一覧と導入時期

| # | hook | イベント | 実質的な効果 | 導入段階（§6） |
|---|---|---|---|---|
| ① | guard-readonly-inputs | PreToolUse | **阻止**（ブロック可） | 段階 0 |
| ② | verify-catalog-contract | PostToolUse | フィードバック | 段階 0 |
| ③ | verify-parser-tests | PostToolUse | フィードバック | 段階 1 |
| ④ | gate-dataset-integrity | Stop | **阻止** | 段階 2 |
| ⑤ | gate-idempotency | **Stop（R3/R4 のみ）** + `--full`（verify / CI） | **阻止** | 段階 2 |
| ⑥ | gate-html-selfcontained | Stop | **阻止** | 段階 3 |
| ⑦ | gate-coverage-regression | Stop + 日次 | **阻止** | **配線 = 段階 0 / 実効化 = 段階 2 / 日次からの呼び出し = 段階 5** |
| ⑧ | gate-signal-tampering | Stop | **阻止** | 段階 1 |

⑧ を段階 1（最初期）に置くのは意図的である。検証信号を守る仕組みは、守るべき検証信号が生まれるのと同時に必要になる。後から入れると、それまでに緩められた閾値が「既存行」として免責されてしまう。

⑦ の「導入段階」が 3 つに分かれているのは、**配線・実効化・呼び出し元の追加が別の作業**だからである。配線を段階 0 に前倒しするのは §2.2 の注記に述べた理由による。実効化（`runs.json` が生成され判定が実際に走る）は段階 2、運用ループ側からの呼び出しは段階 5 に置く。**「段階 5 で入れる」とだけ書いて配線を先送りすると、設計と `settings.json` が食い違ったまま実装に渡り、発火しないゲートが仕様上は存在することになる。**

### 2.5 JSON stdout feedback の採否判断

仕様リファレンス §7.1 は「JSON stdout feedback は公式仕様（§1.5）にあるが、本リポジトリでは未使用（exit 0/2 のみ）」と記録している。本設計での採否を根拠付きで示す。

**結論: 限定採用。PreToolUse の 1 本のみで採用し、PostToolUse / Stop の全ゲートは exit 0/2 契約を維持する。**

| 用途 | 機能（仕様 §1.5） | 採否 | 根拠 |
|---|---|---|---|
| ① guard-readonly-inputs の拒否 | `hookSpecificOutput.permissionDecision: "deny"` + `permissionDecisionReason` | **採用** | exit 2 でも阻止はできるが、拒否理由が**権限系の経路**に乗り、Claude には「このツール呼び出しは許可されない」という明確な意味論で伝わる。将来 `"ask"` に切り替えてオーナー判断を挟む余地も同じ経路で開く。「エラーが起きた」ではなく「禁止されている」を表現できるのはこの形式だけである |
| 未解決分布の文脈注入 | `hookSpecificOutput.additionalContext`（PreToolUse） | **段階 6 で採用** | パーサ編集の直前に「現在の reason_code 上位 5 件と件数」を注入すれば、Claude が推測ではなく実データに基づいてルールを足せる（§3.3 の規律を仕組みで支える）。ただし実データが十分に溜まるまで注入する中身が無いため、段階 6 まで保留する |
| ②③ の検査結果 | `decision: "block"` / `systemMessage` | **不採用** | |
| ④〜⑧ のゲート結果 | `decision: "block"` + `reason` | **不採用** | |

不採用の根拠を 3 点示す。決め手は R3 である。

- **R1: 既存 21 hooks との契約統一。** 本プロジェクトの hooks は既存の A 系統と同一の `.claude/settings.json` に同居する（§1.3）。運用者が失敗を追う先が「stderr」と「stdout の JSON」に分かれると、切り分けコストが恒久的に増える。A 系統は全て stderr であり、B 系統だけ別形式にする利得はない
- **R2: Stop における追加利得がない。** Stop は exit 2 でブロック可能なイベント（仕様 §1.4）であり、`decision: "block"` + `reason` で得られる効果は exit 2 + stderr と実質同一である。表現力が増えるのは `updatedInput` / `updatedToolOutput` のような**入出力を書き換える**用途だが、検証ゲートが対象を書き換えるのは maker-checker 分離（§4）に反する。checker は直さない
- **R3（決め手）: 終了コードという合否表現を手放せない。** 本設計は「**同一スクリプトを hook としても CI ステップとしても使う**」ことを前提にしている（§2.7、特に ⑦ は日次バッチからも呼ぶ）。JSON stdout を返すには `exit 0` が必要であり、そうすると CI 側では「stdout の JSON を解釈しない限り合否が分からない」スクリプトになる。これは原則 P4「停止条件は機械的合否で表現する」を直接損なう。1 つの実行主体（Claude Code）でしか読めない構造化出力より、あらゆる実行主体が読める終了コードのほうが、検証信号としての価値が高い

補足として、`exit 2` の stderr は自由テキストであって構造化されていないが、本設計ではメッセージ書式を統一する（`[理由コード] 対象: 内容` + `→ 是正の方向`）ことで、構造化の利得の大半を stderr 内で回収する。②の stderr 例がその書式である。

### 2.6 Stop の再入ガード（`session_id` カウンタを主、`stop_hook_active` を従）

前例 §2.2 の Stop ゲートは、無限ループ防止に stdin の `.stop_hook_active` のみを参照している。**本設計は `session_id` ベースの自前カウンタを主とし、`stop_hook_active` を補助条件として併用する。**

**当初の判断とその訂正（2026-08-01）**: 本節は当初「仕様リファレンス §1.3 の stdin JSON フィールド一覧に `stop_hook_active` の記載がなく、§8『未確認・未文書化』にも挙がっていないため、存在が確認できないフィールドは読まない」として `stop_hook_active` を採用しなかった。§1.3 の Stop ブロック可否を検証する過程で公式ドキュメントを直接確認したところ、**`stop_hook_active` は Stop / SubagentStop の入力フィールドとして実在する**ことが判明した（"Stop hooks receive `stop_hook_active` … `true` when Claude Code is already continuing as a result of a stop hook"）。本節が定めていた切り替え条件（「実在が確認できた時点で差し替える」）が満たされたため、判断を訂正する。仕様リファレンス §1.3 のフィールド一覧は不完全である。

主・従の役割は次のとおり分ける。

| 機構 | 役割 | 根拠 |
|---|---|---|
| `session_id` カウンタ（`rs_stop_guard()`） | **主**。スクリプト別・セッション別に実行回数を数え、2 回を超えたら未解決である旨をログに残して通す。ブロックを伴わない実行（ゲート通過や `exit 0` 側）も数えるため、Stop ゲートの総実行回数に上限を与えられる | 仕様 §1.3 に明記の `session_id` |
| `stop_hook_active` | **従**。`true` なら「すでに stop hook 起因で継続中」と判断し、カウンタが上限未満でも再検査を打ち切って `exit 0` する。カウンタが状態ファイルの消失などで壊れた場合の二重防護 | 公式ドキュメント Stop 入力フィールド |

`rs_stop_guard()` の先頭に `rs_json "stop_hook_active"` が `true` なら `return 1`（呼び出し側は `exit 0`）を追加する。呼び出し側の記述は変更不要である。フィールドが将来消えても `rs_json` は空文字を返すだけで主のカウンタが残るため、ガードが黙って全無効化されることはない（当初の判断が避けようとしたリスクは、主・従の順序をこの向きにすることで解消している）。

さらに公式ドキュメントは **8 回連続でブロックすると Claude Code 側が hook を上書きしてターンを終了させる**と定めている。本設計の上限 2 回はこれより内側であり、上限に到達する前に必ず自前ガードが先に効く。

### 2.7 hook スクリプトと CI の関係（責務境界）

- 本書は**スクリプトの実体と、終了コードによる合否契約**を定義する
- **いつ・どの環境でそれを呼ぶか**（GitHub Actions のジョブ構成、トリガー、PR ゲート、必須チェック化）は ci-cd-engineer 管轄であり本書では定義しない
- 契約: 全 B 系統スクリプトは (a) 標準入力が空でも動作する（CI からの直接実行）、(b) 対象外なら 0 で即終了、(c) 失敗時は非 0 かつ stderr に理由、(d) 環境変数 `RS_CI=1` のときは `rs_stop_guard` を無効化して必ず全検査を実行する
- 特に ⑦ `gate-coverage-regression.sh` は日次バッチからの呼び出しが前提であり、CI 設計側に「このスクリプトを呼ぶ」ことだけを申し送る

---

## 3. SKILL カタログ

### 3.1 スキル一覧

既存 16 skill（`/company` 系）を調査した結果、retail-stats-tracker の開発・運用に相当するものは存在しない。ただし**以下は既存 skill をそのまま使い、新規に作らない**:

| 用途 | 使う既存 skill | 備考 |
|---|---|---|
| 入力（日次ダイジェスト）の生成 | `/company-daily-digest` | 本システムの上流。一切変更しない |
| 構成図が必要になった場合 | `/company-diagram-v2` | パイプライン図等。本プロジェクト専用の図生成 skill は作らない |
| タスクログ・Case Bank・報酬学習 | `/company-evolve` / `/company-cycle` | 既存の学習基盤に乗る |
| 品質ゲートのチェックリスト配置 | `/company-quality-setup` | ドキュメント側の品質ゲート |
| 活動サマリー・ダッシュボード | `/company-report` / `/company-dashboard` / `/company-today` | 新規に作らない |

新規に用意する skill は 4 本。プラグインソースは `plugins/cc-sier/skills/` に置き、`.claude/skills/` へ同期する（`.claude/rules/skill-development.md`）。

```
plugins/cc-sier/skills/
├── retail-stats-verify/      ← 停止条件スキル【段階 1】
│   ├── SKILL.md
│   └── scripts/verify.sh
├── retail-stats-build/       ← 手順スキル【段階 2】
│   ├── SKILL.md
│   └── references/run-modes.md
├── retail-stats-triage/      ← 人間の観測点スキル【段階 6】
│   ├── SKILL.md
│   └── references/reason-codes.md
└── retail-stats-rules/       ← 規約スキル【段階 1】
    ├── SKILL.md
    └── references/normalization-rules.md
```

| skill | 種別 | 責務 | フェーズ構成 |
|---|---|---|---|
| **retail-stats-verify** | 停止条件 | `scripts/verify.sh` 一発で ②〜⑧ の全検査を実行し、**終了コードで合否を返す**。LLM の目視判断を挟まない | 単一フェーズ（逐次実行 + 結果サマリー） |
| **retail-stats-build** | 手順 | 取り込みの実行と差分レポート。実行モード（incremental / `--rebuild` / `--invalidate-cache`）の選択規準を提示し、誤った `--invalidate-cache` を防ぐ | 6 フェーズ（§3.2） |
| **retail-stats-triage** | 人間の観測点 | `unresolved.json` を reason_code 別に集計し、上位パターンからルール追加候補を提示。H1（解けない／まだ解いていない）の判別をオーナーに問う | 5 フェーズ（§3.2） |
| **retail-stats-rules** | 規約 | 正規表現ルールと正規化処理の書き方の規約集。カタログ駆動の禁則（業態名・指標名のハードコード禁止 = FR-03 / NFR-09）、期間解決の規則（FR-06）、表記ゆれ正規化（FR-05）、テストの書き方 | 規約のため無フェーズ |

`retail-stats-rules` には `paths` を設定し、パーサ編集時にのみ自動発動させる（仕様 §3.1）。常時ロードさせるとコンテキストを恒常的に消費するが、規約が必要なのはコードを触るときだけである。

### 3.2 frontmatter と主要フェーズ

仕様リファレンス §3.1 の実在フィールドのみを使う。

#### `/retail-stats-verify`

```yaml
---
name: retail-stats-verify
description: >
  retail-stats-tracker の全検証ゲートを実行し、終了コードで合否を返す。
  カタログ IF-02 契約、パーサのテスト、データ整合性、冪等性・再現性、
  HTML 自己完結性、検証信号の改変、カバレッジ回帰の 7 種を逐次実行する。
  When: 「retail-stats を検証」「トラッカーの動作確認」「verify」と言われたとき、
  実装変更をコミットする前、retail-stats-qa がレビューを行うとき。
when_to_use: "キーワード: retail-stats, トラッカー検証, 冪等性, 未解決率, カバレッジ回帰"
argument-hint: "[--ci] [--only <gate-name>]"
allowed-tools: >
  Bash(bash .claude/hooks/verify/retail-stats/*)
  Bash(python3 -m unittest *)
  Bash(python3 -m retail_stats *)
  Read Glob Grep
model: sonnet
---
```

- `model: sonnet` — 実体は shell script の実行と結果の要約であり、判断がほとんど無い。強いモデルは検証**判断**（checker）に割り当てる（Osmani）
- `context: fork` は付けない。合否と findings を親コンテキストに残す必要があるため
- `disable-model-invocation` は既定（false）のまま。checker から自動的に呼ばれてよい

`scripts/verify.sh` は各ゲートを逐次実行し、**1 つでも非 0 なら全体を非 0 で終える**。ただし最初の失敗で止めず全ゲートを走らせる（`--only` 指定時を除く）。開発者が 1 往復で全ての問題を把握できるほうが、ループの回転数が上がるためである。**⑤ は必ず `--full` 付きで呼ぶ。** Stop hook では並列実行のため読み取り専用モードに限定しており（§2.2 ★ / §2.3 ⑤）、破壊的な冪等性検査（R1 / R2）が実際に走る経路はこの Skill と CI の 2 つだけである。ゲート数は 7 のまま変わらない（⑤ は 1 本のスクリプトのモード切り替え）。出力の最終行は必ず機械可読の 1 行サマリーにする:

```
RESULT gates=7 pass=5 fail=2 failed=gate-idempotency,gate-signal-tampering
```

#### `/retail-stats-build`

```yaml
---
name: retail-stats-build
description: >
  日次ダイジェストの決算・統計章を取り込み、observations を更新して
  配信 HTML を再生成する。実行モード（増分 / 全件再構築 / キャッシュ無効化）を
  選択し、差分レポートを出力する。
  When: 「トラッカーを更新」「統計を取り込み」「retail-stats build」と言われたとき。
when_to_use: "キーワード: 取り込み, 再構築, rebuild, 差分レポート, observations"
argument-hint: "[--rebuild] [--invalidate-cache] [--dry-run]"
arguments: [mode]
allowed-tools: >
  Bash(python3 -m retail_stats *)
  Bash(git diff *)
  Read Write Edit Glob Grep
model: sonnet
---
```

フェーズ構成:

```
Phase 0  モード確定    引数と直近の runs.json から incremental / rebuild を決める。
                       --invalidate-cache が指定された場合は理由を必ず問い返す
                       （リスク 6: キャッシュ破棄は再現性と LLM コストの双方を悪化させる）
Phase 1  事前検査      /retail-stats-verify の ② のみ実行（カタログ契約）。fail なら中止
Phase 2  取り込み      パーサ実行。決定論パースのみ（LLM 経路は §7 U3 が決まるまで別扱い）
Phase 3  差分レポート  新規 / 更新 / 未解決の件数、および
                       **上書きされた observation の変更前後**を全件列挙（H2）
Phase 4  事後検査      /retail-stats-verify の全ゲート。fail なら data/ を書き戻して中止
                       （NFR-12: 生成失敗時に成果物を空で上書きしない）
Phase 5  反映          差分がある場合のみ branch → commit → PR。差分 0 なら何もしない
```

Phase 4 の「fail なら書き戻す」が NFR-12 の実装である。**成果物を壊れた状態で残さない**ことは、日次で無人実行される系では致命的に重要になる。

#### `/retail-stats-triage`

```yaml
---
name: retail-stats-triage
description: >
  未解決行（unresolved.json）を reason_code 別に集計し、改善候補を提示する。
  「解けない行」と「まだ解いていない行」の判別をオーナーに問い、
  permanently_unresolvable のマークを更新する。
  When: 「未解決を見る」「トリアージ」「抽出精度を上げたい」と言われたとき、
  週次の振り返りのとき。
when_to_use: "キーワード: 未解決, unresolved, reason_code, 抽出精度, ルール追加"
allowed-tools: >
  Bash(python3 -m retail_stats *)
  Read Write Edit Glob Grep AskUserQuestion
model: opus
---
```

- `AskUserQuestion` を明示的に許可している。この skill の存在意義は**オーナーに問うこと**であり、勝手に判断してはならない（H1）
- `model: opus` — 未解決パターンからルール化可能性を見抜く作業であり、判断の比重が高い

```
Phase 0  集計         reason_code 別の件数と、同一パターンの行をクラスタリング
Phase 1  分類提示     上位 5 クラスタについて、原文行の実例 3 件と推定原因を提示
Phase 2  判別（人間）  クラスタごとにオーナーへ問う:
                       (a) ルール追加で解ける  (b) 原理的に解けない（制約 3）
                       (c) 判断保留
Phase 3  反映         (b) は permanently_unresolvable をマーク（L_extract の分母から除外）
Phase 4  バックログ化  (a) は golden ケースに実例を追加し、ルール追加タスクを起票
```

Phase 4 が §3.3 の規律に接続する。**トリアージの出口は必ず評価ケースの追加である**。ルールを先に書かせない。

#### `permanently_unresolvable` の永続化先

要件 §4.2 の `unresolved_rows` は 5 列（`id` / `digest_date` / `raw_line` / `reason_code` / `last_attempted_at`）でこのマークを持つ列を用意しておらず、実装設計にも記載がない。**要件・実装設計のスキーマを本書の都合で拡張しない**ため、別ファイルとして持つ:

```
.companies/{org}/docs/retail-stats/data/permanently-unresolvable.json
```

```json
{
  "schema_version": 1,
  "entries": [
    {
      "article_id": "3f2a9c1b7d4e6055",
      "reason": "記事タイトルに指標名も数値も含まれない（要件 制約 3）。本文取得を解禁しない限り解決不能",
      "decided_by": "SAS-Sasao",
      "decided_at": "2026-08-02"
    }
  ]
}
```

この置き方を選ぶ理由:

| 観点 | 理由 |
|---|---|
| **人間の成果物である** | 判定木が出す `reason_code` と違い、これは H1 の人間判断そのもの（§1.1）。パイプラインが自動生成する `unresolved.json` と混ぜると、**再実行のたびに人間の判断が消える**（`unresolved.json` は毎回再評価される想定であり、解決したら削除される） |
| **Git 差分でレビューできる** | 誰がいつ何を「諦めた」かが履歴に残る。分母を縮める操作である以上、証跡が要る |
| **スキーマ変更が不要** | 要件 §4.2 と実装設計の `unresolved_rows` に手を入れずに済む。列追加は 3 文書の同期が必要になる |
| **キーが安定している** | `unresolved_rows.id` は実行ごとに再生成されうるが、`article_id`（URL の SHA-256 先頭 16 桁）は不変（要件 §4.2） |

L_extract の算出時に、`article_id` がこのファイルに載っている未解決行を分母・分子の双方から除外する。**このファイル自体も §2.3 ⑧ T3 の監視対象**とし、エントリの追加は「分母を縮める変更」として理由の明示を要求する（追加が正当な操作である以上ブロックはするが、`decided_by` / `reason` が埋まっていれば応答での説明は 1 行で足りる）。

**`DATA_DIR` 直下のファイル集合との関係（3 文書の合意事項）**

CI/CD 設計 §3.1 は「`DATA_DIR` 直下のファイル一覧が期待値と完全一致しなければ hard fail」する新規ファイル検出を入れている。本ファイルは同じ `DATA_DIR` 直下に置かれるため、期待値集合に入っていないと**導入段階 6 で本ファイルが生成された日から日次 workflow が毎日落ちる**。前回のレビューで指摘された「有効化すると全 PR が恒久 fail する」ゲートと同型の事故になる。合意事項を明示する。

| ファイル | `DATA_DIR` 直下の期待値集合（8 種） | `RS_REPRO_FILES` = `IDEMPOTENT_FILES`（バイト一致比較、6 種） | 理由 |
|---|---|---|---|
| `observations.json` / `articles.json` / `extraction-cache.json` / `unresolved.json` / `manifest.json` / `series.json` | ○ | ○ | パイプラインが決定論的に再生成する |
| `runs.json` | ○ | **×** | 実行時刻（`started_at` / `finished_at`）を含み、再実行で必ず変わる |
| **`permanently-unresolvable.json`** | ○ | **×** | **人間の判断を記録するファイルであり、パイプラインが再生成するものではない。** 再構築しても内容は変わらないが、「バイト一致を保証する対象」として扱うと、人間が編集した瞬間に冪等性 fail になる |

すなわち「存在が許容される 8 種」と「バイト一致を比較する 6 種」は別の集合である。⑤ の R1 / R2 は後者だけを見るため、本ファイルの追加によって ⑤ の挙動は変わらない。実装設計 §5.1 のファイル構成表と CI/CD 設計 §3.1 の期待値にも同じ 8 種 / 6 種の切り分けを反映すること（秘書経由で両担当に連絡済み）。

### 3.3 評価データセット先行の規律（LayerX 規律の本プロジェクト版）

SWE-Skills-Bench では評価なしで書かれたスキル 49 本中 39 本が改善なし（平均 +1.2%）。前例（ai-virtual-office）はこれに対して「ギャップ記録 3 件」で応じた。本プロジェクトには**より強い形が使える**。実データが 595 行（計測日 2026-07-26）、すでに存在するからである。

#### 規律 G1: golden-60 の凍結（実装着手前に完了させる）

決算・統計章の 595 行（計測日 2026-07-26）から代表 60 行を抽出し、期待される observation を**人手で確定**して `tests/fixtures/golden-60.jsonl` に凍結する。パーサのコードを 1 行も書く前に完了させる。

選定基準（偏りが評価を無効化するため、機械的に決める）:

| 区分 | 件数 | 根拠 |
|---|---|---|
| 主要 4 業態（SC / 百貨店 / チェーンストア / コンビニ）の月次既存店指標 | 18 | NFR-04 が 90% を要求している対象そのもの |
| 複数指標を含む記事（FR-11） | 8 | `日本百貨店協会／6月の外国人売上29.8％増、客数0.5％減・客単価30.4％増` = 3 レコード |
| 期間表記の全 5 種（月次 / 決算期 / 四半期 / 半期 / 年度） | 8 | 制約 5 |
| 表記ゆれ（全角％ / 半角% / 全角数字 / `カ月`・`ヶ月`） | 6 | FR-05。実測で ％ 236 件 / % 643 件の混在（595 行 / 計測日 2026-07-26。要件 FR-05 が引用する ％ 226 件 / % 631 件は 588 行 / 計測日 2026-07-25 の値であり、母数が違うだけで矛盾ではない） |
| 定性表現のみ（`増収増益` / `横ばい`）と連続記録（`51カ月ぶりに前年割れ`） | 6 | 制約 11。`sign_only` / `streak_broken_months` |
| **発表主体が並立する行**（`百貨店／3月の販売額2.2％増の5547億円、既存店は3.4％増（経産省調べ）` と、同一業態・同一期間の協会統計） | 4 | 制約 14。**期待値は「2 レコードが共存し、どちらも上書きされない」** |
| **数値が取れないことが正解の行**（`ホームセンター月次実績＝2026年6月度`） | 4 | 制約 3。**期待値は `unresolved`（`reason_code = no_numeric`）** |
| **対象範囲外が正解の行**（`しまむら 決算／2月期増収増益` / `買い物は「コスパ」、家事は「タイパ」`） | 6 | 制約 15。**期待値は `unresolved`（`reason_code = out_of_scope`）**。うち 2 件は `4月都内物価、1.5%上昇―総務省` のような**真の取りこぼし**（期待値 `no_segment_match`）を混ぜ、両者の判別を評価する |

末尾 3 区分の 14 件が重要である。**「取れないことが正解」「別レコードとして共存するのが正解」のケースを評価データに含めない**と、評価は「取れた数」だけを報酬にしてしまい、無理に数値をひねり出す方向・母集団の違う値を 1 つに畳む方向へ最適化が進む。これは §2.3 ⑧ の T1 / T3 と同じ失敗を、評価データ側から誘発する経路である。

特に最終区分に**真の取りこぼし（`no_segment_match`）を意図的に混ぜる**ことが v0.1.1 以降の要点になる。NFR-05 の分母が可変になったため、「対象外」と「取りこぼし」の判別を誤ると未解決率が実態と乖離する。評価データにこの 2 種を並べて置いておかないと、判別の劣化を誰も検出できない。この判別は設計書 §4.3.7 の判定木が担い、判定順序には回帰テストが用意されている。

#### 規律 G2: ルール追加は実データの分布から。推測で書かない

正規表現ルールを 1 本追加するごとに、以下をコミットメッセージまたは SKILL の記録に残す:

1. 対応する未解決行の**実例**（`unresolved.json` からの引用、最低 2 件）
2. 追加前後の golden-60 通過数の**差分**
3. 595 行全件に対する未解決率（L_extract）の**変化**

3 が改善していないルールは入れない。「たぶん将来こういう表記も来るだろう」という予測でルールを増やすと、ルール集合が肥大化して保守不能になり、しかも効果は測れない。**ルールの正当性は常に実データの差分で示す。**

#### 規律 G3: SKILL 本文は評価が 3 回赤くなってから太らせる

`retail-stats-rules` の本文は、当初は骨子（カタログ駆動の禁則 + 期間解決の 5 種 + テストの書き方）だけに留める。**スキルが無いことで実際に失敗した事例が 3 件溜まるまで、網羅的な文書を書かない**（前例 §3.2 のギャップ記録と同じ規律）。

```markdown
## ギャップ記録（このスキルが無いと起きる失敗）
<!-- 本文を太らせる前に、スキルなしで実際に起きた失敗を 3 件記録する。
     3 件揃うまで本文は骨子のみに留める -->
1. [2026-XX-XX] {Claude が何をどう間違えたか / どの検証ゲートが検出したか}
2. ...
3. ...
```

効果測定: skill 追加後に、同種タスクでの hook ブロック回数と `/retail-stats-verify` の初回通過率が改善したかを task-log で確認する。

### 3.4 編集規律（テキスト学習率）

- **SKILL.md の全面リライト禁止。差分編集のみ。** cc-sier で全面リライトによる references 参照の取りこぼしが発生し、PR #251 → #253 → #254 の 3 段階ですり抜け修正を要した実例がある
- リライトが不可避な場合は `.claude/rules/skill-development.md` の手順（既存成果物の必須セクションを `grep` で事前抽出 → 新旧照合）に従う
- 1,500〜2,000 語制約・`references/` 外出しは既存ルールを踏襲する
- `plugins/cc-sier/skills/` を編集したら `.claude/skills/` に必ず同期する（CLAUDE.md 基本原則）

---

## 4. Subagent 構成（maker-checker 分離）

### 4.1 編成

既存 19 種を調査した結果、**maker は既存で全て足りる**。新規作成は checker 1 本と抽出器 1 本の計 2 本に留める。

| agent | 立場 | 新規/既存 | model | tools | 責務 |
|---|---|---|---|---|---|
| `data-architect` | maker | 既存 | opus | Read, Write, Edit, Glob, Grep, Bash | データモデル（observations / natural key / period_type）の設計判断 |
| `backend-developer` | maker | 既存 | sonnet | Read, Write, Edit, Glob, Grep, Bash | Python パーサ・正規化・upsert・CLI の実装 |
| `frontend-developer` | maker | 既存 | sonnet | Read, Write, Edit, Glob, Grep, Bash | 単一 HTML 生成器・Chart.js 埋め込み・SC-01〜SC-06 |
| `retail-domain-researcher` | maker | 既存 | sonnet | Read, Write, Edit, Glob, Grep, Bash | カタログ MD の維持（IF-02 契約の供給側）。**本システムのコードは触らない** |
| **`retail-stats-qa`** | **checker** | **新規** | **opus** | **Read, Glob, Grep, Bash（Write / Edit なし）** | `/retail-stats-verify` の実行、実装 diff の敵対的レビュー、verdict JSON の出力 |
| **`retail-stats-extractor`** | 抽出器 | **新規** | sonnet | **Read のみ** | IF-03 の LLM 抽出フォールバック。未解決行を受け取り observation 候補 JSON を返す |

#### なぜ既存の checker で足りないか

| 候補 | 却下理由 |
|---|---|
| `qa-lead` | `tools: Read, Write, Edit, Glob, Grep` — **Bash を持たない**。`/retail-stats-verify` を実行できないため、機械検証の結果ではなく読んだ印象で採点することになる。§4.2 の s1（機械検証）が原理的に埋められない |
| `lead-developer` | Write / Edit を持つ。checker が自分で直せる構造は maker-checker 分離を無効化する（Osmani） |
| `test-engineer` | 同上（Write / Edit あり）。加えて責務がテスト作成であり、テスト自体の妥当性を疑う立場に立てない |
| `general-purpose` | 汎用で足りるが、本プロジェクトの致命軸（IF-02 契約 / 冪等性 / 出典）を毎回プロンプトで注入する必要があり、注入漏れが検証の穴になる |

`retail-stats-qa` は **Bash を持ち Write / Edit を持たない**という組み合わせが要点である。既存 19 種にこの組み合わせは存在しない。

#### なぜ抽出器を分けるか

IF-03 の LLM 抽出は maker でも checker でもない第 3 の役割である。専用 agent にする理由:

- **`tools: Read` のみ**とし、Write を与えない。抽出結果を直接 `data/` に書かせず、必ず親がスキーマ検証（FR-07: 検証 NG は 1 回リトライ、以後 unresolved へ退避）を通してから書き込む。抽出器に書き込みを許すと、スキーマ違反の JSON が検証を経ずに永続化される経路ができる
- **`memory` フィールドを設定しない。** 仕様 §2.1 のとおり省略でセッションメモリのみになる。ここが本プロジェクト固有の判断で、**永続メモリは NFR-06（再現性）と正面から競合する**。抽出器が過去の抽出を記憶していると、同一入力に対する出力が「これまでに何を抽出したか」に依存し、キャッシュで封じ込めたはずの非決定性が memory 経由で復活する。抽出器は毎回まっさらであるべきである
- `model: sonnet` — NFR-11（1 日数行、キャッシュヒット率 95%）の想定下でコストを抑える。抽出品質はスキーマ検証と confidence 閾値で担保する

#### 新規 2 本のフロントマター（公式 sub-agents リファレンス "Supported frontmatter fields" の 16 種のみ）

```yaml
---
name: retail-stats-qa
description: >
  retail-stats-tracker の検証専任エージェント。/retail-stats-verify を実際に実行し、
  実装 diff を敵対的にレビューして verdict JSON を返す。
  カタログ IF-02 契約、冪等性・再現性、出典トレーサビリティ、スコープ遵守を
  致命軸として採点する。修正は行わず、必ず maker に差し戻す。
  「retail-stats のレビュー」「トラッカーの検証」「verdict」「冪等性検証」
  「出典検証」と言われたとき、または /retail-stats-build の Phase 4 から
  委譲されたときに使用する。
tools: Read, Glob, Grep, Bash
model: opus
memory: project
background: false
---
```

```yaml
---
name: retail-stats-extractor
description: >
  retail-stats-tracker の LLM 抽出フォールバック（IF-03）。決定論パースで
  未解決になった記事タイトルを受け取り、observation スキーマの JSON 配列だけを返す。
  推測で値を埋めない。タイトルに現れない情報は null とし、
  根拠となる部分文字列を raw_expression に必ず含める。
  「LLM 抽出」「フォールバック」「unresolved 行の構造化」と言われたとき、
  または /retail-stats-build から未解決行が渡されたときにのみ使用する。
tools: Read
model: sonnet
background: false
---
```

**`when_to_use:` を書かない（2026-08-01 訂正）**: 本節は当初、両 agent に `when_to_use:` を置いてトリガー語を分離していた。公式 sub-agents リファレンスの "Supported frontmatter fields" 表を確認したところ、Subagent が受け付けるのは **`name` / `description` / `tools` / `disallowedTools` / `model` / `permissionMode` / `maxTurns` / `skills` / `mcpServers` / `hooks` / `memory` / `background` / `effort` / `isolation` / `color` / `initialPrompt` の 16 種のみ**で、`when_to_use` は**含まれない**（必須は `name` と `description` の 2 種）。仕様リファレンス §2.1 の表が誤って掲載していたものであり、本書が確認した仕様リファレンスの誤り 4 件のうちの 1 つである（一覧は §7.2 A9）。

`when_to_use` は **Skill のフロントマターには実在する**（§3.2 の 3 skill での使用は正しい）。Skill 側の書式を Subagent に持ち込んだ取り違えであり、トリガー語は `description` の末尾に畳み込む形へ移した。既存 19 種の Subagent（`.claude/agents/*.md`）も `when_to_use` を使っておらず、本修正で書式が揃う。

上記 2 本で使う `name` / `description` / `tools` / `model` / `memory` / `background` は **全数を 16 種の表と突き合わせ済み**である。`disallowedTools` / `permissionMode` / `maxTurns` / `skills` / `mcpServers` / `hooks` / `effort` / `isolation` / `color` / `initialPrompt` は本設計では使わない（`tools` の allowlist で足り、`isolation: worktree` は §2.3 ⑤ の退避方式と役割が重複するため採らない）。

#### `background` フィールドの採否

仕様リファレンス §7.1 は「Subagent `background` フィールド（v2.1.218+）は本リポジトリで未使用 ⚠️ Could be added」と記録している。**本プロジェクトでは新規 2 本に `background: false` を明示する。既存 19 種には手を入れない。**

根拠: 仕様 §2.1 によれば `background` の既定値は `true` である。CLAUDE.md には Issue #618 の教訓が記録されている — headless 環境（claude-code-action）で subagent がバックグラウンド既定になり、**完了を待たずに親が終了して成果物未生成のまま success を偽装した**。

- `retail-stats-qa` の結果を待たずに親が進むと、maker-checker 分離は形だけ存在して機能しない。verdict が返る前に PR が作られる
- `retail-stats-extractor` の結果を待たなければ、そもそも抽出結果が得られない

`/retail-stats-verify` を将来 CI から回す想定（§2.7）がある以上、ローカル対話での既定挙動に依存せず**明示する**のが正しい。既存 19 種に一律で追加しないのは、本プロジェクトのスコープを超えるためである（依頼外の改善はしない）。

### 4.2 `retail-stats-qa` の合格基準（verdict JSON）

レビューは自由記述ではなく、`.claude/rules/review-pattern.md` の L2 設計を移植した **6 軸採点 + verdict JSON** で出力する。合格基準のない checker はノイズの多い損失関数となり、自己修正ループが収束しない。

```json
{
  "s1_mechanical": 0.00,
  "s2_contract": 0.00,
  "s3_idempotency": 0.00,
  "s4_provenance": 0.00,
  "s5_delivery": 0.00,
  "s6_scope": 0.00,
  "composite": 0.00,
  "verdict": "pass|fail",
  "critical_triggered": false,
  "findings": [],
  "fix_suggestions": []
}
```

| 軸 | 内容 | 致命軸 |
|---|---|---|
| `s1_mechanical` | `/retail-stats-verify` を**実際に実行**し、その結果で採点する。感想で埋めない。golden-60 の通過数、unittest の結果、②〜⑧ の 7 ゲートの合否を根拠として `findings` に転記する（① は PreToolUse でありスクリプト単体実行では検証できないため 7 ゲート） | ★ |
| `s2_contract` | IF-02 カタログ契約の遵守（FR-03: 業態名・指標名のハードコードなし / FR-24: 未定義 ID の暗黙生成なし / NFR-09: 指標追加がコード変更を要しない） | ★ |
| `s3_idempotency` | 冪等性・再現性（FR-09 natural key / NFR-06 バイト一致 / NFR-07 非連続 6 日重複 / リスク 6 キャッシュ追記のみ） | ★ |
| `s4_provenance` | 出典トレーサビリティ（FR-17 全データ点から出典到達 / FR-10 未解決行の非破棄 / NFR-10 握り潰し禁止） | |
| `s5_delivery` | 配信物の品質（NFR-08 自己完結 / FR-20 欠測を補間しない / NFR-13 色のみに依存しない / NFR-03 サイズ・初期表示） | |
| `s6_scope` | スコープ遵守（スクレイピング禁止 = 要件 §1.3 スコープ外 / ダイジェスト MD の書き換え禁止 = IF-01 / カタログへの書き込み禁止 / 依頼外の改善をしていない） | ★ |

**判定ルール**（`.claude/rules/review-pattern.md` と統一）:

- 致命軸（★）のいずれかが `< 0.5` → composite 強制 0.00、verdict = fail、`critical_triggered = true`
- それ以外は composite = 等重み平均、**`>= 0.85` で pass**

**本プロジェクト特則**（いずれも s3 = 0 の即 fail）:

| # | 特則 | 理由 |
|---|---|---|
| SP1 | confidence 閾値（FR-07 既定 0.70）の引き下げを含む diff は、golden-60 での誤抽出増加が 0 であることの実測が示されない限り s3 = 0 | 未解決率を下げる最も安易な経路。数値上は改善に見える |
| SP2 | `unresolved.json` からの行の削除、または未解決への退避をスキップする分岐の追加は s3 = 0 | FR-10 の silent fail 禁止に真っ向から反する |
| SP2b | `out_of_scope` 判定木（設計書 §4.3.7）を広げる変更は、**付け替えられた行の実例を全件列挙し、いずれも協会統計・マクロ統計ではないことが示されない限り** s3 = 0。`no_segment_match` から `out_of_scope` への付け替えは特に厳格に見る | NFR-05 の分母を縮めて未解決率を改善したように見せる経路。件数と原文は保持されるため FR-10 の検査は通ってしまい、機械側は ⑦ S4 / ⑧ T3 でしか捕まえられない |
| SP3 | NFR 目標値（90% / 80% / 20% / 2 MB）そのものの緩和、および NFR-05 の**分母定義**の変更は s3 = 0。要件の変更は checker が承認する対象ではなく、要件定義の改訂として扱う | 検証信号の定義を被験者が書き換える構造を作らない。分母が可変になった v0.1.1 以降は、目標値だけでなく分母の定義も保護対象になる |
| SP4 | テストの skip / xfail 追加、assert の純減は s1 = 0 | 前例 §4.1 と同一 |

SP1〜SP3 は §2.3 ⑧ の `gate-signal-tampering.sh` と対になっている。**機械が検出し、checker が判断する**という二段構えであり、どちらか片方では成立しない — 機械は意図を判定できず、LLM は見落とすからである。

**リトライポリシー**: fail → `findings` / `fix_suggestions` を maker に差し戻し → 自動修正 1 回 → 再採点 → それでも fail なら PR を draft のまま人間へエスカレーション（H3）。`retail-stats-qa` は Write / Edit を持たないため、checker が自分で直して pass にする経路は構造的に存在しない。

---

## 5. 開発ループの定義

本プロジェクトには**性質の異なるループが 3 本**ある。日次運用ループと開発ループは前提条件も失敗の形も違うため、別々に定義する。

### 5.1 ループ A: 日次運用ループ（データが増える）

| 項目 | 内容 |
|---|---|
| **トリガー** | `/company-daily-digest` の完了後（後続ジョブ）。毎日 |
| **実行主体** | GitHub Actions 上のバッチ（**ジョブ構成の設計は ci-cd-engineer 管轄**）。決定論パースのみ。LLM フォールバックは含めない（§7 U3） |
| **入力** | 前回実行以降に追加・更新された `docs/daily-digest/*.md`（FR-12 増分モード） |
| **検証信号** | バッチ内から `gate-dataset-integrity.sh` と `gate-coverage-regression.sh` を `RS_CI=1` で直接呼ぶ（§2.7）。加えて `runs.json` に L_silent / L_extract / L_prov を記録 |
| **失敗時の挙動** | (a) 検証 fail → **`data/` と HTML を書き戻し、commit しない**（NFR-12: 前回生成物が配信され続ける）。(b) 差分 0 → commit も PR も作らない。(c) 決算・統計章が無い日 → スキップし、スキップ日数を `runs.json` に記録（制約 1） |
| **人間の介入点** | H2（上書きされた observation の差分レポート確認）。件数 0 の日はレポートを出さない。加えて L_extract 閾値超過時に Issue が立つ（§1.1） |
| **無人化の範囲** | 決定論パースの実行・upsert・HTML 再生成まで。**判断を伴う操作は一切含めない** |

このループは**成功が静かで、失敗も静か**である。だから `gate-coverage-regression.sh` を運用ループ内から呼ぶことが必須になる。開発ループ（Stop hook）は開発者が手を動かしたときにしか発火せず、数週間コードを触らなければ検証機会が一度も来ないからである。

### 5.2 ループ B: 開発ループ（コードを変える）

| 項目 | 内容 |
|---|---|
| **トリガー** | 正規表現ルールの追加、指標・業態の追加、HTML の改修、バグ修正 |
| **実行主体** | maker subagent（backend-developer / frontend-developer / data-architect） |
| **検証信号** | ① PreToolUse（阻止）→ ②③ PostToolUse（即時フィードバック）→ ④〜⑧ Stop（阻止）→ `/retail-stats-verify` → `retail-stats-qa` の verdict JSON |
| **失敗時の挙動** | 各層で自動修正 1 回。Stop ゲートは `rs_stop_guard` により 2 回で通過し、未解決の事実を `unresolved-stops.log` に記録する（**silent skip 禁止**。通過はしても記録は残る） |
| **人間の介入点** | H3（verdict が 2 回 fail）、および ⑧ が検出した検証信号の改変 |

標準の 6 フェーズ:

```
Phase 0 設計       maker が変更設計メモを起案（対象・受入基準・golden ケースへの影響・スコープ外の明示）
Phase 1 評価先行   golden-60 に対応ケースを追加し、**先に赤くする**（§3.3 G1）。
                   ここで赤くならない変更は、検証できない変更である
Phase 2 実装       PostToolUse の ②③ が即時勾配として並走
Phase 3 機械検証   /retail-stats-verify（②〜⑧ の全 7 ゲート。⑤ は --full）
                   └ fail → Phase 2 へ（自動 1 回、2 回目 fail で Phase 0 へ戻す）
Phase 4 独立レビュー retail-stats-qa が §4.2 の verdict JSON を出力
                   └ fail → fix_suggestions を添えて Phase 2 へ（自動 1 回、2 回目で H3）
Phase 5 反映       branch → PR（verdict JSON と L_extract の変化を本文に記載）→ auto-merge
```

Phase 1 が前例（ai-virtual-office の TDD）と異なる点は、**赤くする対象が「テスト」ではなく「評価データセット」**であることである。パーサの正しさは個別の関数の振る舞いではなく、595 行の実データに対する抽出結果の質で決まる。golden-60 が赤くならない変更は、L_extract を動かさない変更であり、入れる根拠がない（§3.3 G2）。

### 5.3 ループ C: 抽出改善ループ（未解決を減らす）

本プロジェクト固有の第 3 のループ。ループ A が生んだ未解決行を、ループ B の入力に変換する。

| 項目 | 内容 |
|---|---|
| **トリガー** | 週次、または L_extract が 20% を超えて Issue が立ったとき |
| **実行主体** | オーナー + `/retail-stats-triage`（AskUserQuestion で必ず人間に問う） |
| **検証信号** | reason_code 別の分布。ルール追加前後の golden-60 通過数と L_extract の差分（§3.3 G2） |
| **失敗時の挙動** | 判断保留のクラスタは次週に持ち越す。**推測でルールを追加しない** |
| **人間の介入点** | **H1 — このループは全体が人間の介入点である。** 「解けない」と「まだ解いていない」の判別は、機械が持たない情報（記事本文が取得できないという運用上の制約）に依存する |

このループを自動化しないことが本設計で最も意図的な選択である。自動化すると、AI は「解けない行」に対しても解こうとし続け、無理な正規表現が積み上がり、誤抽出が増え、しかも L_extract は下がって見える。

### 5.4 「無人で間違え続ける」具体的シナリオと検知手段

| # | シナリオ | なぜ静かに進行するか | 検知 | 残余リスク |
|---|---|---|---|---|
| S1 | **章見出しの改称**。ダイジェスト側が「決算・統計」を「決算/統計」等に変更 | パースは例外を出さず 0 行になる。observations は増えないだけ。HTML は古いデータで正常表示され続ける | ⑦ S2（対象セクション 0 件が 3 実行連続）+ S1（中央値比 -20%） | 改称が段階的で減少が緩やかな場合、中央値も追随して下がる。四半期ごとに絶対値を人間が確認する |
| S2 | **カタログの列名変更**。小売ドメイン室が `KPI ID` を別名に変更 | FR-24 でエラー停止する設計だが、CI 側が `\|\| true` で握り潰すと success になる | ② C4/C5（編集の瞬間）+ ⑧ T5（握り潰しの新規追加を禁止） | ci-cd-engineer 管轄の workflow 側に握り潰しが入る経路。CI 設計へ申し送る（§7 U4） |
| S3 | **カタログの ID 改名**。`existing-store-sales-yoy` の改名で過去の natural key が孤児化 | 新 ID で新規レコードが作られ、件数は増える。古い系列は増えなくなるだけで、エラーは出ない | ② C10（HEAD との ID 差分）+ ④ D3（未定義 ID 参照） | 改名と同時に旧 ID のデータも消された場合は ④ D6 が拾う |
| S4 | **閾値の切り下げ**。confidence 閾値を 0.70 → 0.50 に下げて未解決率を改善したように見せる | 全ての指標が改善方向に動く。誤抽出は個別に見ないと分からない | ⑧ T1（機械検出）+ §4.2 SP1（checker の判断） | golden-60 に誤抽出ケースが含まれていないと、checker も見抜けない。§3.3 G1 の末尾 3 区分 14 件が防衛線 |
| S5 | **LLM 抽出のドリフト**。`--invalidate-cache` が習慣化し、再実行のたびに値が微妙に変わる | 各回の出力は妥当に見える。時系列で見て初めて揺れが分かる | ⑤ R3（キャッシュの削除行を検出）+ `/retail-stats-build` Phase 0 での理由の問い返し | キャッシュファイルごと作り直された場合。Git 履歴で追える |
| S6 | **観測されない成功**。PR が毎日自動マージされ、誰も差分レポートを読まない | 何も壊れていないため、読まない習慣が定着する。壊れた日も読まれない | H2 を「件数 0 の日はレポートを出さない」設計にし、**レポートの存在自体を異常の合図にする** | 例外通知が多すぎると同じ問題が再発する。閾値は運用開始後に調整 |

S6 への対処が設計上の要点である。常時ダッシュボードは観測面として機能しない（§1.1）。**通知の希少性そのものが観測の質**である。

---

## 6. 導入ロードマップ

**最初から全部入れない。** 検証信号が揃う前に自動化を入れることが最大のアンチパターンである（原則 P6）。各段階の完了条件を満たすまで次に進まない。

| 段階 | 導入するもの | 完了条件 |
|---|---|---|
| **段階 0**<br>実装着手前 | ① guard-readonly-inputs / ② verify-catalog-contract（+ `validate_catalog.py`）/ `_common.sh` / settings.json 配線 / **golden-60 の凍結**（§3.3 G1） | (a) 現行カタログが C1〜C10 を全て pass する（**実装前にカタログ側の不整合を出し切る**）(b) golden-60 の期待値が人手で確定し、末尾 3 区分 14 件（`no_numeric` / `out_of_scope` / 発表主体並立）を含む (c) ダイジェストへの書き込みが実際に拒否されることを確認 |
| **段階 1**<br>PoC（要件 §8-3） | ③ verify-parser-tests / ⑧ gate-signal-tampering / `/retail-stats-verify` 骨格 / `/retail-stats-rules` 骨子 / **`tests/` パッケージの整備（unittest。外部依存なし）** | (a) 595 行を全件処理し、`out_of_scope` を分離した上で reason_code 別の未解決分布が出る (b) golden-60 の通過数が測定できる (c) NFR-04（主要 4 業態 90%）/ NFR-05（**対象内行**の未解決 20% 以下）の**達成可否を判定できる**。達成そのものは条件にしない — 判定できることが PoC の目的 |
| **段階 2**<br>MVP コア | ④ gate-dataset-integrity / ⑤ gate-idempotency / `retail-stats-qa`（§4.2 verdict JSON 込み）/ `/retail-stats-build`（Phase 0-3） | (a) 非連続 6 日重複ケース（`s041442`）のテストが green (b) 再実行で `observations.json` がバイト一致 (c) 出典を持たない observation が 0 件 (d) `retail-stats-qa` が実際に verdict JSON を返す |
| **段階 3**<br>配信 | ⑥ gate-html-selfcontained / HTML 生成器 / SC-01〜SC-03・SC-05 | (a) `file://` で開いて全機能が動作 (b) 2 MB 以内 (c) 出典リンク（`a[href]`）が外部 URL として残ったまま H1 を pass する — **検査が要件を殺していないことの確認** |
| **段階 4**<br>LLM フォールバック | `retail-stats-extractor` / 抽出キャッシュ / FR-07 スキーマ検証 + 1 回リトライ | (a) 同一 URL の再実行がキャッシュヒットし LLM を呼ばない (b) スキーマ検証 NG が unresolved へ退避される (c) §7 U3（実行主体）が決着している |
| **段階 5**<br>日次自動化 | ⑦ gate-coverage-regression / 日次バッチからの検証呼び出し<br>**（workflow 本体は ci-cd-engineer 管轄）** | (a) 段階 1〜4 の検証信号が全て稼働している (b) 検証 fail 時に成果物が書き戻され、前回 HTML が配信され続けることを実際に確認 (c) 章欠落日（制約 1 の実例日）でスキップが正しく記録される |
| **段階 6**<br>改善ループ運用 | `/retail-stats-triage` / `permanently_unresolvable` マーク / PreToolUse `additionalContext` 注入（§2.5） | (a) 週次トリアージが 4 週継続 (b) L_extract が永久未解決を除外した形で計算されている (c) ルール追加が §3.3 G2 の 3 点セット付きで記録されている |

段階 5（自動化）を後ろに置いているのは前例と同じ理由である。加えて本プロジェクトでは、**段階 0 の完了条件（現行カタログが契約検査を pass する）を実装着手前に置いた**ことが重要である。カタログは他部署の管轄であり、契約違反が実装中に発覚すると、パーサ側で吸収する誘惑が生まれる。それは NFR-09（指標追加がコード変更を要しない）の放棄に直結する。

### Agent Teams を使わない判断

本プロジェクトでは Agent Teams を使わない。理由:

- 実体は 1 本のバッチパイプラインであり、並列化できる独立作業が少ない（パーサ / HTML 生成 / カタログ の 3 分割が上限で、しかも順序依存がある）
- 仕様 §4.1 のとおり実験的機能であり、「タスク状態のラグ」「1 セッション 1 チーム」の制約がある。検証信号の一貫性を最優先する本設計と相性が悪い
- maker-checker の往復（§5.2 Phase 3-4）は逐次であることに意味がある。並列化すると checker が未完成の実装を採点する

`.claude/settings.json` の `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS: "1"` は組織運営（`/company`）が使うため既存のまま残す。本プロジェクトが使わないだけである。

---

## 7. 前提・制約・未決事項

### 7.1 未決事項

| # | 内容 | 影響 | 決着の期限 |
|---|---|---|---|
| ~~U1~~ | **決着済み（2026-07-26）。** 実装コードの配置は実装設計 §2.1 で `scripts/retail-stats-tracker/`（パッケージは `retail_stats/`）に確定。`_common.sh` の `RS_CODE_ROOT` と各 skill の `allowed-tools` を追随済み | — | 完了 |
| ~~U2~~ | **決着済み（2026-07-26）。** テストランナーは**標準ライブラリの `unittest`**。pytest は導入しない。根拠: 実装設計 §7.1 / P1 が外部依存を追加しない方針であり、pytest を入れると CI 側に `pip install` と依存ピン留めの管理対象が増える。`unittest` 形式は pytest でもそのまま走るため将来の移行余地は残る。③ verify-parser-tests・§2.2 permissions・skill の `allowed-tools`・段階 1 の完了条件を追随済み | — | 完了 |
| **U3** | **LLM 抽出の実行主体**（要件 未決 7-10）。GitHub Actions 上で claude-code-action を使うか、ローカル `/company` 経由の手動バッチに留めるか | 段階 4 の設計。`retail-stats-extractor` の呼び出し経路。日次バッチに LLM を含めるかは ci-cd-engineer 設計にも影響 | 段階 4 着手前 |
| **U4** | **CI 側での握り潰し防止。** ⑧ T5 は本リポジトリの `RS_CODE_ROOT` と hooks ディレクトリのみを見る。`.github/workflows/` 配下の握り潰しは検出しない | S2 の残余リスク。ci-cd-engineer へ「workflow 冒頭に `set -euo pipefail`、`\| tee` の pipefail 注意」を申し送る（CLAUDE.md に既存の教訓あり） | 段階 5 |
| **U5** | **`retail-stats-qa` の呼び出し形式。** subagent として直接呼ぶか、`/retail-stats-verify` に `context: fork` + `agent:` を設定して skill 経由にするか。仕様 §2.5 では両者が近い挙動になる | §4 の編成には影響しないが、`/retail-stats-build` Phase 4 の記述が変わる | 段階 2 |

### 7.2 仕様上の前提（仕様リファレンスに基づく）

| # | 前提 | 根拠 |
|---|---|---|
| A1 | **PostToolUse は exit 2 でもツールをブロックしない。** ②③ は「阻止」ではなく「フィードバック」であり、合否の責任は Stop に集約される | 仕様 §1.4 "Never Blockable" |
| A1-b | **Stop は exit 2 でブロック可（"Prevents Claude from stopping"）。** 合否を Stop に集約する本設計の前提。仕様リファレンス §1.1 の `Blockable = No` は誤りであり §1.4 が正しい | 公式ドキュメント "Exit code 2 behavior per event"（2026-08-01 確認。§1.3 ★ 参照） |
| A2 | **Stop の再入ガードは `session_id` ベースの自前カウンタを主とし、`stop_hook_active` を補助条件として併用する。** 併せて公式の 8 回連続上限より内側（上限 2 回）に収める | 公式ドキュメント Stop 入力フィールド（2026-08-01 確認。§2.6 参照） |
| A3 | **同一イベントにマッチする hook は並列実行される**（"All matching hooks run in parallel"）。時間予算は各 hook の個別値で、待ち時間は最大値。**Stop 配下は全て読み取り専用**でなければ相互に中間状態を見る。仕様リファレンス §1.7 の「逐次実行」は誤り | 公式ドキュメント "Hook handler fields"（2026-08-01 確認。§2.2 ★ 参照） |
| A3-b | 同一の `command` 文字列 + `args` を持つ handler は自動的に重複排除される | 同上 |
| A3-c | `Stop` は matcher 非対応。書いても silently ignored | 公式 matcher 対応表（2026-08-01 確認） |
| A4 | `hooks` は user / project / local スコープでマージされる。既存 A 系統の配列要素を消さずに追加する | 仕様 §5.1 |
| A5 | Subagent の `background` は未設定なら Claude が選択し、v2.1.198 以降は既定でバックグラウンド実行になる。待ち合わせが必要な agent には `false` を明示する | 公式 sub-agents "Supported frontmatter fields"（2026-08-01 確認）/ CLAUDE.md #618 |
| A6 | Subagent の `memory` を省略するとセッションメモリのみになる（`memory` は cross-session 学習を有効化するフィールド）。`retail-stats-extractor` はこれを利用して再現性を守る | 公式 sub-agents "Supported frontmatter fields"（2026-08-01 確認） |
| A6-b | **Subagent のフロントマターは 16 種で、`when_to_use` は存在しない**（Skill には存在する）。トリガー語は `description` に畳み込む。仕様リファレンス §2.1 の掲載は誤り | 公式 sub-agents "Supported frontmatter fields"（2026-08-01 確認。§4.1 参照） |
| A7 | Skill の `paths` は「マッチするファイルが編集されたときのみ有効化」。`retail-stats-rules` に使う | 仕様 §3.1 |
| A8 | hook の `timeout` 既定は command / http / mcp_tool で 600 秒。全 B 系統 hook で明示的に短縮する | 公式 "Common fields"（2026-08-01 確認） |
| A9 | **仕様リファレンスには確認済みの誤りが 4 件ある**（§1.1 Stop のブロック可否 / §1.3 `stop_hook_active` 欠落 / §1.7 逐次実行 / §2.1 `when_to_use`）。設計の根幹を支える仕様は公式ドキュメントで個別に裏を取る | 本書 §1.3 ★ / §2.2 ★ / §2.6 / §4.1 |

### 7.3 スコープ境界

| 領域 | 担当 | 本書での扱い |
|---|---|---|
| GitHub Actions workflow、日次自動更新のジョブ構成、PR ゲートの必須チェック化 | ci-cd-engineer（`cicd-design.md`） | **本書では設計しない。** スクリプトの終了コード契約（§2.7）のみ提供 |
| パーサのアルゴリズム、データモデルの詳細、HTML 生成器の内部構造 | system-architect（`implementation-design.md`） | 本書は検証すべき性質のみを定義。実装方法には踏み込まない |
| カタログ MD の内容 | 小売ドメイン室（retail-domain-researcher） | 本書は IF-02 契約の**検査**のみを担当。カタログの内容そのものは管轄外 |
| 要件そのもの（NFR 目標値の妥当性など） | 要件定義書 v0.1.1 | 本書は要件を検証可能な形に翻訳するのみ。§4.2 SP3 のとおり、目標値の変更は要件改訂として扱う |

---

## 8. 用語

| 用語 | 定義 |
|---|---|
| 検証 hooks（B 系統） | retail-stats-tracker の規約・データ契約を機械検証する hook。`.claude/hooks/verify/retail-stats/` 配下。exit 2 で止める |
| 観測 hooks（A 系統） | 既存 21 本の組織運営基盤 hook。Case Bank・ダッシュボード等。絶対にブロックしない |
| silent accumulation | パース失敗が例外にならず「不在」として静かに蓄積する、本プロジェクト最大の危険（§1.2） |
| L_silent / L_extract / L_repro / L_prov | 本プロジェクトの 4 つの損失関数（§1.2）。前 2 者は回帰で、後 2 者は 0/1 で判定する |
| golden-60 | 595 行（計測日 2026-07-26）から選定し期待値を人手確定した 60 件の評価データセット。**「解けないことが正解」「対象範囲外が正解」「2 レコード共存が正解」の計 14 件を含む**（§3.3 G1） |
| `out_of_scope` | 個社決算・非統計記事など、本システムの対象範囲外と**決定論的な判定木で明示的に分類**した行の reason_code（要件 v0.1.1）。NFR-05 の分母から除外されるが破棄はせず、SC-06 に取りこぼし（`no_segment_match`）と区別可能な形で独立表示される |
| `source_authority` | 統計の発表主体コード（`sc-association` / `meti` 等）。記事の掲載媒体（`source_name`）とは別物。natural key の第 5 要素であり、母集団の異なる統計を別レコードとして共存させる根拠（要件 v0.1.1 の 7-14） |
| permanently_unresolvable | 原理的に解けない未解決行に人間が付けるマーク。L_extract の分母・分子から除外される（H1）。永続化先は `data/permanently-unresolvable.json`（`article_id` をキーとする人間の判断ファイル。§3.2） |
| 検証信号の改変 | 閾値の引き下げ・unresolved の削除・NFR 目標値の緩和など、検査を通すために検査を緩める変更。⑧ が検出し checker が判断する |
| verdict JSON | `retail-stats-qa` が出力する 6 軸採点 + 合否の構造化出力（§4.2） |
| H1 / H2 / H3 | 人間に固定的に残すトリアージ点（§1.1） |
