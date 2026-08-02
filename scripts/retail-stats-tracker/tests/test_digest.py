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

import tempfile
import unittest
from pathlib import Path

from retail_stats import digest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "digests"

ROW = (
    "| 1 | [ショッピングセンター／6月既存店売上1.6％減]"
    "(https://www.ryutsuu.biz/sales/s072477.html) | 流通ニュース | 6月の既存店売上高は… |"
)


def _md(header: str, rows: str = ROW, heading: str = "### B5. 決算・統計") -> str:
    sep = "|" + "|".join("---" for _ in header.strip().strip("|").split("|")) + "|"
    return "\n".join(
        ["# 日次ダイジェスト 2026-07-25", "", "## B. 小売ドメイン", "", heading, "", header, sep, rows, ""]
    )


class _DigestTestCase(unittest.TestCase):
    def parse_text(self, text, name="2026-07-25.md"):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / name
        path.write_text(text, encoding="utf-8")
        return digest.parse_file(path)


class TestDigestParsing(_DigestTestCase):
    def test_missing_section_is_recorded_not_error(self):
        """T-10a: 決算・統計章が存在しない日でエラーにならない（要件 7-1）。"""
        result = digest.parse_file(FIXTURES / "2026-04-14.md")
        self.assertFalse(result.has_section)
        self.assertFalse(result.has_table)
        self.assertEqual(result.rows, ())
        self.assertEqual(result.malformed, ())
        self.assertEqual(result.digest_date, "2026-04-14")

    def test_header_column_order_independent(self):
        """T-10b: 列順を入れ替えても列位置が動的に解決される（FR-02）。"""
        header = "| 要約 | ソース | 記事 | # |"
        row = (
            "| 6月の既存店売上高は… | 流通ニュース | "
            "[ショッピングセンター／6月既存店売上1.6％減]"
            "(https://www.ryutsuu.biz/sales/s072477.html) | 1 |"
        )
        result = self.parse_text(_md(header, row))
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0].url, "https://www.ryutsuu.biz/sales/s072477.html")
        self.assertEqual(result.rows[0].source_name, "流通ニュース")
        self.assertEqual(result.rows[0].summary, "6月の既存店売上高は…")
        self.assertEqual(result.rows[0].row_index, 1)

    def test_header_alias_is_accepted(self):
        """T-10c: 列名を 記事→Article / ソース→Source に変えても解決される。"""
        result = self.parse_text(_md("| # | Article | Source | Summary |"))
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0].source_name, "流通ニュース")

    def test_unknown_header_column_stops_parsing(self):
        """T-10d: 未知の列名では列マップを確定せず、データ行を**捨てない**。

        要件 7-12 の silent な欠測の防止。ここで 0 行を返して静かに済ませると、
        「表の列名が変わった」ことが誰にも観測されないまま件数だけが減る
        （ループ設計 §1.2 の silent accumulation）。
        """
        result = self.parse_text(_md("| 番号 | 見出し | 情報源 | 概要 |"))
        self.assertFalse(result.has_table)
        self.assertEqual(len(result.rows), 0)
        # 捨てずに落ちていること。ヘッダ行自身も malformed に入る（列マップを
        # 解決できない以上、その行がヘッダなのかデータなのかを判別する根拠が
        # 無いため。判別できないものを落とすのは要件 7-12 が禁じている欠測）
        self.assertEqual([m.reason for m in result.malformed], ["no_header_map"] * 2)
        self.assertIn("見出し", result.malformed[0].raw_line)
        self.assertIn("s072477", result.malformed[1].raw_line)

    def test_partial_header_is_not_accepted(self):
        """必須キーの片方（ソース）だけでは列マップを確定しない。"""
        result = self.parse_text(_md("| # | 記事 | 情報源 | 概要 |"))
        self.assertFalse(result.has_table)
        self.assertEqual(len(result.malformed), 2)
        self.assertIn("s072477", result.malformed[1].raw_line)

    def test_row_without_link_is_not_dropped(self):
        """リンクを抽出できない行も捨てずに落とす（規則 6 / FR-10）。"""
        result = self.parse_text(_md("| # | 記事 | ソース | 要約 |", "| 1 | 見出しのみ | DCS | … |"))
        self.assertEqual(len(result.rows), 0)
        self.assertEqual(len(result.malformed), 1)
        self.assertEqual(result.malformed[0].reason, "no_link")

    def test_section_detection_ignores_chapter_number(self):
        """章番号（B5）では判定しない（要件 7-1）。見出しテキストの部分一致のみ。"""
        for heading in ("### B5. 決算・統計", "### 決算・統計", "### C3. 決算・統計まとめ"):
            with self.subTest(heading=heading):
                result = self.parse_text(_md("| # | 記事 | ソース | 要約 |", ROW, heading))
                self.assertTrue(result.has_section)
                self.assertEqual(len(result.rows), 1)

    def test_other_sections_are_not_scanned(self):
        """決算・統計章以外の表は読まない。"""
        result = self.parse_text(_md("| # | 記事 | ソース | 要約 |", ROW, "### B1. 業態変革・新店"))
        self.assertFalse(result.has_section)
        self.assertEqual(len(result.rows), 0)

    def test_h2_ends_the_section(self):
        """## 見出しで対象フラグを落とす（章の切り替わり）。"""
        text = _md("| # | 記事 | ソース | 要約 |") + "\n## C. クロスドメイン分析\n\n" + ROW + "\n"
        result = self.parse_text(text)
        self.assertEqual(len(result.rows), 1)

    def test_second_table_header_is_redetected(self):
        """1 つの章に表が 2 つある場合、2 つ目のヘッダをデータ行と誤認しない。

        列マップを持ち越したまま読むと、2 つ目のヘッダ行は「リンクの無い行」
        として malformed に落ちる。実データでは章あたり表は 1 つだが、
        誤認すると本物のデータ行と見分けがつかない形で件数がずれる。
        """
        header = "| # | 記事 | ソース | 要約 |"
        sep = "|---|---|---|---|"
        row2 = (
            "| 1 | [日本百貨店協会／6月の売上高2.3％増]"
            "(https://www.ryutsuu.biz/sales/s072447.html) | 流通ニュース | … |"
        )
        text = "\n".join(
            [
                "# 日次ダイジェスト 2026-07-25", "", "## B. 小売ドメイン", "",
                "### B5. 決算・統計", "", header, sep, ROW, "",
                "（補足）", "", header, sep, row2, "",
            ]
        )
        result = self.parse_text(text)
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(result.malformed, ())
        self.assertEqual(
            [r.url for r in result.rows],
            [
                "https://www.ryutsuu.biz/sales/s072477.html",
                "https://www.ryutsuu.biz/sales/s072447.html",
            ],
        )

    def test_title_is_kept_raw(self):
        """タイトルは原文のまま保持する（正規化しない。実装設計 §4.2）。"""
        result = self.parse_text(_md("| # | 記事 | ソース | 要約 |"))
        self.assertIn("％", result.rows[0].title)  # 全角のまま
        self.assertIn("s072477", result.rows[0].raw_line)


