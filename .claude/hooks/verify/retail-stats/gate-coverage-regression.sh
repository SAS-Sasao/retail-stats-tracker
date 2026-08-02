#!/usr/bin/env bash
# .claude/hooks/verify/retail-stats/gate-coverage-regression.sh
# ⑦ カバレッジ回帰ゲート【Stop / 日次バッチ内】
# loop-engineering-design.md §2.3 ⑦ / §2.4（配線 = 段階 0 / 実効化 = 段階 2 /
# 日次からの呼び出し = 段階 5）
#
# 目的: L_silent の検出。§1.2 の silent accumulation に対する唯一の能動的な防波堤。
# 発火: Stop（開発ループ）+ 日次バッチ内から同一スクリプトを再利用（運用ループ）
# 時間予算: 2 秒（runs.json の走査のみ）
#
# **本ファイルは段階 0 の「配線だけ先に入れる」ための最小実装である。**
# §2.2 の配線上の注意が、配線を段階 5 まで先送りすると「発火しないゲートが
# 仕様上は存在する」状態になると明示しているため、settings.json 側と揃えて
# 段階 0 で置く。判定ロジック S1〜S4 の実装は段階 2（runs.json が生成される
# 段階）で行う。
#
# 段階 0 時点の挙動:
#   runs.json が無い  → exit 0（判定対象が存在しない。設計 手順 1 のとおり）
#   runs.json が有る  → rs_block（S1〜S4 未実装。判定できないものを
#                        「pass」と報告しない。silent accumulation を最大の
#                        危険とする本設計で、未実装のゲートが緑を返すのは
#                        まさにその事故そのものであるため）
#
# Stop 配下のため**読み取り専用**を厳守する（§2.2 ★ / §7.2 A3 / ⑧ T7）。
# $RS_DATA_ROOT には一切書き込まない。
set -euo pipefail
source "$(dirname "$0")/_common.sh"
rs_read_stdin

rs_stop_guard || exit 0

runs="${RS_REPO_ROOT}/${RS_DATA_ROOT}/runs.json"
[[ -f "$runs" ]] || exit 0

rs_block "カバレッジ回帰ゲート（⑦ S1〜S4）が未実装のまま ${RS_DATA_ROOT}/runs.json が生成されています。

  [not_implemented] gate-coverage-regression.sh: 判定ロジック S1〜S4 が未実装
    → ループ設計 §2.3 ⑦ に従って実装してください（導入段階 2）。
       S1 rows_parsed < 直近 7 実行の中央値 * 0.8
       S2 「対象セクションを検出できたファイル数 = 0」が 3 実行連続
       S3 series.json の quality.nfr05 から未解決率 > 0.20（分母・分子は
          そのまま読む。このゲート内で計算式を再実装しない）
       S4 nfr05.denominator が直近 7 実行の中央値 * 0.8 を下回る

判定できない状態を pass として報告しないため、ここで止めています。"
