"""report.py の品質サマリー。実装設計 §6.1 / §8 M3 の完了条件。

**NFR-05 の分母・分子はここだけで計算する。** ループ設計 §2.3 ⑦ S3 が
「このゲート内で計算式を再実装しない」と定めており、hook も画面も
本モジュールの出力をそのまま読む。定義の二重管理を避けるため、
式が変わったことを検出できるようにする。
"""

import unittest

from retail_stats import catalog as catalog_mod
from retail_stats import config, report
from retail_stats.models import Observation, SourceArticle, UnresolvedRow

CATALOG = catalog_mod.load(config.catalog_path())


def obs(segment, metric, authority="sc-association", article="a" * 16, value=1.0):
    return Observation(
        observation_id="o" * 16, segment_id=segment, metric_id=metric,
        scope="existing_store", source_authority=authority, period_key="2026-06",
        period_type="month", period_start="2026-06-01", period_end="2026-06-30",
        value=value, unit="percent_yoy", streak_broken_months=None, sign_only=None,
        needs_source_check=False, raw_expression="1.0%増", article_id=article,
        extraction_method="deterministic", confidence=0.95, manual_override=False,
        first_seen_date="2026-07-25", last_updated_date="2026-07-25",
    )


def unres(reason, raw="| 1 | 記事 |", uid="u1"):
    return UnresolvedRow(id=uid, digest_date="2026-07-25", raw_line=raw,
                         reason_code=reason, last_attempted_at="2026-07-25")


def article(article_id="a" * 16, dates=("2026-07-25",)):
    return SourceArticle(article_id=article_id, url="https://x/1", title_first_seen="t",
                         title_variants=("t",), source_name="s", source_name_normalized="s",
                         first_published_date=dates[0], appeared_dates=tuple(dates))


class TestNfr05(unittest.TestCase):
    def test_out_of_scope_is_excluded_from_the_denominator(self):
        """out_of_scope だけが分母から外れる（要件 v0.1.1 の 7-15）。"""
        q = report.build_quality_summary(
            [obs("shopping-center", "existing-store-sales-yoy")],
            [unres("out_of_scope", uid="u1"), unres("no_metric_match", uid="u2")],
            [article()], CATALOG,
        )
        # 分子 1（成功した記事）+ 分母に残る失敗 1 = 2
        self.assertEqual(q["nfr05"], {
            "denominator": 2, "numerator": 1, "rate": 0.5, "target": 0.80, "met": False,
        })

    def test_in_scope_failures_all_count_toward_the_denominator(self):
        rows = [unres(code, uid=f"u{i}") for i, code in enumerate(report.IN_SCOPE_REASONS)]
        q = report.build_quality_summary([], rows, [], CATALOG)
        self.assertEqual(q["nfr05"]["denominator"], len(report.IN_SCOPE_REASONS))
        self.assertEqual(q["nfr05"]["numerator"], 0)

    def test_target_is_not_softened(self):
        """目標値の変更は要件改訂として扱う（⑧ T2 の監視対象）。"""
        self.assertEqual(report.NFR05_TARGET, 0.80)
        self.assertEqual(report.NFR04_TARGET, 0.90)

    def test_permanently_unresolvable_is_excluded_from_both_sides(self):
        """人間の判断ファイルによる除外は**この関数で**適用する（§3.2 の申し送り）。"""
        q = report.build_quality_summary(
            [obs("shopping-center", "existing-store-sales-yoy", article="b" * 16)],
            [], [article("b" * 16)], CATALOG, permanently_unresolvable={"b" * 16},
        )
        self.assertEqual(q["nfr05"]["numerator"], 0)


class TestNfr04(unittest.TestCase):
    def test_all_four_segments_required(self):
        covered = [obs(s, "existing-store-sales-yoy") for s in report.MAJOR4_SEGMENTS]
        q = report.build_quality_summary(covered, [], [], CATALOG)
        self.assertEqual(q["nfr04"]["rate"], 1.0)
        self.assertTrue(q["nfr04"]["met"])

    def test_missing_segment_is_named(self):
        covered = [obs(s, "existing-store-sales-yoy") for s in report.MAJOR4_SEGMENTS[:3]]
        q = report.build_quality_summary(covered, [], [], CATALOG)
        self.assertEqual(q["nfr04"]["missing"], ["convenience-store"])
        self.assertFalse(q["nfr04"]["met"])

    def test_other_metrics_do_not_count(self):
        """NFR-04 の対象は**月次既存店指標**であり、他の指標では代替できない。"""
        q = report.build_quality_summary(
            [obs(s, "sales-amount-yoy") for s in report.MAJOR4_SEGMENTS], [], [], CATALOG
        )
        self.assertEqual(q["nfr04"]["rate"], 0.0)


