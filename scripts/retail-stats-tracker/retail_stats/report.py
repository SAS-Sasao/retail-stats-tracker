"""実行サマリー・reason_code 分布・上書き差分の整形（FR-22）。実装設計 §6。

依存先: models のみ。series.json の `quality` オブジェクトを産出する側
（実装設計 §6.1 のスキーマ例）。loop-engineering-design.md §1.2 の
L_extract（NFR-05 未解決率）は本モジュールが出す `quality.nfr05` を
そのまま読む設計であり、hook 側で式を再実装しない。

`quality` の構造（実装設計 §6.1 のサンプルに準拠）:
    by_method:              {"deterministic": N, "llm": N, "manual": N}
    by_reason_code:         REASON_CODES 7 値それぞれの件数（out_of_scope
                             を含む合計 = meta.unresolved_count）
    nfr05:                  {"denominator", "numerator", "rate", "target": 0.80,
                              "met"}。分母は発表主体が協会統計・マクロ統計で
                              ある一意 URL [代表]（out_of_scope と
                              permanently_unresolvable を除外。§1.2）
    out_of_scope_breakdown: {"company_disclosure", "non_statistical"}
    duplication:            {"unique_articles", "total_rows", "duplicate_rows",
                              "max_appeared"}
    unresolved_samples:     reason_code 別の代表例（occurrences は
                             配信用の集計値であり、永続層 unresolved.json
                             には持たせない）

`permanently_unresolvable`（人間の判断ファイル、data/permanently-unresolvable.json）
による除外は、この quality.nfr05 を産出する本モジュールで適用すること。
適用箇所が画面側とバラけると、hook が読む値と画面が出す値が食い違う
（loop-engineering-design.md §3.2 実装設計への申し送り）。
"""

from __future__ import annotations


def build_quality_summary(observations, unresolved_rows, articles, catalog) -> dict:
    """`quality` オブジェクト（実装設計 §6.1）を組み立てる。"""
    raise NotImplementedError


def build_diff_report(before: dict, after: dict) -> dict:
    """新規 / 更新 / 未解決の件数と、値が変わった observation の前後を出す
    （要件リスク 7-8、`--report-json` の出力元。FR-22）。

    件数0の日はレポートを出さない設計とする（H2 のトリアージ負荷を
    減らすため。loop-engineering-design.md §1.1）。
    """
    raise NotImplementedError


def build_run_record(run_id: str, started_at: str, finished_at: str, **stats) -> dict:
    """runs.json の1レコードを組み立てる。実行時刻を含むため冪等性比較
    （IDEMPOTENT_FILES）の対象外。カタログ改訂検知（source_sha256の変化）
    もここに記録する（実装設計 §3.3）。
    """
    raise NotImplementedError
