#!/usr/bin/env python3
"""実データから決算・統計章のみを抜き出して最小の MD フィクスチャを生成する。

実装設計 §7.3「テストデータの置き場所と切り出し」に対応する。

使用例（実装設計 §7.3）:
    python3 scripts/retail-stats-tracker/tests/make_fixtures.py \\
      --dates 2026-04-14,2026-04-15,2026-04-16,2026-04-17,2026-04-18,2026-04-22,2026-04-23 \\
      --dates 2026-07-22,2026-07-23,2026-07-24,2026-07-25,2026-07-26 \\
      --out scripts/retail-stats-tracker/tests/fixtures/digests/

生成物は「# 日次ダイジェスト YYYY-MM-DD」見出し + 「## B. 小売ドメイン」 +
「### B5. 決算・統計」の表のみを含む。A章・C章・D章は落とす。

選定した日付とその理由（実装設計 §7.3。実データはこのリポジトリではなく
cc-sier-organization 側の .companies/domain-tech-collection/docs/daily-digest/
にある。このスクリプトは cc-sier リポジトリを --source で指す運用を想定する）:
    2026-04-15/16/17/18/22/23: s041442 の非連続6日重複、4つの title variant
    2026-04-14: 決算・統計章そのものが存在しない日
    2026-07-22〜07-26: 主要4業態の6月既存店、全角/半角混在、複数指標分解、
        連続記録表現、生協の総供給高、金額+率の併存、出典名の揺れ 等
"""

from __future__ import annotations

import argparse


def build_arg_parser() -> argparse.ArgumentParser:
    raise NotImplementedError("実装設計 §7.3 の --dates / --out 引数を実装する")


def extract_section(md_text: str, digest_date: str) -> str | None:
    """1日分の日次ダイジェスト MD から B5. 決算・統計 章のみを抜き出す。

    章が存在しない日は None を返す（呼び出し側が 2026-04-14 のように
    「章なし」フィクスチャとして別扱いする）。
    """
    raise NotImplementedError


def main() -> int:
    raise NotImplementedError("実装設計 §7.3 のフィクスチャ生成フローを実装する")


if __name__ == "__main__":
    raise SystemExit(main())
