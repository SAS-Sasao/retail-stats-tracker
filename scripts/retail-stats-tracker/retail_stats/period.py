"""期間表現 → Period 解決（FR-06）。実装設計 §4（テストは §7.2 T-5）。

依存先: models, textnorm。掲載日は引数で受け取り、グローバル日時（datetime.now
等）には触れない（実装設計 §2.3。掲載日は digest_date 由来であり、実行時刻を
含めないことが NFR-06 バイト一致・冪等性の前提）。

対応するパターン（実装設計 §7.2 T-5 PERIOD_CASES から要約。詳細は同節参照）:
    月次       "6月既存店売上1.6％減" → "2026-06" (month)
    年またぎ月 12月の記事が1月公開 → 前年の12月に解決
    決算期     "2 月期増収増益" → "FY{year}-02" (fiscal_year)
    2桁年決算期 "26年2月期" → 4桁年に正規化
    将来期     "29年2月期" → 未来日付でも解決する
    四半期範囲 "3〜5月" → "2026-03~2026-05" (quarter)
    半期範囲   "9〜2月"（年またぎ）→ "2025-09~2026-02" (half)
    年度       "2025年度" → "FY2025" (fiscal_year)
    元号       "令和8年2月度" → 西暦に変換
    上半期     "2026年上半期" → "2026-H1" (half)

**評価順序の注意**（T-5 test_range_pattern_beats_fiscal_year_end）:
    範囲パターン（P_RANGE）を決算期末パターン（P_FY_END）より先に評価しないと
    「2026年1-3月期」が「3月期」に誤マッチする。

解決不能な場合（span が大きすぎる曖昧な範囲等）は reason_code =
"ambiguous_period" として unresolved に落とす
（T-5 PERIOD_UNRESOLVED_CASES: span=9 の "6〜2月" 等）。
"""

from __future__ import annotations

from datetime import date

from retail_stats.models import Period


def resolve(window_text: str, pub: date) -> Period | None:
    """正規化済み文字列 window_text と掲載日 pub から Period を解決する。

    解決できない場合は None を返し、呼び出し側（parser.py）が
    reason_code="ambiguous_period" として unresolved に落とす。
    """
    raise NotImplementedError("実装設計 §7.2 T-5 の各パターンを実装する")
