"""golden-60 候補ファイルの構成を固定する（ループ設計 §3.3 規律 G1）。

設計のテスト一覧には無い追加のテスト（origin.md D-B に記録）。G1 が定める
「区分ごとの件数」は評価の妥当性そのものであり、**末尾 3 区分 14 件が欠けると
評価が『取れた数』だけを報酬にしてしまう**（G1 の本文）。ファイルが静かに
差し替わったり件数が変わったりしたことを検出できるようにする。

期待値（`expected`）そのものは人手で確定する（G1）。このテストは
「まだ未確定であること」または「確定済みであること」を状態として検査するのみで、
期待値の中身には踏み込まない。
"""

import json
import unittest
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CANDIDATES = FIXTURES / "golden-60.candidates.jsonl"
FROZEN = FIXTURES / "golden-60.jsonl"

# G1 の選定基準表（区分 → 件数）。合計 60。
EXPECTED_BUCKETS = {
    # G1 は 18 件を求めるが母集団から取れない（origin.md D-E の G-6）。
    # 主要4業態 34 件のうち使えるのは 21 件で、⑤⑥ が 5 件を先に確保するため 16 が上限。
    # 不足 2 件を埋めるには個社決算を混ぜるしかなく、制約 15 に反する。
    "major4_existing_store": 16,
    "multi_metric": 8,
    "period_all_5_types": 8,
    "notation_variants": 6,
    "qualitative_and_streak": 6,
    "multi_authority": 4,
    "no_numeric": 4,
    "out_of_scope": 6,
}


