"""store.py の upsert・冪等性・参照整合性。実装設計 §5.3〜§5.5 / §7.2。

対応: T-10e（manual_override 保護）/ T-10f（同値なら既存維持）/
      T-7 の test_association_and_meti_coexist（発表主体違いの共存）
"""

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from retail_stats import catalog as catalog_mod
from retail_stats import config, store
from retail_stats.models import Observation

CATALOG = catalog_mod.load(config.catalog_path())


def obs(**kw):
    base = dict(
        observation_id="", segment_id="shopping-center",
        metric_id="existing-store-sales-yoy", scope="existing_store",
        source_authority="sc-association", period_key="2026-06", period_type="month",
        period_start="2026-06-01", period_end="2026-06-30", value=-1.6,
        unit="percent_yoy", streak_broken_months=None, sign_only=None,
        needs_source_check=False, raw_expression="1.6%減", article_id="a" * 16,
        extraction_method="deterministic", confidence=0.95, manual_override=False,
        first_seen_date="2026-07-25", last_updated_date="2026-07-25",
    )
    base.update(kw)
    return Observation(**base)


class TestUpsert(unittest.TestCase):
    def test_created_then_unchanged_on_replay(self):
        index = {}
        self.assertEqual(store.upsert(index, obs()).action, "created")
        self.assertEqual(store.upsert(index, obs()).action, "unchanged")
        self.assertEqual(len(index), 1)

    def test_higher_confidence_wins(self):
        index = {}
        store.upsert(index, obs(confidence=0.80))
        r = store.upsert(index, obs(confidence=0.95, value=-1.7))
        self.assertEqual(r.action, "updated")
        self.assertAlmostEqual(list(index.values())[0].value, -1.7)

    def test_ties_keep_the_existing_record(self):
        """T-10f: confidence 同値・掲載日同値なら**既存を維持**する。

        完全同点で新側を採るとファイル走査順に依存し、NFR-06 が崩れる。
        """
        index = {}
        store.upsert(index, obs(value=-1.6, raw_expression="A"))
        r = store.upsert(index, obs(value=-9.9, raw_expression="B"))
        self.assertEqual(r.action, "unchanged")
        self.assertEqual(list(index.values())[0].raw_expression, "A")

    def test_manual_override_is_never_overwritten(self):
        """T-10e / FR-23: 手動補正は自動 upsert で上書きしない。"""
        index = {}
        store.upsert(index, obs(manual_override=True, value=-1.0, confidence=0.10))
        r = store.upsert(index, obs(value=-9.9, confidence=1.00))
        self.assertEqual(r.action, "skipped_manual")
        self.assertAlmostEqual(list(index.values())[0].value, -1.0)

    def test_losing_record_still_extends_the_date_range(self):
        index = {}
        store.upsert(index, obs(first_seen_date="2026-07-25"))
        store.upsert(index, obs(first_seen_date="2026-07-26", confidence=0.50))
        self.assertEqual(list(index.values())[0].last_updated_date, "2026-07-26")

    def test_association_and_meti_coexist(self):
        """T-7 / 要件 7-14: 発表主体が異なる観測は上書きされず共存する。

        4 項キーではこの 2 系列が同一キーに落ち、_wins() で毎回どちらかが消えていた。
        """
        index = {}
        store.upsert(index, obs(segment_id="department-store",
                                source_authority="department-store-association", value=3.2))
        store.upsert(index, obs(segment_id="department-store",
                                source_authority="meti", value=3.4))
        self.assertEqual(len(index), 2)
        self.assertEqual({o.source_authority for o in index.values()},
                         {"department-store-association", "meti"})

    def test_wins_does_not_consider_authority(self):
        """どちらの発表主体が「正しい」かを本システムは判定しない。"""
        a = obs(source_authority="meti", confidence=0.95)
        b = obs(source_authority="sc-association", confidence=0.95)
        self.assertFalse(store._wins(a, b))
        self.assertFalse(store._wins(b, a))


