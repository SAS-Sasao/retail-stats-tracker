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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail_stats import config, digest  # noqa: E402

_H2_RE = re.compile(r"^##\s+(.+)$")
_H3_RE = re.compile(r"^###\s+(.+)$")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="実データから決算・統計章のみを抜き出して最小の MD フィクスチャを生成する"
    )
    parser.add_argument(
        "--dates",
        action="append",
        required=True,
        metavar="YYYY-MM-DD,...",
        help="対象日（カンマ区切り）。複数回指定できる",
    )
    parser.add_argument("--out", required=True, metavar="DIR", help="出力先ディレクトリ")
    parser.add_argument(
        "--source",
        metavar="DIR",
        help="実データの digest ディレクトリ。省略時は config.digest_dir()"
        f"（{config.WORKSPACE_ENV_VAR} で cc-sier の作業コピーを指せる）",
    )
    parser.add_argument("--org", default=config.DEFAULT_ORG, metavar="SLUG")
    return parser


def extract_section(md_text: str, digest_date: str) -> str | None:
    """1日分の日次ダイジェスト MD から B5. 決算・統計 章のみを抜き出す。

    章が存在しない日は None を返す（呼び出し側が 2026-04-14 のように
    「章なし」フィクスチャとして別扱いする）。

    章の検出は `digest.SECTION_KEYWORD` の部分一致であり、章番号（B5）には
    依存しない（要件 7-1）。パーサ側と同じ判定条件を使うことで、
    フィクスチャとパーサが別々の「章の定義」を持つことを防ぐ。
    """
    lines = md_text.splitlines()
    captured: list[str] = []
    in_section = False
    heading = None
    for line in lines:
        stripped = line.strip()
        m3 = _H3_RE.match(stripped)
        if m3:
            in_section = digest.SECTION_KEYWORD in m3.group(1)
            if in_section:
                heading = stripped
            continue
        if _H2_RE.match(stripped):
            in_section = False
            continue
        if in_section:
            captured.append(line.rstrip())
    if heading is None:
        return None
    body = "\n".join(captured).strip("\n")
    return "\n".join(
        [
            f"# 日次ダイジェスト {digest_date}",
            "",
            "## B. 小売ドメイン",
            "",
            heading,
            "",
            body,
            "",
        ]
    )


def main() -> int:
    args = build_arg_parser().parse_args()
    source = Path(args.source) if args.source else config.digest_dir(args.org)
    if not source.is_dir():
        print(
            f"実データの digest ディレクトリがありません: {source}\n"
            f"  → --source で指すか、{config.WORKSPACE_ENV_VAR} に"
            " cc-sier-organization の作業コピーを設定してください（origin.md D-A）",
            file=sys.stderr,
        )
        return 3

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    dates: list[str] = []
    for group in args.dates:
        dates.extend(d.strip() for d in group.split(",") if d.strip())

    written = 0
    for date in sorted(set(dates)):
        src = source / f"{date}.md"
        if not src.is_file():
            print(f"[warn] 実データがありません: {src}", file=sys.stderr)
            continue
        section = extract_section(src.read_text(encoding="utf-8"), date)
        if section is None:
            # 章が無い日も「章が無いこと」を検証するフィクスチャとして生成する
            # （T-10a。存在しないファイルにすると走査対象から外れて検証にならない）
            section = "\n".join(
                [
                    f"# 日次ダイジェスト {date}",
                    "",
                    "## B. 小売ドメイン",
                    "",
                    "### B1. 業態変革・新店",
                    "",
                    "（このフィクスチャは決算・統計章が存在しない日の検証用。"
                    "実データの当日も同章を持たない）",
                    "",
                ]
            )
            print(f"[info] {date}: 決算・統計章なし → 章なしフィクスチャを生成")
        (out / f"{date}.md").write_text(section, encoding="utf-8")
        written += 1

    print(f"{written} 件のフィクスチャを {out} に生成しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
