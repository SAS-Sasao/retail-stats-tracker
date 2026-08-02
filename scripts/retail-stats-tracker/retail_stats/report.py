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

import re
from collections import Counter

from retail_stats.models import REASON_CODES

# NFR の目標値（要件定義）。**コード側で緩めない**（⑧ T2 の監視対象）。
NFR04_TARGET = 0.90
NFR05_TARGET = 0.80

# NFR-04 の対象（要件 NFR-04「主要 4 業態の月次既存店指標」）
MAJOR4_SEGMENTS = ("shopping-center", "department-store", "chain-store", "convenience-store")
EXISTING_STORE_METRIC = "existing-store-sales-yoy"

# 分母に残る失敗（対象内）。out_of_scope だけが分母から外れる。
IN_SCOPE_REASONS = ("no_metric_match", "no_numeric", "no_segment_match", "ambiguous_period")

# out_of_scope の下位分類は**永続化しない**。raw_line から同じ判定木で
# 再計算する（§4.3.7 の「下位分類は永続化しない」）。判定木は決定論的なので
# 再計算しても結果が揺れない。
_STAT_VOCAB_RE = re.compile(
    r"既存店|売上高|売上|販売額|客数|客単価|営業利益|営業収益|供給高|物価|市場規模|店舗数"
)


def classify_out_of_scope(raw_line: str) -> str:
    """out_of_scope を「個社開示」と「非統計記事」に再分類する（§4.3.7）。"""
    return "company_disclosure" if _STAT_VOCAB_RE.search(raw_line) else "non_statistical"


def build_quality_summary(
    observations, unresolved_rows, articles, catalog, permanently_unresolvable=()
) -> dict:
    """`quality` オブジェクト（実装設計 §6.1）を組み立てる。

    **NFR-05 の分母・分子はここだけで計算する。** ループ設計 §2.3 ⑦ S3 が
    「このゲート内で計算式を再実装しない」と定めており、hook も画面も
    本関数の出力をそのまま読む。定義の二重管理を避けるため。

    `permanently_unresolvable`（人間の判断ファイルの article_id 集合）は
    **分母・分子の双方から**除外する（§3.2 の実装設計への申し送り）。
    """
    permanent = set(permanently_unresolvable)

    by_method = Counter(o.extraction_method for o in observations)
    by_reason = Counter(u.reason_code for u in unresolved_rows)

    resolved_articles = {o.article_id for o in observations} - permanent
    in_scope_failures = {
        u.id for u in unresolved_rows if u.reason_code in IN_SCOPE_REASONS
    }
    # unresolved は (article_id, reason_code) で 1 エントリなので id で数えてよい
    numerator = len(resolved_articles)
    denominator = numerator + len(in_scope_failures)
    rate = (numerator / denominator) if denominator else 0.0

    breakdown = Counter(
        classify_out_of_scope(u.raw_line)
        for u in unresolved_rows
        if u.reason_code == "out_of_scope"
    )

    appeared = [len(a.appeared_dates) for a in articles]
    total_rows = sum(appeared)

    return {
        "by_method": {k: by_method.get(k, 0) for k in ("deterministic", "llm", "manual")},
        "by_reason_code": {code: by_reason.get(code, 0) for code in REASON_CODES},
        "nfr05": {
            "denominator": denominator,
            "numerator": numerator,
            "rate": round(rate, 4),
            "target": NFR05_TARGET,
            "met": rate >= NFR05_TARGET,
        },
        "nfr04": build_nfr04_summary(observations, catalog),
        "out_of_scope_breakdown": {
            "company_disclosure": breakdown.get("company_disclosure", 0),
            "non_statistical": breakdown.get("non_statistical", 0),
        },
        "duplication": {
            "unique_articles": len(articles),
            "total_rows": total_rows,
            "duplicate_rows": total_rows - len(articles),
            "max_appeared": max(appeared) if appeared else 0,
        },
        "by_authority": dict(sorted(Counter(o.source_authority for o in observations).items())),
        "multi_authority_segments": _multi_authority_segments(observations),
    }


