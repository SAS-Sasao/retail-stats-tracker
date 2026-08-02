# 設計成果物の出自情報

## ソース

- **リポジトリ**: https://github.com/SAS-Sasao/cc-sier-organization
- **組織**: domain-tech-collection
- **コピー日**: 2026-08-02
- **コピー元コミット**: `2da1c48844ea7cfaa07ef24b3012d3188a76c003`
- **関連 PR**: #710（設計3冊のマージ） / **関連 Issue**: #711
- **作業者**: SAS-Sasao

## コピーした成果物

| ファイル | コピー元パス | 作成日 |
|---------|------------|--------|
| `requirements.md` | `.companies/domain-tech-collection/docs/research/retail-stats-tracker-requirements.md` | 2026-07-26 |
| `implementation-design.md` | `.companies/domain-tech-collection/docs/research/retail-stats-tracker-design.md` | 2026-07-26 |
| `loop-engineering-design.md` | `.companies/domain-tech-collection/docs/research/retail-stats-tracker-loop-engineering-design.md` | 2026-07-26 |
| `cicd-design.md` | `.companies/domain-tech-collection/docs/research/retail-stats-tracker-cicd-design.md` | 2026-07-26 |
| `retail-monthly-kpi-catalog.md` | `.companies/domain-tech-collection/docs/retail-domain/retail-monthly-kpi-catalog.md` | 2026-07-26 |

コピーにあたり、5 文書間の相互参照（ファイル名によるリンク）のみを新ファイル名に機械的に置換した。それ以外の本文・数値・結論は原文のまま変更していない。

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

## 更新ルール

- 設計原本は **cc-sier 側**（`.companies/domain-tech-collection/docs/research/` および `docs/retail-domain/`）にある。本リポジトリはスナップショットである。
- 設計変更が発生した場合は cc-sier 側で更新し、このリポにも反映すること（二重管理を避けるため、原本は常に cc-sier）
- このリポで設計を直接変更した場合は、cc-sier 側にもフィードバックすること
- `origin.md` は削除しないこと（設計のトレーサビリティ維持のため）