class TestDigestFixtures(_DigestTestCase):
    """コミット済みフィクスチャに対する回帰（実装設計 §7.3 の選定理由に対応）。"""

    def setUp(self):
        self.files = digest.iter_digest_files(FIXTURES)
        self.results = [digest.parse_file(p) for p in self.files]
        self.rows = [row for r in self.results for row in r.rows]

    def test_fixture_set_is_complete(self):
        dates = [digest.date_from_filename(p) for p in self.files]
        self.assertEqual(
            dates,
            [
                "2026-04-14", "2026-04-15", "2026-04-16", "2026-04-17",
                "2026-04-18", "2026-04-22", "2026-04-23",
                "2026-07-22", "2026-07-23", "2026-07-24", "2026-07-25", "2026-07-26",
            ],
        )

    def test_iteration_is_date_sorted(self):
        """走査順をディレクトリ列挙順に依存させない（NFR-06 の再現性）。"""
        dates = [digest.date_from_filename(p) for p in self.files]
        self.assertEqual(dates, sorted(dates))

    def test_since_filters_by_date(self):
        files = digest.iter_digest_files(FIXTURES, since="2026-07-22")
        self.assertEqual(len(files), 5)

    def test_s041442_appears_on_six_non_consecutive_days(self):
        """T-1 の前提となるフィクスチャの回帰（掲載日と variant 数）。

        upsert の収束そのものは M4 の test_idempotency.py が検証する。
        ここでは「6 日分・4 variant がフィクスチャに実在すること」を固定する。
        """
        target = [r for r in self.rows if "s041442" in r.url]
        self.assertEqual(
            [r.digest_date for r in target],
            ["2026-04-15", "2026-04-16", "2026-04-17", "2026-04-18", "2026-04-22", "2026-04-23"],
        )
        self.assertEqual(len({r.title for r in target}), 4)

    def test_all_links_extracted(self):
        """フィクスチャ内のデータ行は全てリンク抽出に成功する。"""
        malformed = [m for r in self.results for m in r.malformed]
        self.assertEqual(malformed, [])
        self.assertGreater(len(self.rows), 0)

    def test_header_variant_is_single(self):
        """実データのヘッダは 1 種類のみ（実装設計 §4.1 の実測）。"""
        variants = {r.header_variant for r in self.results if r.has_table}
        self.assertEqual(variants, {("#", "記事", "ソース", "要約")})

    def test_fullwidth_and_halfwidth_variants_coexist(self):
        """T-3 の前提: 同一 URL が全角％と半角% の両方で出現する（s072212）。"""
        target = [r for r in self.rows if "s072212" in r.url]
        self.assertTrue(any("％" in r.title for r in target), "全角％の variant が無い")
        self.assertTrue(any("%" in r.title for r in target), "半角% の variant が無い")


if __name__ == "__main__":
    unittest.main()