def build_nfr04_summary(observations, catalog) -> dict:
    """NFR-04（主要 4 業態の月次既存店指標で 90% 以上）の判定材料。

    「カバー率」は、主要 4 業態それぞれについて **existing-store-sales-yoy の
    観測が 1 件以上あるか**で数える。要件は業態横断の比較を目的にしており、
    1 業態でも欠けると比較が成立しないため。
    """
    covered = {
        seg
        for seg in MAJOR4_SEGMENTS
        for o in observations
        if o.segment_id == seg and o.metric_id == EXISTING_STORE_METRIC
    }
    rate = len(covered) / len(MAJOR4_SEGMENTS)
    return {
        "segments": list(MAJOR4_SEGMENTS),
        "covered": sorted(covered),
        "missing": sorted(set(MAJOR4_SEGMENTS) - covered),
        "observation_count": sum(
            1
            for o in observations
            if o.segment_id in MAJOR4_SEGMENTS and o.metric_id == EXISTING_STORE_METRIC
        ),
        "rate": round(rate, 4),
        "target": NFR04_TARGET,
        "met": rate >= NFR04_TARGET,
    }


def _multi_authority_segments(observations) -> dict:
    """複数の発表主体を持つ業態の一覧（要件 7-14 の効果確認）。"""
    seen: dict[str, set] = {}
    for o in observations:
        seen.setdefault(o.segment_id, set()).add(o.source_authority)
    return {seg: sorted(auth) for seg, auth in sorted(seen.items()) if len(auth) > 1}


def unresolved_samples(unresolved_rows, limit: int = 20) -> dict:
    """reason_code 別の未解決行の原文（M3 完了条件の「上位 20 件ずつ」）。"""
    samples: dict[str, list[str]] = {}
    for u in sorted(unresolved_rows, key=lambda x: (x.reason_code, x.digest_date, x.raw_line)):
        samples.setdefault(u.reason_code, [])
        if len(samples[u.reason_code]) < limit:
            samples[u.reason_code].append(u.raw_line)
    return samples


# 発表主体の表示ラベルと種別（§6.1 authorities）。IF-02 発表主体対応表に対応する。
AUTHORITY_LABELS: dict[str, tuple[str, str]] = {
    "meti": ("経済産業省（商業動態統計）", "government"),
    "mic": ("総務省", "government"),
    "sc-association": ("日本ショッピングセンター協会", "association"),
    "department-store-association": ("日本百貨店協会", "association"),
    "chain-store-association": ("日本チェーンストア協会", "association"),
    "food-service-association": ("日本フードサービス協会", "association"),
    "co-op-union": ("日本生活協同組合連合会", "association"),
    "industry-association": ("業界団体", "association"),
    "trade-press": ("業界紙（DCS）集計", "trade_press"),
    "private-research": ("民間調査機関", "private"),
}

# **集計粒度が 1 段違う segment**（カタログ §1.1 / §1.4）。
# 個別業態と同一チャートに並べない（§6.4 R6）。
DIFFERENT_GRANULARITY = ("meti-commerce-dynamics",)


