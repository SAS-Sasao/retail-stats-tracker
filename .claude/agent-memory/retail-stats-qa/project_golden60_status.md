---
name: golden60-status
description: golden-60（G1 評価データセット）の凍結状況と、2026-08-02 の候補選定レビューで fail 判定になった理由
metadata:
  type: project
---

golden-60 は 2026-08-02 時点で **候補選定のみ完了・期待値は未確定**（`expected: null` /
`status: needs_human_review`）。`tests/fixtures/golden-60.jsonl`（凍結先）は未作成のため
`test_golden60.TestGolden60Frozen` は skip のまま＝現時点で拘束力がない。

2026-08-02 の敵対的レビューは **fail（s2 = 0.35、致命軸）**。8 区分中 5 区分が、G1 の
選定基準表が定義した性質を実際には持っていなかった（②に対象内の複数指標行 0 件、
⑤に連続記録 0 件、⑥に発表主体並立ペア 0 組、⑦に月次統計行 0 件、③の半期/四半期が誤判定）。

**Why:** 期待値を人手で埋めた後に区分を作り直すと、オーナーの労力が丸ごと無駄になる。
選定の欠陥は凍結前に潰す必要がある。

**How to apply:** 次に golden-60 関連の diff を採点するときは、まず区分ごとに
「その区分の期待値が実際に書けるか」を 1 件ずつ確認する。件数が合っていることは
何の保証にもならない（`test_golden60` は件数しか見ていない）。詳細は
[[golden60-selection-traps]]。
