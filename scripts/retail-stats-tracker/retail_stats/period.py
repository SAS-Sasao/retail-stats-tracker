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

import calendar
import re
from datetime import date

from retail_stats.models import Period

# 元号 → 西暦の基準年（令和8年 = 2018 + 8 = 2026）
ERA_BASE = {"令和": 2018, "平成": 1988}

# カタログ §4.3 の実測レンジ（対象月の翌月 20 日前後に発表される）
EXPECTED_LAG_MONTHS = {1, 2}

# **適用順序が意味を持つ**（実装設計 §4.4.2）。
# `楽天の2026年1-3月期（1Q）…` を P_FY_END に先に当てると `3月期` に一致して
# FY2026-03 になり誤りとなるため、範囲パターンを先に評価する。
P_FY_YEAR = re.compile(r"(?:(?P<y4>[0-9]{4})|(?P<y2>[0-9]{2}))年度")
P_HALF = re.compile(r"(?:(?P<y4>[0-9]{4})年)?(?P<h>上|下)半期")
P_RANGE = re.compile(r"(?<![0-9])(?P<m1>1[0-2]|[1-9])\s*[~-]\s*(?P<m2>1[0-2]|[1-9])月(?P<ki>期)?")
P_FY_END = re.compile(r"(?:(?P<y4>[0-9]{4})|(?P<y2>[0-9]{2}))?年?(?P<m>1[0-2]|[1-9])月期")
P_YM = re.compile(
    r"(?:(?P<era>令和|平成)(?P<ey>[0-9]{1,2})|(?P<y4>[0-9]{4})|(?P<y2>[0-9]{2}))年(?P<m>1[0-2]|[1-9])月(?P<do>度)?"
)
P_MONTH = re.compile(r"(?<![0-9年~-])(?P<m>1[0-2]|[1-9])月(?![期度~\-0-9])")

# 範囲の span → period_type（実装設計 §4.4.2）。
# span 9（3Q 累計）と span 4 は要件 §4.2 の period_type enum に該当する値が無い。
# **enum を勝手に増やさず** ambiguous_period として unresolved に退避する。
SPAN_TO_TYPE = {3: "quarter", 6: "half", 12: "year"}


def recent_past_year(pub: date, month: int) -> int:
    """掲載日 pub 以前で直近の (年, month) の年を返す。

    この 1 行がカタログ §4.2 の 2 つの規則を同時に満たす。
      掲載 2026-07-25 の `6月`  → 6 <= 7  なので 2026（発表ラグ 1 カ月）
      掲載 2026-01-20 の `12月` → 12 > 1 なので 2025（年またぎのロールバック）

    「掲載月の前月」と直接書かないのは、ダイジェストの再掲載や遅れて拾われた
    記事でラグが 1 カ月からずれるため（`s041442` は 6 日間出現する）。
    ラグは信頼度の材料として使う（lag_penalty）。
    """
    return pub.year if month <= pub.month else pub.year - 1


def lag_penalty(pub: date, period_start: date) -> float:
    """掲載日と対象期間開始月のラグから confidence の減点を返す（§4.4.1）。"""
    lag = (pub.year * 12 + pub.month) - (period_start.year * 12 + period_start.month)
    if lag in EXPECTED_LAG_MONTHS:
        return 0.05
    return 0.25  # 想定外のラグ。誤解決の可能性があるため大きく減点する


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _shift(year: int, month: int, delta: int) -> tuple[int, int]:
    """(year, month) を delta か月ずらす。"""
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _two_digit_year(value: str) -> int:
    """2 桁年表記は 2000 年代として補完する（カタログ §4.2）。"""
    return 2000 + int(value)


def _year_from(match: re.Match, pub: date, anchor_month: int) -> int:
    """マッチから年を決める。明示が無ければ掲載日基準で直近の過去に寄せる。"""
    if match.groupdict().get("era"):
        return ERA_BASE[match.group("era")] + int(match.group("ey"))
    if match.groupdict().get("y4"):
        return int(match.group("y4"))
    if match.groupdict().get("y2"):
        return _two_digit_year(match.group("y2"))
    return recent_past_year(pub, anchor_month)


def _fiscal_year(year: int) -> Period:
    """日本の会計年度（4 月始まり）。`2025年度` → 2025-04-01〜2026-03-31。"""
    return Period(
        period_key=f"FY{year}",
        period_type="fiscal_year",
        period_start=date(year, 4, 1).isoformat(),
        period_end=_month_end(year + 1, 3).isoformat(),
    )


