# retail-stats-tracker

日次ダイジェストの「決算・統計」章を時系列データ化する小売月次統計トラッカー。
小売業界の月次既存店売上等の統計記事を決定論パース + LLM フォールバックで
構造化し、単一 HTML のトレンド可視化サイトとして配信する。

## 状態

**M1 / M2 完了、golden-60 凍結済み。次は M3（決定論パース）。**
進捗と再開点は `docs/design/origin.md` の D-E を参照。設計は
[cc-sier-organization](https://github.com/SAS-Sasao/cc-sier-organization)
リポジトリの組織「domain-tech-collection」で策定された。

## 設計書

- [要件定義書 v0.1.1](docs/design/requirements.md)
- [実装設計書](docs/design/implementation-design.md)
- [開発ループ設計書](docs/design/loop-engineering-design.md)
- [CI/CD 設計書](docs/design/cicd-design.md)
- [小売月次 KPI カタログ](docs/design/retail-monthly-kpi-catalog.md)
- [設計の出自・未決事項](docs/design/origin.md)

## セットアップ手順

```bash
# Python 3.10 以上（標準ライブラリのみ、外部パッケージ不要）
python3 --version

# テスト実行
python3 -m unittest discover -s scripts/retail-stats-tracker/tests
```

実行方法の詳細は `scripts/retail-stats-tracker/README.md` を参照。

## 実装状況

`scripts/retail-stats-tracker/retail_stats/` の各モジュールは実装設計に
基づく骨格（docstring + 関数シグネチャ）のみで、本体は未実装。
実装マイルストーンは `CLAUDE.md`「実装マイルストーン」節を参照。

## 配信先

生成した単一 HTML は **cc-sier-organization の GitHub Pages** で配信する
（要件 IF-05 / `docs/design/origin.md` D-G）。

```
公開 URL: https://sas-sasao.github.io/cc-sier-organization/retail-stats/
出力先  : {workspace}/docs/retail-stats/index.html
```

`RETAIL_STATS_WORKSPACE` で cc-sier の作業コピーを指すと、そちらの `docs/` に
書き出される。未設定なら本リポジトリの `docs/` に出るので、`file://` で開いて
ローカルプレビューできる（NFR-08 で単一 HTML に自己完結しており、
ネットワークを切っても全機能が動く）。

**M6 が未実装のため、現時点ではまだ生成されていない。**

## ライセンス・組織情報

public リポジトリ。設計のトレーサビリティは `docs/design/origin.md` を
参照。
