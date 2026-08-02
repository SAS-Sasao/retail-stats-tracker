"""series.json + テンプレート → 単一 HTML（FR-13 / FR-14）。実装設計 §6 / §8 M6。

依存先: models, config。パース系（catalog/digest/parser/llm）には依存しない。
JSON + JS + CSS + Chart.js を単一 HTML にインライン埋め込みする
（NFR-08 自己完結。ネットワークを切った file:// でも動作すること）。

series の一意キーは (segment_id, metric_id, scope, source_authority,
period_type)。同一業態・同一指標でも発表主体が異なれば別系列になる
（要件 7-14。実装設計 §6.1）。

series[].points は欠測期間を含めない（FR-20）。periods.month が全期間の
軸を持ち、points に無い期間は「データなし」として描画される。null 埋めに
しないのは、ライブラリ設定を誤ったときに補間が復活する経路を作らないため。

禁則（実装設計 §6 / §8 M6 完了条件、テスト T-10g）:
    生成 HTML に `src="http`、`fetch(`、`import(` を含めないこと（NFR-08）
    HTML 総サイズは 2 MB 以内
    A4 横で印刷してチャートとテーブルが崩れないこと

チャート描画の禁則（実装設計 §6.4 R1〜R8、テスト T-7 / T-9）:
    R1: 発表主体が異なる系列を同一チャートに混ぜない
        （test_chart_spec_rejects_mixed_authority）
    R6: `meti-commerce-dynamics`（小売業全体）と個別業態を同一チャートに
        混ぜない（集計粒度が1段違うため。
        test_chart_spec_rejects_mixed_granularity）
    R8: parent_segment_id によるロールアップ集計を行わない
        （test_no_parent_rollup）

必須7セクション（SC-01〜SC-06。詳細 HTML の構成順序は
implementation-design.md §6 を参照。P3「対象外」パネルは
out_of_scope_breakdown を独立表示し、未解決件数（reason_code 側）と
混ぜないこと。冒頭固定文言:
「これらは抽出の失敗ではなく、本システムの対象範囲外として意図的に
除外した記事です。NFR-05 の分母には含みません。」）
"""

from __future__ import annotations

from pathlib import Path


def build_chart_spec(series: list) -> object:
    """複数系列からチャート仕様を組み立てる。R1 / R6 の禁則違反時は
    `renderable=False` とし `error_message` に理由を入れて描画しない。
    """
    raise NotImplementedError


def build_default_segment_candidates(catalog) -> list:
    """業態横並び表示の既定候補を返す。`meti-commerce-dynamics` は
    集計粒度が異なるため既定候補から除外する（R6。
    implementation-design.md §7.2 T-9
    test_meti_commerce_dynamics_excluded_from_default_segments）。
    """
    raise NotImplementedError


def build_series_json(observations, articles, quality: dict) -> dict:
    """observations.json 等から配信用 series.json を組み立てる（実装設計 §6.1）。"""
    raise NotImplementedError


def render(series_json: dict, template_path: Path, out_path: Path) -> None:
    """template.html + app.js + styles.css + vendor/chart.umd.min.js を
    インライン埋め込みし、単一 HTML として out_path に書き出す。

    一時ファイル + os.replace() でアトミックに書き出すこと（NFR-12）。
    """
    raise NotImplementedError
