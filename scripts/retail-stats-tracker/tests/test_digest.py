"""digest.py のセクション抽出・行数検証。実装設計 §7.2 T-10a〜T-10d / M1 完了条件。

対応するテストケース:
    T-10a 決算・統計章が存在しない日（2026-04-14）でエラーにならず、
          files_without_section が加算される。
    T-10b ヘッダ行の列順を入れ替えたフィクスチャで、列位置が動的に
          解決される（FR-02）。
    T-10c ヘッダ行の列名を「記事」→「Article」に変えても解決される
          （許容リスト、DIGEST_COLUMNS）。
    T-10d ヘッダ行の列名を未知の名前に変えたら停止する（silent な欠測を
          防ぐ、要件 7-12）。

M1 完了条件（実装設計 §8）: --dry-run --rebuild が 102 ファイルを走査し、
決算・統計章を持つ93ファイル / 表を持つ89ファイル / データ行595行 /
リンク抽出成功595件 を出力すること。
"""

import unittest


class TestDigestParsing(unittest.TestCase):
    def test_missing_section_is_recorded_not_error(self):
        raise unittest.SkipTest("M1 実装後: T-10a 2026-04-14 フィクスチャで検証する")

    def test_header_column_order_independent(self):
        raise unittest.SkipTest("M1 実装後: T-10b 列順入れ替えフィクスチャで検証する")

    def test_header_alias_is_accepted(self):
        raise unittest.SkipTest("M1 実装後: T-10c 記事→Article 列名で検証する")

    def test_unknown_header_column_stops_parsing(self):
        raise unittest.SkipTest("M1 実装後: T-10d 未知列名フィクスチャで停止することを検証する")


if __name__ == "__main__":
    unittest.main()
