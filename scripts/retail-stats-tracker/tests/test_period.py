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
from datetime import date

from retail_stats import period, textnorm

# 実装設計 §7.2 T-5 の PERIOD_CASES をそのまま移植したもの。
# (掲載日, タイトル, period_key, period_type, period_start, period_end)
PERIOD_CASES = [
    ("2026-07-25", "ショッピングセンター／6月既存店売上1.6％減",
     "2026-06", "month", "2026-06-01", "2026-06-30"),
    ("2026-01-20", "（検証用）12月既存店1.0%減",
     "2025-12", "month", "2025-12-01", "2025-12-31"),          # 年またぎ
    ("2026-04-11", "イオン 決算／2 月期増収増益",
     "FY2026-02", "fiscal_year", "2025-03-01", "2026-02-28"),
    ("2026-04-15", "オークワ／26年2月期は増収増益",
     "FY2026-02", "fiscal_year", "2025-03-01", "2026-02-28"),  # 2 桁年
    ("2026-04-20", "DCM／29年2月期売上高6500億円",
     "FY2029-02", "fiscal_year", "2028-03-01", "2029-02-28"),  # 将来期
    ("2026-06-27", "DCM 決算／3〜5月営業利益17.4%増",
     "2026-03~2026-05", "quarter", "2026-03-01", "2026-05-31"),
    ("2026-04-15", "サイゼリヤ 決算／9〜2月増収増益",
     "2025-09~2026-02", "half", "2025-09-01", "2026-02-28"),   # 年またぎ範囲
    ("2026-07-25", "ECプラットフォーム市場規模（2025年度）は前年度比5.8%増",
     "FY2025", "fiscal_year", "2025-04-01", "2026-03-31"),
    ("2026-04-01", "令和8年2月度チェーンストア販売統計",
     "2026-02", "month", "2026-02-01", "2026-02-28"),          # 元号
    ("2026-07-25", "ホームセンター月次実績＝2026年6月度",
     "2026-06", "month", "2026-06-01", "2026-06-30"),
    ("2026-07-23", "貿易赤字、1兆円に半減＝―2026年上半期",
     "2026-H1", "half", "2026-01-01", "2026-06-30"),
]

PERIOD_UNRESOLVED_CASES = [
    ("2026-04-15", "クスリのアオキHD 決算／6〜2月増収増益", "ambiguous_period"),  # span=9
    ("2026-04-11", "イオン 決算／2〜5月営業利益33.6%増", "ambiguous_period"),     # span=4
]


def _resolve(pub: str, title: str):
    """パーサと同じく、必ず normalize() を通してから解決する。"""
    return period.resolve(textnorm.normalize(title), date.fromisoformat(pub))


class TestPeriodResolution(unittest.TestCase):
    def test_period_cases(self):
        for pub, title, key, ptype, start, end in PERIOD_CASES:
            with self.subTest(title=title):
                p = _resolve(pub, title)
                self.assertIsNotNone(p, "解決できていない")
                self.assertEqual(p.period_key, key)
                self.assertEqual(p.period_type, ptype)
                self.assertEqual(p.period_start, start)
                self.assertEqual(p.period_end, end)

    def test_unresolved_cases(self):
        """span が enum に無い範囲は解決しない（ambiguous_period へ退避）。

        span 9（3Q 累計）と span 4 は意味としては明確だが、要件 §4.2 の
        period_type enum に該当する値が無い。**enum を勝手に増やさない**。
        """
        for pub, title, _reason in PERIOD_UNRESOLVED_CASES:
            with self.subTest(title=title):
                self.assertIsNone(_resolve(pub, title))

    def test_range_pattern_beats_fiscal_year_end(self):
        """P_RANGE を P_FY_END より先に評価しないと `3月期` に誤マッチする。"""
        p = _resolve("2026-05-20", "楽天の2026年1-3月期（1Q）の流通総額は約1.5兆円で4.8%増")
        self.assertEqual(p.period_type, "quarter")
        self.assertEqual(p.period_key, "2026-01~2026-03")

    def test_normalization_is_required_for_range(self):
        """正規化を挟まないと `9〜2 月`（空白混入）が P_RANGE に一致しない。

        §4.4.2 の注記。正規化前後で結果が変わることを固定しておく。
        """
        raw = "ビックカメラ 決算／9〜2 月増収増益"
        self.assertIsNone(period.resolve(raw, date(2026, 4, 15)))
        self.assertIsNotNone(period.resolve(textnorm.normalize(raw), date(2026, 4, 15)))

    def test_no_period_expression_returns_none(self):
        for title in ("小売業の「支払手数料」負担がキャッシュレス決済普及で増加", ""):
            with self.subTest(title=title):
                self.assertIsNone(_resolve("2026-04-21", title))


class TestYearInference(unittest.TestCase):
    def test_recent_past_year(self):
        """掲載日以前で直近の (年, month) に寄せる（カタログ §4.2 の 2 規則）。"""
        self.assertEqual(period.recent_past_year(date(2026, 7, 25), 6), 2026)
        self.assertEqual(period.recent_past_year(date(2026, 1, 20), 12), 2025)
        self.assertEqual(period.recent_past_year(date(2026, 7, 25), 7), 2026)

    def test_lag_penalty(self):
        """想定レンジ（1〜2 カ月）を外れたラグは大きく減点する（§4.4.1）。"""
        self.assertEqual(period.lag_penalty(date(2026, 7, 25), date(2026, 6, 1)), 0.05)
        self.assertEqual(period.lag_penalty(date(2026, 7, 25), date(2026, 5, 1)), 0.05)
        self.assertEqual(period.lag_penalty(date(2026, 7, 25), date(2026, 1, 1)), 0.25)

    def test_december_fiscal_period_rolls_to_january(self):
        """12 月決算のときだけ period_start の月が翌年 1 月になる（§4.4.2）。"""
        p = _resolve("2026-03-10", "（検証用）12月期決算")
        self.assertEqual(p.period_key, "FY2025-12")
        self.assertEqual(p.period_start, "2025-01-01")
        self.assertEqual(p.period_end, "2025-12-31")


if __name__ == "__main__":
    unittest.main()
