"""textnorm.normalize() の回帰テスト。実装設計 §7.2 T-3。

対応するテストケース（実装設計 §7.2 から。実装時に本文をそのまま移植する）:
    test_normalize_table
        全角%→半角、全角数字→半角、／→/、波ダッシュ統一、カ月統一、
        数値内空白除去、桁区切りカンマ除去の各ケース。
        \\b バグの回帰（"1兆4,505億円" → "1兆4505億円"）を必ず含む。
    test_jpy_conversion
        JPY_CASES 16 パターン（parser.VALUE_JPY_RE + parser.to_jpy_oku 経由）。
        旧実装が silent に誤値を返した8パターンを必ず含む
        （"1兆4,505億円" 等。実装設計 §7.2 T-3 JPY_CASES を参照）。
"""

import unittest


class TestNormalize(unittest.TestCase):
    def test_normalize_table(self):
        raise unittest.SkipTest("M1 実装後に implementation-design.md §7.2 T-3 のケースを移植する")

    def test_jpy_conversion(self):
        raise unittest.SkipTest("M3 実装後に implementation-design.md §7.2 T-3 の JPY_CASES を移植する")


if __name__ == "__main__":
    unittest.main()
