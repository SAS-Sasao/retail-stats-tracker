"""period.resolve() の各パターン。実装設計 §7.2 T-5。

対応するテストケース:
    PERIOD_CASES（11パターン）: 月次 / 年またぎ月 / 決算期（1桁年・2桁年・
        将来期）/ 四半期範囲 / 半期範囲（年またぎ）/ 年度 / 元号 / 上半期。
        実装設計 §7.2 T-5 の表をそのまま移植する。
    PERIOD_UNRESOLVED_CASES（2パターン）: span=9 の曖昧な範囲は
        reason_code="ambiguous_period" に落ちる。
    test_range_pattern_beats_fiscal_year_end: 範囲パターン（P_RANGE）を
        決算期末パターン（P_FY_END）より先に評価しないと「2026年1-3月期」が
        「3月期」に誤マッチする回帰テスト。
"""

import unittest


class TestPeriodResolve(unittest.TestCase):
    def test_period_cases(self):
        raise unittest.SkipTest("M3 実装後に implementation-design.md §7.2 T-5 PERIOD_CASES を移植する")

    def test_period_unresolved_cases(self):
        raise unittest.SkipTest("M3 実装後に PERIOD_UNRESOLVED_CASES を移植する（reason_code=ambiguous_period）")

    def test_range_pattern_beats_fiscal_year_end(self):
        raise unittest.SkipTest("M3 実装後: 評価順序の回帰テスト（実装設計 §7.2 T-5）")


if __name__ == "__main__":
    unittest.main()
