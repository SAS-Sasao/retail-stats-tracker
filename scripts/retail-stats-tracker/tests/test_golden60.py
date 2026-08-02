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
    "major4_existing_store": 18,
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

    def test_total_is_60(self):
        self.assertEqual(len(self.rows), 60)

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
    def test_frozen_file_is_fully_confirmed(self):
        if not FROZEN.is_file():
            self.skipTest(
                "golden-60.jsonl は未凍結。候補の expected を人手で確定してから"
                "凍結する（ループ設計 §3.3 G1 / origin.md D-E N-1a）"
            )
        rows = _load(FROZEN)
        self.assertEqual(len(rows), 60)
        for row in rows:
            with self.subTest(url=row["url"]):
                self.assertEqual(row["status"], "confirmed")
                self.assertIsNotNone(row["expected"])


if __name__ == "__main__":
    unittest.main()
