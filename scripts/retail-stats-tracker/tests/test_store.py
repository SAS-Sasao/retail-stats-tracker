"""store.py の純粋な dict 操作テスト。実装設計 §7.1 / §7.2 T-10e / T-10f。

対応するテストケース:
    T-10e manual_override=True の observation が自動 upsert で
          上書きされない（FR-23）。
    T-10f confidence 同値・掲載日同値の場合に既存側が維持される
          （走査順非依存。_wins() が完全同点で False を返す）。
    test_association_and_meti_coexist（実装設計 §7.2 T-7。natural key の
          5要素化により発表主体が異なる観測が上書きされないことの確認。
          parser.py 側のテストと重複して store.py 側でも upsert() 単体で
          検証する）。
"""

import unittest


class TestUpsert(unittest.TestCase):
    def test_manual_override_is_not_overwritten(self):
        raise unittest.SkipTest("M4 実装後に実装設計 §7.2 T-10e を移植する（FR-23）")

    def test_tie_keeps_existing_record(self):
        raise unittest.SkipTest("M4 実装後に実装設計 §7.2 T-10f を移植する（走査順非依存）")

    def test_association_and_meti_coexist(self):
        raise unittest.SkipTest("M4 実装後に実装設計 §7.2 T-7 を store.upsert() 単体で移植する")


if __name__ == "__main__":
    unittest.main()
