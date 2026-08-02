"""parser.py の決定論パースアルゴリズム。実装設計 §7.2 T-4 / T-7 / T-8 / T-9 / T-10h〜j。

本システムの中核テストファイル。M3（判断の分岐点）の完了条件そのもの。
各テストの詳細は implementation-design.md §7.2 の該当節を必ず参照して
本文をそのまま移植すること（値・件数は実測値であり創作しない）。

T-4 複数指標の分解（FR-11）:
    test_split_into_three_observations
    test_absolute_and_ratio_split
    test_intra_title_collision_lowers_confidence

T-7 発表主体の解決と共存（要件 7-14）:
    test_association_and_meti_coexist
    test_authority_default_from_catalog
    test_authority_override_by_article
    test_source_name_is_not_authority
    test_unknown_authority_in_catalog_raises（catalog 側。test_catalog.py 参照）
    test_chart_spec_rejects_mixed_authority（html/build.build_chart_spec() 対象。
        実装設計 §2.2 の tests/ 構成には専用ファイルが無いため、本ファイルの
        TestAuthorityResolution にまとめて置く）
    test_home_center_two_authorities_coexist
    test_drugstore_company_disclosure_excluded

T-8 スコープ外の分類（要件 7-15。主語位置ガード §4.3.3）:
    test_scope_classification（SCOPE_CASES 8パターン）
    test_generic_alias_does_not_match_outside_subject
        （SEGMENT_FALSE_POSITIVE_CASES 6パターン。主語位置ガードの中核）
    test_authority_head_exception_is_preserved（経産省調べの4件）
    test_multi_subject_values_are_not_misattributed（U10: 複数主体併記）
    test_authority_marker_evaluated_before_company_rule（判定順序回帰）
    test_out_of_scope_is_persisted_not_discarded（FR-10 / NFR-10）
    test_out_of_scope_never_calls_llm（NFR-11）
    test_nfr05_denominator_excludes_out_of_scope
        現時点の確定値は 0.771（64/83）で未達（origin.md「未決事項」参照）。
        閾値 assert は NFR-05 未達解消（U9）後に有効化する。

T-9 集計粒度の混在禁止（カタログ §1.1 / §1.4）:
    test_no_parent_rollup（R8: parent_segment_id によるロールアップをしない）

T-10h〜j:
    T-10h streak_broken_months（51カ月ぶりに前年割れ）
    T-10i 増収増益 → 2件、value=None、sign_only="+"、needs_source_check=True
    T-10j 金額換算16パターン（test_jpy_conversion。test_textnorm.py 側）
"""

import unittest


class TestMultiMetricSplit(unittest.TestCase):
    def test_split_into_three_observations(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-4 を移植する")

    def test_absolute_and_ratio_split(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-4 を移植する")

    def test_intra_title_collision_lowers_confidence(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-4 を移植する")


class TestAuthorityResolution(unittest.TestCase):
    def test_association_and_meti_coexist(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-7 を移植する")

    def test_authority_default_from_catalog(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-7 を移植する")

    def test_authority_override_by_article(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-7 を移植する")

    def test_source_name_is_not_authority(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-7 を移植する")

    def test_home_center_two_authorities_coexist(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-7 を移植する")

    def test_drugstore_company_disclosure_excluded(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-7 を移植する")

    def test_chart_spec_rejects_mixed_authority(self):
        raise unittest.SkipTest(
            "M6 実装後に html.build.build_chart_spec() で実装設計 §7.2 T-7 R1 を移植する"
        )


class TestScopeClassification(unittest.TestCase):
    def test_scope_classification(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-8 SCOPE_CASES を移植する")

    def test_generic_alias_does_not_match_outside_subject(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-8 主語位置ガードを移植する")

    def test_authority_head_exception_is_preserved(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-8 を移植する")

    def test_multi_subject_values_are_not_misattributed(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-8（U10）を移植する")

    def test_authority_marker_evaluated_before_company_rule(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-8 判定順序回帰を移植する")

    def test_out_of_scope_is_persisted_not_discarded(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-8 を移植する（FR-10）")

    def test_out_of_scope_never_calls_llm(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-8 を移植する（NFR-11）")

    def test_nfr05_denominator_excludes_out_of_scope(self):
        raise unittest.SkipTest(
            "M3 実装後に実装設計 §7.2 T-8 を移植する。確定値 64/83=0.771 は未達"
            "（origin.md「未決事項」参照）。閾値 assert は U9 解決後に有効化する"
        )


class TestGranularityAndRollup(unittest.TestCase):
    def test_no_parent_rollup(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-9 R8 を移植する")

    def test_meti_commerce_dynamics_excluded_from_default_segments(self):
        raise unittest.SkipTest(
            "M6 実装後に html.build.build_default_segment_candidates() で実装設計 §7.2 T-9 R6 を移植する"
        )

    def test_chart_spec_rejects_mixed_granularity(self):
        raise unittest.SkipTest(
            "M6 実装後に html.build.build_chart_spec() で実装設計 §7.2 T-9 R6 を移植する"
        )

    def test_catalog_has_no_parent_links_today(self):
        raise unittest.SkipTest(
            "test_catalog.py の同名テストと重複するため実装時にどちらか一方に集約する"
            "（実装設計 §7.2 T-9）"
        )


class TestMiscRequiredCases(unittest.TestCase):
    def test_streak_broken_months(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-10h を移植する")

    def test_qualitative_sign_only(self):
        raise unittest.SkipTest("M3 実装後に実装設計 §7.2 T-10i を移植する")


if __name__ == "__main__":
    unittest.main()