def _load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestGolden60Candidates(unittest.TestCase):
    def setUp(self):
        if not CANDIDATES.is_file():
            self.skipTest(
                "golden-60.candidates.jsonl が未生成。実データを指して "
                "tests/make_golden60.py を実行すること（origin.md D-A）"
            )
        self.rows = _load(CANDIDATES)

    def test_total_matches_achievable_composition(self):
        """G1 の合計は 60 件だが、本母集団から取れるのは 58 件（G-6）。

        件数を満たすために性質を捨てない、という判断の結果。
        母集団を広げれば 60 に届くが、G1 は母集団を「計測日 2026-07-26 の 595 行」と
        固定しており、広げると設計の他の実測値と比較できなくなる。
        """
        self.assertEqual(len(self.rows), sum(EXPECTED_BUCKETS.values()))
        self.assertEqual(len(self.rows), 58)

    def test_bucket_counts_match_g1(self):
        counts = {}
        for row in self.rows:
            counts[row["bucket"]] = counts.get(row["bucket"], 0) + 1
        self.assertEqual(counts, EXPECTED_BUCKETS)

    def test_tail_three_buckets_are_present(self):
        """G1: 末尾 3 区分の 14 件が最も重要。

        「取れないことが正解」「別レコードとして共存するのが正解」を評価データに
        含めないと、評価が『取れた数』だけを報酬にしてしまい、無理に数値を
        ひねり出す方向・母集団の違う値を 1 つに畳む方向へ最適化が進む。
        """
        tail = sum(
            1
            for row in self.rows
            if row["bucket"] in ("multi_authority", "no_numeric", "out_of_scope")
        )
        self.assertEqual(tail, 14)

    def test_out_of_scope_includes_true_misses(self):
        """out_of_scope の 6 件のうち 2 件は真の取りこぼし（no_segment_match 期待）。

        NFR-05 の分母が可変になったため「対象外」と「取りこぼし」の判別を誤ると
        未解決率が実態と乖離する。評価データにこの 2 種を並べて置かないと、
        判別の劣化を誰も検出できない（G1）。
        """
        true_miss = [
            row
            for row in self.rows
            if row["bucket"] == "out_of_scope" and "真の取りこぼし" in row["selected_because"]
        ]
        self.assertEqual(len(true_miss), 2)
        for row in true_miss:
            self.assertTrue(row["features"]["has_authority_marker"])
            self.assertEqual(row["features"]["segment_alias_hits"], [])

    # --- 性質検査（件数だけでは通ってしまう欠陥を止める）---------------------
    #
    # 初版は件数しか見ておらず、8 区分中 5 区分が「G1 が定義した性質を持たない行」で
    # 埋まったまま green だった（retail-stats-qa の差し戻し）。件数は評価データの
    # 妥当性を何も保証しない。

    def test_multi_authority_rows_come_in_pairs(self):
        """⑥: 期待値は「2 レコードが共存し、どちらも上書きされない」（制約 14）。

        片側だけを選ぶと、**その期待値を書ける行が 1 件も無くなる**。
        """
        rows = [r for r in self.rows if r["bucket"] == "multi_authority"]
        self.assertEqual(len(rows), 4)
        groups = {}
        for row in rows:
            key = tuple(
                s for s in row["features"]["segment_alias_hits"] if s != "meti-commerce-dynamics"
            )[:1]
            groups.setdefault((key, row["_month_hint"]), []).append(row)
        self.assertTrue(groups, "ペアの手がかり（業態・月）が失われている")
        for key, pair in groups.items():
            with self.subTest(key=key):
                self.assertEqual(len(pair), 2, "並立ペアの片側しか入っていない")
                self.assertEqual(
                    sorted(r["features"]["has_authority_marker"] for r in pair),
                    [False, True],
                    "経産省側と協会側が揃っていない",
                )

    def test_streak_rows_are_evaluable(self):
        """⑤: 制約 11 の streak_broken_months を評価できる行があること。"""
        rows = [r for r in self.rows if r["bucket"] == "qualitative_and_streak"]
        evaluable = [
            r
            for r in rows
            if r["features"]["has_streak"]
            and r["features"]["segment_alias_hits"]
            and r["features"]["value_tokens"] > 0
        ]
        self.assertGreaterEqual(len(evaluable), 2, "連続記録を評価できる行が無い")

    def test_multi_metric_rows_are_in_scope(self):
        """②: FR-11 の評価対象は業態が解決できる行に限る。"""
        for row in [r for r in self.rows if r["bucket"] == "multi_metric"]:
            with self.subTest(url=row["url"]):
                self.assertTrue(row["features"]["segment_alias_hits"], "業態が解決できない行")
                self.assertGreaterEqual(row["features"]["pct_tokens"], 2)

    def test_no_numeric_rows_are_in_scope_and_not_ranking(self):
        """⑦: 「対象内なのに値が取れない」が期待値の性質。

        ランキング記事は未決事項 (c) に依存するため、決着していない論点を
        評価データの前提にしない。
        """
        for row in [r for r in self.rows if r["bucket"] == "no_numeric"]:
            with self.subTest(url=row["url"]):
                self.assertTrue(row["features"]["segment_alias_hits"], "業態が解決できない行")
                self.assertEqual(row["features"]["value_tokens"], 0)
                self.assertFalse(row["features"]["is_ranking"], "ランキング記事が混入している")

    def test_period_bucket_covers_all_five_kinds(self):
        """③: G1 は「期間表記の**全 5 種**」を求めている。"""
        rows = [r for r in self.rows if r["bucket"] == "period_all_5_types"]
        self.assertEqual(
            {r["features"]["period_kind"] for r in rows},
            {"month", "fiscal_period", "quarter", "half", "fiscal_year"},
        )

    def test_source_distribution_is_not_dominated_by_one_domain(self):
        """出所の偏りを止める。G1 は「偏りが評価を無効化する」と言っている。"""
        import re as _re

        domains = [_re.sub(r"https?://([^/]+)/.*", r"\1", r["url"]) for r in self.rows]
        top = max(domains.count(d) for d in set(domains))
        self.assertLess(
            top / len(domains), 0.60, f"1 ドメインが {top}/{len(domains)} を占めている"
        )

    def test_urls_are_unique(self):
        """同じ記事が複数枠を占めていないこと（代表 variant 単位で選ぶ前提）。"""
        urls = [row["url"] for row in self.rows]
        self.assertEqual(len(urls), len(set(urls)))

    def test_every_row_carries_its_selection_reason(self):
        for row in self.rows:
            with self.subTest(url=row["url"]):
                self.assertIn(row["bucket"], EXPECTED_BUCKETS)
                self.assertTrue(row["selected_because"])
                self.assertTrue(row["title"])
                self.assertTrue(row["appeared_dates"])

    def test_expected_values_are_not_machine_filled(self):
        """G1: 期待値は人手で確定する。機械が推測で埋めていないこと。

        埋まっていたら「実装に引きずられた期待値」の疑いがあるため落とす。
        オーナーが確定したものは FROZEN（golden-60.jsonl）側に置く。
        """
        for row in self.rows:
            with self.subTest(url=row["url"]):
                self.assertIsNone(row["expected"])
                self.assertEqual(row["status"], "needs_human_review")