def build_series(observations, articles, unresolved_rows, catalog, meta) -> dict:
    """配信 JSON（§6.1）を組み立てる。

    observations の生テーブルではなく**描画に必要な形へ整形**する（FR-13）。
    ブラウザ側のグルーピング処理を無くして初期表示 1.5 秒（NFR-03）を確実にするため。

    系列の一意キーは `(segment_id, metric_id, scope, source_authority, period_type)`。
    **同一業態・同一指標でも発表主体が異なれば別系列**になる（要件 7-14）。

    `points` に**欠測期間を含めない**（FR-20）。`periods` が全期間の軸を持ち、
    points に無い期間は「データなし」として描画される。null 埋めにしないのは、
    ライブラリ設定を誤ったときに補間が復活する経路を作らないため。
    """
    used_articles = {o.article_id for o in observations}
    by_id = {a.article_id: a for a in articles}

    grouped: dict[tuple, list] = {}
    for o in observations:
        grouped.setdefault(
            (o.segment_id, o.metric_id, o.scope, o.source_authority, o.period_type), []
        ).append(o)

    series = []
    for key in sorted(grouped):
        points = [
            {
                "period_key": o.period_key, "value": o.value, "article_id": o.article_id,
                "method": o.extraction_method, "raw": o.raw_expression,
                "streak_broken_months": o.streak_broken_months,
                "sign_only": o.sign_only, "needs_source_check": o.needs_source_check,
            }
            for o in sorted(grouped[key], key=lambda x: x.period_key)
        ]
        series.append(dict(zip(
            ("segment_id", "metric_id", "scope", "source_authority", "period_type"), key
        ), points=points))

    periods: dict[str, set] = {}
    for o in observations:
        periods.setdefault(o.period_type, set()).add(o.period_key)

    return {
        "schema_version": 1,
        "meta": meta,
        "segments": [
            {
                "segment_id": s.segment_id, "name": s.name, "entity_type": s.entity_type,
                "display_order": s.display_order,
                "default_source_authority": s.source_authority,
                # R6 / R7: 粒度が 1 段違う segment は silent に除外しない。
                # 画面のラベルで「単独表示」であることを明示する。
                "different_granularity": s.segment_id in DIFFERENT_GRANULARITY,
            }
            for s in catalog.segments
        ],
        "authorities": [
            {"source_authority": code, "label": AUTHORITY_LABELS[code][0],
             "kind": AUTHORITY_LABELS[code][1]}
            for code in sorted({o.source_authority for o in observations})
            if code in AUTHORITY_LABELS
        ],
        "metrics": [
            {"metric_id": m.metric_id, "name": m.name, "unit": m.unit,
             "value_type": m.value_type, "direction_hint": m.direction_hint,
             "precision": m.precision}
            for m in catalog.metrics
        ],
        "periods": {k: sorted(v) for k, v in sorted(periods.items())},
        "series": series,
        "articles": [
            {"article_id": a.article_id, "url": a.url, "title": a.title_first_seen,
             "source": a.source_name, "first_published_date": a.first_published_date,
             "appeared_count": len(a.appeared_dates)}
            for a in sorted(articles, key=lambda x: x.article_id)
            if a.article_id in used_articles
        ],
        "unresolved": [
            {"reason_code": u.reason_code, "digest_date": u.digest_date, "raw_line": u.raw_line,
             "out_of_scope_kind": classify_out_of_scope(u.raw_line)
             if u.reason_code == "out_of_scope" else None}
            for u in sorted(unresolved_rows, key=lambda x: (x.reason_code, x.digest_date, x.raw_line))
        ],
        "quality": build_quality_summary(observations, unresolved_rows, articles, catalog),
    }


def build_diff_report(before: dict, after: dict) -> dict:
    """新規 / 更新 / 未解決の件数と、値が変わった observation の前後を出す
    （要件リスク 7-8、`--report-json` の出力元。FR-22）。

    件数0の日はレポートを出さない設計とする（H2 のトリアージ負荷を
    減らすため。loop-engineering-design.md §1.1）。
    """
    raise NotImplementedError("M7 で実装する（実装設計 §8 M7）")


def build_run_record(run_id: str, started_at: str, finished_at: str, **stats) -> dict:
    """runs.json の1レコードを組み立てる。実行時刻を含むため冪等性比較
    （IDEMPOTENT_FILES）の対象外。カタログ改訂検知（source_sha256の変化）
    もここに記録する（実装設計 §3.3）。
    """
    raise NotImplementedError("M4 で実装する（実装設計 §8 M4）")
