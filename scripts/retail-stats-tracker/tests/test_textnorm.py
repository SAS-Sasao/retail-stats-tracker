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

from retail_stats import textnorm


class TestNormalize(unittest.TestCase):
    def test_normalize_table(self):
        """実装設計 §7.2 T-3 の正規化表をそのまま移植したもの。"""
        cases = [
            ("1.6％減", "1.6%減"),
            ("６月", "6月"),  # 全角数字（現行データでは未出現）
            ("日本百貨店協会／", "日本百貨店協会/"),
            ("3〜5月", "3~5月"),
            ("3～5月", "3~5月"),
            ("51ヶ月", "51カ月"),
            ("19ヵ月", "19カ月"),
            ("3カ月", "3カ月"),
            ("2 月期", "2月期"),  # イオン記事の実例
            ("9〜2 月", "9~2月"),  # ビックカメラ記事の実例
            ("1兆4,505億円", "1兆4505億円"),  # \b バグの回帰（CJK 直前に境界なし）
            ("8,577億円", "8577億円"),
            ("12,345,678円", "12345678円"),
            ("1,23億円", "1,23億円"),  # 3 桁でないので除去しない
            ("2026,1", "2026,1"),  # 同上
        ]
        for src, want in cases:
            with self.subTest(src=src):
                self.assertEqual(textnorm.normalize(src), want)

    def test_normalize_is_pure(self):
        """副作用なし・冪等（NFR-06 の再現性が正規化順序に依存しないこと）。"""
        src = "日本百貨店協会／6月の外国人売上29.8％増、客数0.5％減"
        once = textnorm.normalize(src)
        self.assertEqual(textnorm.normalize(once), once)
        self.assertEqual(src, "日本百貨店協会／6月の外国人売上29.8％増、客数0.5％減")

    def test_thousand_separator_does_not_use_word_boundary(self):
        """\\b バグの直接的な回帰テスト（実装設計 §4.2 の落とし穴）。

        `(?=[0-9]{3}\\b)` は CJK の直前に単語境界が無いため実データで発火せず、
        カンマ分断された `505億円` に一致して 1兆4,505億円 を 505.0 として
        取り込む。例外にも未解決行にもならないため、テストで固定しない限り
        誤りに気づけない。
        """
        import re

        self.assertIsNone(re.search(r"505\b", "505億円"), "前提: CJK 直前に単語境界は無い")
        self.assertIsNotNone(re.search(r"505\b", "505 yen"))
        self.assertEqual(textnorm.normalize("1兆4,505億円"), "1兆4505億円")

    def test_jpy_conversion(self):
        raise unittest.SkipTest("M3 実装後に implementation-design.md §7.2 T-3 の JPY_CASES を移植する")


if __name__ == "__main__":
    unittest.main()
