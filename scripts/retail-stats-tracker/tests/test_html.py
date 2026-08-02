"""単一 HTML の自己完結性と描画規則。実装設計 §6 / §8 M6 の完了条件。

対応: T-10g（外部参照を含まない）/ §6.4 R1・R6・R8 / SC-06 の 3 パネル分離
"""

import json
import re
import tempfile
import unittest
from pathlib import Path

from retail_stats import catalog as catalog_mod
from retail_stats import config, report
from retail_stats.html import build
from retail_stats.models import Observation, SourceArticle, UnresolvedRow

CATALOG = catalog_mod.load(config.catalog_path())


def obs(segment="shopping-center", metric="existing-store-sales-yoy",
        authority="sc-association", period="2026-06", value=-1.6, streak=None):
    return Observation(
        observation_id="o" * 16, segment_id=segment, metric_id=metric,
        scope="existing_store", source_authority=authority, period_key=period,
        period_type="month", period_start=period + "-01", period_end=period + "-30",
        value=value, unit="percent_yoy", streak_broken_months=streak, sign_only=None,
        needs_source_check=False, raw_expression="6月既存店売上1.6％減",
        article_id="a" * 16, extraction_method="deterministic", confidence=0.95,
        manual_override=False, first_seen_date="2026-07-25", last_updated_date="2026-07-25",
    )


ARTICLE = SourceArticle(
    "a" * 16, "https://www.ryutsuu.biz/sales/s072477.html",
    "ショッピングセンター／6月既存店売上1.6％減", ("t",), "流通ニュース", "流通ニュース",
    "2026-07-25", ("2026-07-25", "2026-07-26"),
)
META = {"generated_from_digest_max_date": "2026-07-26", "digest_files_scanned": 102,
        "digest_files_with_section": 93, "observation_count": 1, "unresolved_count": 1,
        "catalog_sha256": "x" * 64}


def series_of(observations, unresolved=()):
    return report.build_series(observations, [ARTICLE], list(unresolved), CATALOG, META)


class TestSelfContained(unittest.TestCase):
    """NFR-08 / T-10g: ネットワークを切った file:// で動くこと。"""

    def setUp(self):
        self.html = build.render(series_of([obs()]))

    def test_no_external_or_dynamic_loading(self):
        for pattern in ('src="http', "fetch(", "import(", "@import"):
            with self.subTest(pattern=pattern):
                self.assertNotIn(pattern, self.html)

    def test_size_is_within_budget(self):
        self.assertLessEqual(len(self.html.encode("utf-8")), build.MAX_BYTES)

    def test_chartjs_is_inlined_not_referenced(self):
        self.assertIn("Chart.js v4.4.1", self.html)
        self.assertNotIn("cdn.jsdelivr.net", self.html)

    def test_source_urls_survive_the_check(self):
        """出典リンクの外部 URL は**残す**。検査が要件（FR-19）を殺していないこと。

        ループ設計 §6 段階 3 の完了条件 (c) が明示的に求めている確認。
        """
        self.assertIn("https://www.ryutsuu.biz/sales/s072477.html", self.html)

    def test_check_rejects_a_dynamic_fetch(self):
        with self.assertRaises(build.SelfContainedError):
            build.check_self_contained('<script>fetch("/x")</script>')

    def test_check_rejects_oversize(self):
        with self.assertRaises(build.SelfContainedError):
            build.check_self_contained("x" * (build.MAX_BYTES + 1))

    def test_script_close_tag_is_escaped(self):
        """JSON 内の `</script>` でスクリプト文脈を壊さない。"""
        article = SourceArticle("b" * 16, "https://x/1", "</script><b>x", ("t",), "s", "s",
                                "2026-07-25", ("2026-07-25",))
        s = report.build_series([obs()], [article, ARTICLE], [], CATALOG, META)
        html = build.render(s)
        self.assertNotIn("</script><b>x", html)


class TestChartRules(unittest.TestCase):
    """§6.4 の描画禁則。series 側で守れる部分を検査する。"""

    def test_different_authorities_become_separate_series(self):
        """R1 の前提: 発表主体が違えば別系列（同一チャートに混ざりようがない）。"""
        s = series_of([obs(segment="department-store", authority="department-store-association"),
                       obs(segment="department-store", authority="meti")])
        self.assertEqual(len(s["series"]), 2)
        self.assertEqual(
            sorted(x["source_authority"] for x in s["series"]),
            ["department-store-association", "meti"],
        )

    def test_macro_segment_is_flagged_not_dropped(self):
        """R6 / R7: 粒度が違う segment は**除外を silent にしない**。"""
        flags = {x["segment_id"]: x["different_granularity"] for x in series_of([obs()])["segments"]}
        self.assertTrue(flags["meti-commerce-dynamics"])
        self.assertFalse(flags["shopping-center"])

    def test_no_parent_rollup(self):
        """R8: parent_segment_id によるロールアップ集計を行わない。

        series には合計行を作らない。segment ごとの実測値だけを持つ。
        """
        s = series_of([obs(segment="shopping-center"), obs(segment="chain-store")])
        self.assertEqual(len(s["series"]), 2)
        self.assertNotIn("total", [x["segment_id"] for x in s["series"]])
        self.assertNotIn("parent_segment_id", json.dumps(s))

    def test_points_omit_missing_periods(self):
        """FR-20: 欠測期間を points に含めない（null 埋めで補間を復活させない）。"""
        s = series_of([obs(period="2026-04"), obs(period="2026-06")])
        self.assertEqual([p["period_key"] for p in s["series"][0]["points"]],
                         ["2026-04", "2026-06"])
        self.assertNotIn(None, [p["value"] for p in s["series"][0]["points"]])


class TestQualityPanels(unittest.TestCase):
    """SC-06 は「未解決（要改善）」と「対象外（意図的除外）」を別パネルに分ける。"""

    def test_out_of_scope_is_separated_from_failures(self):
        rows = [
            UnresolvedRow("u1", "2026-07-25", "| 1 | カスミ／6月の総売上高233億円 |",
                          "out_of_scope", "2026-07-25"),
            UnresolvedRow("u2", "2026-07-25", "| 2 | 4月都内物価―総務省 |",
                          "no_segment_match", "2026-07-25"),
        ]
        s = series_of([obs()], rows)
        kinds = {u["reason_code"]: u["out_of_scope_kind"] for u in s["unresolved"]}
        self.assertEqual(kinds["out_of_scope"], "company_disclosure")
        self.assertIsNone(kinds["no_segment_match"])
        self.assertEqual(s["quality"]["out_of_scope_breakdown"]["company_disclosure"], 1)

    def test_nfr05_is_rendered_with_its_denominator_definition(self):
        html = build.render(series_of([obs()]))
        self.assertIn("発表主体が協会統計・マクロ統計である行", html)
        self.assertIn("対象範囲外として意図的に除外した記事です", html)

    def test_quality_is_embedded_for_the_panels(self):
        s = series_of([obs()])
        for key in ("nfr05", "nfr04", "by_reason_code", "out_of_scope_breakdown"):
            self.assertIn(key, s["quality"])


class TestDeterministicOutput(unittest.TestCase):
    def test_render_is_reproducible(self):
        s = series_of([obs()])
        self.assertEqual(build.render(s), build.render(s))

    def test_build_writes_atomically(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "index.html"
            build.build(series_of([obs()]), out)
            self.assertTrue(out.is_file())
            self.assertEqual([p.name for p in Path(d).iterdir()], ["index.html"])


if __name__ == "__main__":
    unittest.main()
