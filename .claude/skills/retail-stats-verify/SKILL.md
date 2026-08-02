---
name: retail-stats-verify
description: >
  retail-stats-tracker の全検証ゲートを実行し、終了コードで合否を返す。
  カタログ IF-02 契約、パーサのテスト、データ整合性、冪等性・再現性、
  HTML 自己完結性、検証信号の改変、カバレッジ回帰の 7 種を逐次実行する。
  When: 「retail-stats を検証」「トラッカーの動作確認」「verify」と言われたとき、
  実装変更をコミットする前、retail-stats-qa がレビューを行うとき。
argument-hint: "[--ci] [--only <gate-name>]"
allowed-tools: >
  Bash(bash .claude/skills/retail-stats-verify/scripts/verify.sh *)
  Bash(bash .claude/hooks/verify/retail-stats/*)
  Bash(python3 -m unittest *)
  Bash(python3 -m retail_stats *)
  Bash(python3 scripts/retail-stats-tracker/validate_catalog.py *)
  Read Glob Grep
model: sonnet
---

# retail-stats-verify（停止条件スキル）

出自: `docs/design/loop-engineering-design.md` §3.2。**停止条件スキル**であり、
合否は終了コードだけで決まる。LLM の目視判断を挟まない。

## 実行

```bash
bash .claude/skills/retail-stats-verify/scripts/verify.sh            # 全ゲート
bash .claude/skills/retail-stats-verify/scripts/verify.sh --ci       # CI モード（再入ガード無効）
bash .claude/skills/retail-stats-verify/scripts/verify.sh --only=catalog-contract
```

出力の最終行は必ず機械可読の 1 行サマリーになる。

```
RESULT gates=7 pass=2 fail=0 skip=5 failed=none
```

## このスキルの使い方（重要）

1. `scripts/verify.sh` を実行する
2. **終了コードで合否を判断する**。0 = pass / 非 0 = fail
3. fail したゲートの stderr をそのまま報告する。**要約で丸めない**
4. **合否を自分で判断し直さない。** 「実質問題ない」「軽微」といった評価を
   加えることは、このスキルが存在する意味（機械的な停止条件）を壊す

## ゲート一覧と導入段階

| ゲート名 | 検査 | 段階 | 現況 |
|---|---|---|---|
| `catalog-contract` | ② カタログ IF-02 契約（C1〜C12） | 0 | **稼働** |
| `parser-tests` | ③ unittest 一式 | 1 | **稼働** |
| `signal-tampering` | ⑧ 検証信号の改変検知（T1〜T7） | 1 | **稼働** |
| `dataset-integrity` | ④ 出典を持たない observation・未定義 ID | 2 | 未導入（skip） |
| `idempotency` | ⑤ 冪等性・再現性（**`--full`** で R1〜R4） | 2 | 未導入（skip） |
| `html-selfcontained` | ⑥ 配信 HTML の自己完結性（NFR-08） | 3 | 未導入（skip） |
| `coverage-regression` | ⑦ カバレッジ回帰（S1〜S4） | 2 | 配線のみ |

未導入のゲートは **skip として数え、pass に含めない**。「まだ入れていない」ことが
緑に見えると、段階の進行そのものが観測できなくなる。

## ⑤ を `--full` で呼ぶ理由

Stop hook は並列実行されるため（§2.2 ★ / §7.2 A3）、Stop 配下の ⑤ は
**読み取り専用モードに限定**されている。破壊的な冪等性検査（R1 = 2 回実行して
バイト一致 / R2 = committed との no-drift）が実際に走る経路は、**このスキルと CI の
2 つだけ**である。ここで `--full` を落とすと、冪等性は事実上どこでも検査されない。

## 関連

- 検査スクリプトの実体: `.claude/hooks/verify/retail-stats/`
- 終了コード契約: `docs/design/loop-engineering-design.md` §2.7
- checker: `.claude/agents/retail-stats-qa.md`（このスキルを実行して verdict を返す）