class TestArticleMerge(unittest.TestCase):
    def test_non_consecutive_dates_and_variants(self):
        """T-1 の前提: 非連続 6 日・4 variant に収束する（NFR-07）。"""
        index = {}
        url = "https://www.ryutsuu.biz/sales/s041442.html"
        for date, title in [
            ("2026-04-16", "B"), ("2026-04-15", "A"), ("2026-04-23", "A"),
            ("2026-04-18", "C"), ("2026-04-17", "D"), ("2026-04-22", "B"),
        ]:
            store.merge_article(index, url, title, "流通ニュース", date)
        a = list(index.values())[0]
        self.assertEqual(a.appeared_dates, ("2026-04-15", "2026-04-16", "2026-04-17",
                                            "2026-04-18", "2026-04-22", "2026-04-23"))
        self.assertEqual(a.first_published_date, "2026-04-15")
        self.assertEqual(a.title_variants, ("A", "B", "C", "D"))
        self.assertEqual(a.title_first_seen, "A", "初出日のタイトルを採る（走査順非依存）")


class TestIntegrity(unittest.TestCase):
    def test_observation_without_a_source_is_rejected(self):
        with self.assertRaises(store.IntegrityError) as ctx:
            store.validate_integrity([obs()], [], CATALOG)
        self.assertIn("出典を持たない", str(ctx.exception))

    def test_undefined_ids_are_rejected(self):
        from retail_stats.models import SourceArticle

        article = SourceArticle("a" * 16, "https://x/1", "t", ("t",), "s", "s",
                                "2026-07-25", ("2026-07-25",))
        with self.assertRaises(store.IntegrityError):
            store.validate_integrity([obs(segment_id="takashimaya")], [article], CATALOG)

    def test_value_and_sign_only_are_exclusive(self):
        from retail_stats.models import SourceArticle

        article = SourceArticle("a" * 16, "https://x/1", "t", ("t",), "s", "s",
                                "2026-07-25", ("2026-07-25",))
        with self.assertRaises(store.IntegrityError):
            store.validate_integrity([obs(value=1.0, sign_only="+")], [article], CATALOG)


class TestDeterministicWrite(unittest.TestCase):
    """§5.4 の 6 規則。1 つでも欠けるとバイト一致しない。"""

    def test_json_is_byte_identical_on_rewrite(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.json"
            payload = {"schema_version": 1, "b": [3, 1, 2], "a": {"z": 1, "y": 2}}
            store.write_json(path, payload)
            first = path.read_bytes()
            store.write_json(path, payload)
            self.assertEqual(first, path.read_bytes())

    def test_keys_are_sorted_and_utf8_is_readable(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.json"
            store.write_json(path, {"b": 1, "a": "百貨店"})
            text = path.read_text(encoding="utf-8")
            self.assertLess(text.index('"a"'), text.index('"b"'))
            self.assertIn("百貨店", text, "ensure_ascii=False で日本語が読める")
            self.assertTrue(text.endswith("\n"))

    def test_no_temp_file_is_left_behind(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "x.json"
            store.write_json(path, {"a": 1})
            self.assertEqual([p.name for p in Path(d).iterdir()], ["x.json"])

    def test_values_are_rounded_to_catalog_precision(self):
        """§5.4 規則 4: `-1.6000000000000001` のような表現差を防ぐ。"""
        rounded = store.round_values([obs(value=-1.6000000000000001)], CATALOG)
        self.assertEqual(rounded[0].value, -1.6)

    def test_roundtrip_through_json(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "observations.json"
            index = {}
            store.upsert(index, obs())
            store.write_json(path, {
                "schema_version": 1,
                "observations": [json.loads(json.dumps(o.__dict__)) for o in index.values()],
            })
            self.assertEqual(len(store.load_observations(path)), 1)


if __name__ == "__main__":
    unittest.main()