class TestPeriodKind(unittest.TestCase):
    """期間表記の 5 種判定（カタログ §4.2）。パターンの評価順の回帰テスト。"""

    def test_range_periods_are_classified_by_span_not_suffix(self):
        """`1~6月期`（暦年上半期）が決算期に化けないこと。

        fiscal_period の `[0-9]{1,2}月期` は `1~6月期` の「6月期」にも一致するため、
        half より先に評価すると半期が 1 件も選ばれない。G1 は「期間表記の**全 5 種**」を
        求めており、1 種が構造的に選ばれなくなると評価データの区分が欠ける。
        """
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from make_golden60 import period_kind

        cases = [
            ("1~6月期", "half"),           # 暦年上半期
            ("2月期", "fiscal_period"),     # 決算期（期末月）
            ("29年2月期", "fiscal_period"),
            ("2025年度", "fiscal_year"),    # 会計年度
            ("3~5月", "quarter"),           # 会計四半期
            ("2026年6月", "month"),         # 月次（年月明示）
            ("6月", "month"),               # 月次
            ("特集記事", None),
        ]
        for src, want in cases:
            with self.subTest(src=src):
                self.assertEqual(period_kind(src), want)


class TestGolden60Frozen(unittest.TestCase):
    """凍結済み golden-60 の検査。

    **評価データ自身が壊れていないこと**を見る。カタログに無い ID や enum 外の値が
    紛れていると、パーサが正しくても落ち、正しくなくても通りうる。
    """

    def setUp(self):
        if not FROZEN.is_file():
            self.skipTest(
                "golden-60.jsonl は未凍結。候補の expected を確定してから凍結する"
                "（ループ設計 §3.3 G1 / origin.md D-E N-1a）"
            )
        self.rows = _load(FROZEN)

    def test_every_row_is_confirmed_with_provenance(self):
        """誰がいつ決めたかを残す（permanently-unresolvable.json と同じ形）。"""
        for row in self.rows:
            with self.subTest(url=row["url"]):
                self.assertEqual(row["status"], "confirmed")
                self.assertIsNotNone(row["expected"])
                self.assertTrue(row["decided_by"])
                self.assertTrue(row["decided_at"])
                self.assertTrue(row["expectation_note"], "導出根拠が空")

    def test_composition_matches_candidates(self):
        """凍結時に行が増減していないこと。"""
        self.assertEqual(len(self.rows), 58)
        counts = {}
        for row in self.rows:
            counts[row["bucket"]] = counts.get(row["bucket"], 0) + 1
        self.assertEqual(counts, EXPECTED_BUCKETS)

    def test_expected_ids_exist_in_catalog(self):
        """期待値の segment_id / metric_id がカタログに実在すること（FR-24）。"""
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from retail_stats import catalog as catalog_mod
        from retail_stats import config
        from retail_stats.models import (
            REASON_CODES, SCOPES, SOURCE_AUTHORITY_CODES, UNITS,
        )

        cat = catalog_mod.load(config.catalog_path())
        segments = {s.segment_id for s in cat.segments}
        metrics = {m.metric_id for m in cat.metrics}

        for row in self.rows:
            expected = row["expected"]
            with self.subTest(url=row["url"]):
                if isinstance(expected, dict):
                    self.assertIn(expected["unresolved"]["reason_code"], REASON_CODES)
                    continue
                self.assertIsInstance(expected, list)
                self.assertGreater(len(expected), 0, "空配列は unresolved で表す")
                for ob in expected:
                    self.assertIn(ob["segment_id"], segments)
                    self.assertIn(ob["metric_id"], metrics)
                    self.assertIn(ob["scope"], SCOPES)
                    self.assertIn(ob["source_authority"], SOURCE_AUTHORITY_CODES)
                    self.assertIn(ob["unit"], UNITS)
                    self.assertIn(ob["period_type"], ("month", "quarter", "half", "fiscal_year"))

    def test_value_and_sign_only_are_exclusive(self):
        """制約 11: 定性表現のみの行は value=None かつ sign_only を持つ。"""
        for row in self.rows:
            if not isinstance(row["expected"], list):
                continue
            for ob in row["expected"]:
                with self.subTest(url=row["url"], metric=ob["metric_id"]):
                    if ob["sign_only"] is not None:
                        self.assertIsNone(ob["value"], "sign_only と value は排他")
                        self.assertIn(ob["sign_only"], ("+", "-"))
                        self.assertTrue(ob["needs_source_check"], "数値は原資料参照のフラグを立てる")
                    else:
                        self.assertIsNotNone(ob["value"])

    def test_natural_keys_do_not_collide_within_a_row(self):
        """1 行から出る observation どうしが natural key で衝突しないこと。

        衝突していると upsert で片方が消え、期待値として成立しない（FR-09）。
        """
        for row in self.rows:
            if not isinstance(row["expected"], list):
                continue
            keys = [
                (ob["segment_id"], ob["metric_id"], ob["scope"], ob["period_key"], ob["source_authority"])
                for ob in row["expected"]
            ]
            with self.subTest(url=row["url"]):
                self.assertEqual(len(keys), len(set(keys)), "同一行内で natural key が衝突している")

    def test_multi_authority_rows_coexist_by_authority(self):
        """制約 14: 同一業態・同一期間の観測が、発表主体違いで共存すること。

        **同一 natural key の衝突（第 5 要素だけが違う組）は、この母集団には
        存在しない。** カタログ §2.3 の対応マトリクスが、百貨店について
        `existing-store-sales-yoy` を協会側「－」、`sales-amount-yoy`（経産省）を
        「○」としているとおり、協会と経産省は**別の指標**を発表しているためである。
        したがって golden-60 で評価できるのは「同一業態・同一期間の観測が
        発表主体違いで並立する」ところまでで、**5 項キーが 4 項キーの衝突を
        防いでいることの直接の実証はできない**（origin.md D-E の G-7）。
        """
        by_authority = {}
        for row in self.rows:
            if row["bucket"] != "multi_authority" or not isinstance(row["expected"], list):
                continue
            for ob in row["expected"]:
                by_authority.setdefault(
                    (ob["segment_id"], ob["period_key"]), set()
                ).add(ob["source_authority"])
        parallel = {k: v for k, v in by_authority.items() if len(v) > 1}
        self.assertTrue(
            parallel, "同一業態・同一期間で発表主体が並立する観測が無い"
        )
        for key, authorities in parallel.items():
            with self.subTest(key=key):
                self.assertIn("meti", authorities, "経産省側が無い")
                self.assertTrue(
                    authorities - {"meti"}, "協会側が無い"
                )


if __name__ == "__main__":
    unittest.main()