class TestBreakdowns(unittest.TestCase):
    def test_out_of_scope_breakdown_is_recomputed_not_persisted(self):
        """下位分類は永続化せず raw_line から再計算する（§4.3.7）。"""
        q = report.build_quality_summary([], [
            unres("out_of_scope", "| 1 | カスミ／6月の総売上高233億円 |", "u1"),
            unres("out_of_scope", "| 2 | 買い物は「コスパ」、家事は「タイパ」 |", "u2"),
        ], [], CATALOG)
        self.assertEqual(
            q["out_of_scope_breakdown"], {"company_disclosure": 1, "non_statistical": 1}
        )

    def test_multi_authority_segments(self):
        """要件 7-14 の効果確認。発表主体が並立する業態を名指しする。"""
        q = report.build_quality_summary([
            obs("department-store", "existing-store-sales-yoy", "department-store-association"),
            obs("department-store", "sales-amount-yoy", "meti"),
            obs("shopping-center", "existing-store-sales-yoy", "sc-association"),
        ], [], [], CATALOG)
        self.assertEqual(
            q["multi_authority_segments"],
            {"department-store": ["department-store-association", "meti"]},
        )

    def test_duplication_counts_reprints(self):
        q = report.build_quality_summary(
            [], [], [article("a" * 16, ("2026-04-15", "2026-04-16", "2026-04-23"))], CATALOG
        )
        self.assertEqual(q["duplication"],
                         {"unique_articles": 1, "total_rows": 3, "duplicate_rows": 2, "max_appeared": 3})

    def test_all_reason_codes_are_present(self):
        """7 値すべてを 0 埋めで出す（欠測と 0 件を区別する）。"""
        from retail_stats.models import REASON_CODES

        q = report.build_quality_summary([], [], [], CATALOG)
        self.assertEqual(sorted(q["by_reason_code"]), sorted(REASON_CODES))

    def test_unresolved_samples_are_capped_and_deterministic(self):
        rows = [unres("no_numeric", f"| {i} | 記事{i:02d} |", f"u{i}") for i in range(30)]
        samples = report.unresolved_samples(rows, limit=20)
        self.assertEqual(len(samples["no_numeric"]), 20)
        self.assertEqual(samples["no_numeric"], report.unresolved_samples(rows, limit=20)["no_numeric"])


class TestDiffReport(unittest.TestCase):
    """FR-22 / 要件リスク 7-8: 値が変わった observation の前後を必ず出す。"""

    def _results(self):
        from retail_stats import store

        index = {}
        created = store.upsert(index, obs("shopping-center", "existing-store-sales-yoy"))
        # 速報 → 確報の改定を模す（confidence が上がって値が変わる）
        updated = store.upsert(
            index,
            obs("shopping-center", "existing-store-sales-yoy", value=-1.9)._replace_confidence(0.99)
            if hasattr(obs("shopping-center", "existing-store-sales-yoy"), "_replace_confidence")
            else _bump(obs("shopping-center", "existing-store-sales-yoy", value=-1.9)),
        )
        return [created, updated]

    def test_value_change_is_listed_with_before_and_after(self):
        results = self._results()
        q = report.build_quality_summary([], [], [], CATALOG)
        d = report.build_diff_report(results, [], q)
        self.assertEqual(d["counts"]["created"], 1)
        self.assertEqual(d["counts"]["updated"], 1)
        self.assertEqual(len(d["value_changes"]), 1)
        change = d["value_changes"][0]
        self.assertEqual(change["before"]["value"], 1.0)
        self.assertEqual(change["after"]["value"], -1.9)
        self.assertTrue(d["has_changes"])

    def test_no_changes_means_no_report(self):
        """差分 0 の日はレポートを出さない（H2 のトリアージ負荷を減らす）。"""
        q = report.build_quality_summary([], [], [], CATALOG)
        d = report.build_diff_report([], [], q)
        self.assertFalse(d["has_changes"])

    def test_markdown_states_the_nfr_verdicts(self):
        q = report.build_quality_summary([], [], [], CATALOG)
        md = report.format_diff_report_markdown(report.build_diff_report(self._results(), [], q))
        self.assertIn("NFR-05", md)
        self.assertIn("NFR-04", md)
        self.assertIn("値が変わった観測", md)
        self.assertIn("未達", md)

    def test_manual_override_protection_is_reported(self):
        """FR-23 で保護された観測を黙って落とさない。"""
        from retail_stats import store

        index = {}
        store.upsert(index, obs("shopping-center", "existing-store-sales-yoy")
                     .__class__(**{**obs("shopping-center", "existing-store-sales-yoy").__dict__,
                                   "manual_override": True}))
        skipped = store.upsert(index, obs("shopping-center", "existing-store-sales-yoy", value=9.9))
        q = report.build_quality_summary([], [], [], CATALOG)
        d = report.build_diff_report([skipped], [], q)
        self.assertEqual(d["counts"]["skipped_manual"], 1)
        self.assertEqual(len(d["skipped_manual_keys"]), 1)


def _bump(o):
    from dataclasses import replace

    return replace(o, confidence=0.99)


if __name__ == "__main__":
    unittest.main()
