"""冪等性・再現性の統合テスト。実装設計 §7.2 T-1 / T-2。M4 完了条件。

対応するテストケース:
    T-1 test_s041442_six_day_duplication
        要件 NFR-07 が名指しするケース。s041442 は掲載日 04-15/16/17/18/22/23
        の非連続6日。1記事に収束し、appeared_dates が全て記録され、
        title_variants は4種、observation は0件（業態「カジュアル衣料4社」が
        カタログ未定義）、unresolved は1エントリに集約（reason_code=
        out_of_scope）。NFR-05 の分母に含まれないこと。
        実装設計 §7.2 T-1 の assert 群をそのまま移植する。

    T-2 test_rebuild_is_byte_identical
        --rebuild を2回連続実行し、runs.json 以外の全 JSON がバイト一致する
        （config.IDEMPOTENT_FILES の6ファイル）。

冪等性比較の対象ファイルは config.IDEMPOTENT_FILES と一致させること
（独自の集合を定義しない。実装設計 §5.1 の申し送り）。
"""

import unittest


class TestIdempotency(unittest.TestCase):
    def test_s041442_six_day_duplication(self):
        raise unittest.SkipTest("M4 実装後に実装設計 §7.2 T-1 を移植する（NFR-07 名指しケース）")

    def test_rebuild_is_byte_identical(self):
        raise unittest.SkipTest("M4 実装後に実装設計 §7.2 T-2 を移植する（NFR-06 バイト一致）")


if __name__ == "__main__":
    unittest.main()