def _fiscal_period(year: int, month: int) -> Period:
    """決算期末月。`2月期` → 2025-03-01〜2026-02-28。

    period_start は「決算期末月の翌月の 1 年前」。12 月決算のときだけ翌月が
    翌年 1 月になるため、月の繰り上げは `month % 12 + 1` で行う（§4.4.2）。
    """
    start_month = month % 12 + 1
    start_year = year - 1 if start_month != 1 else year
    return Period(
        period_key=f"FY{year}-{month:02d}",
        period_type="fiscal_year",
        period_start=date(start_year, start_month, 1).isoformat(),
        period_end=_month_end(year, month).isoformat(),
    )


def _month(year: int, month: int) -> Period:
    return Period(
        period_key=f"{year}-{month:02d}",
        period_type="month",
        period_start=date(year, month, 1).isoformat(),
        period_end=_month_end(year, month).isoformat(),
    )


def _range(end_year: int, m1: int, m2: int) -> Period | None:
    """`N~M月` を span から解決する。span が enum に無ければ None（§4.4.2）。"""
    span = (m2 - m1) % 12 + 1
    period_type = SPAN_TO_TYPE.get(span)
    if period_type is None:
        return None
    start_year, start_month = _shift(end_year, m2, -(span - 1))
    return Period(
        period_key=f"{start_year}-{start_month:02d}~{end_year}-{m2:02d}",
        period_type=period_type,
        period_start=date(start_year, start_month, 1).isoformat(),
        period_end=_month_end(end_year, m2).isoformat(),
    )


def resolve_with_penalty(window_text: str, pub: date) -> tuple[Period | None, float]:
    """`resolve()` に confidence の減点を添えて返す（実装設計 §4.5 の期間の行）。

    | 条件 | 減点 |
    |---|---|
    | 年が明示されている（P_YM / P_FY_YEAR / P_HALF） | 0.00 |
    | 年を推定（P_MONTH / P_FY_END）でラグが 1〜2 カ月 | 0.05 |
    | 同上でラグが範囲外 | 0.25 |
    | P_RANGE の span が enum 内 | 0.05 |

    どのパターンで解決したかは `Period` の 4 フィールド（§3.2 で固定）からは
    復元できないため、解決と同時に返す。Period 側にフィールドを足さないための
    設計（origin.md D-B）。
    """
    if P_FY_YEAR.search(window_text) or P_HALF.search(window_text):
        return resolve(window_text, pub), 0.00
    if P_RANGE.search(window_text):
        return resolve(window_text, pub), 0.05
    m = P_YM.search(window_text)
    if m:
        return resolve(window_text, pub), 0.00      # 年が明示されている
    resolved = resolve(window_text, pub)
    if resolved is None:
        return None, 0.00
    # **発表ラグは「期末」から測る。** §4.4.1 の lag_penalty は月次を想定して
    # period_start を引数に取るが、決算期（P_FY_END）の period_start は期末の
    # 約 1 年前であり、そのまま渡すと必ずラグ 13〜14 カ月になって常に 0.25 に
    # 落ちる。`イオン 決算／2月期`（2026-02 期末）が 2026-04 に掲載されるのは
    # ラグ 2 カ月であって想定内である。月次は period_start と period_end が
    # 同月なので、期末基準にしても月次の判定は変わらない。
    return resolved, lag_penalty(pub, date.fromisoformat(resolved.period_end))


def resolve(window_text: str, pub: date) -> Period | None:
    """正規化済み文字列 window_text と掲載日 pub から Period を解決する。

    解決できない場合は None を返し、呼び出し側（parser.py）が
    reason_code="ambiguous_period" として unresolved に落とす。

    `window_text` は `textnorm.normalize()` を通した文字列であること。
    正規化を挟まないと `9〜2 月`（数値と `月` の間に空白）が P_RANGE に
    一致しない（§4.4.2 の注記）。
    """
    m = P_FY_YEAR.search(window_text)
    if m:
        return _fiscal_year(_year_from(m, pub, 3))

    m = P_HALF.search(window_text)
    if m:
        first = m.group("h") == "上"
        anchor = 6 if first else 12
        year = _year_from(m, pub, anchor)
        start_month, end_month = (1, 6) if first else (7, 12)
        return Period(
            period_key=f"{year}-H{1 if first else 2}",
            period_type="half",
            period_start=date(year, start_month, 1).isoformat(),
            period_end=_month_end(year, end_month).isoformat(),
        )

    m = P_RANGE.search(window_text)
    if m:
        m1, m2 = int(m.group("m1")), int(m.group("m2"))
        return _range(recent_past_year(pub, m2), m1, m2)

    m = P_FY_END.search(window_text)
    if m:
        month = int(m.group("m"))
        return _fiscal_period(_year_from(m, pub, month), month)

    m = P_YM.search(window_text)
    if m:
        month = int(m.group("m"))
        return _month(_year_from(m, pub, month), month)

    m = P_MONTH.search(window_text)
    if m:
        month = int(m.group("m"))
        return _month(recent_past_year(pub, month), month)

    return None
