#!/usr/bin/env bash
# .claude/hooks/verify/retail-stats/verify-catalog-contract.sh
# ② カタログ IF-02 スキーマ契約【PostToolUse】
# loop-engineering-design.md §2.3 ② / 導入段階 0（§6）
#
# 目的: カタログ MD が IF-02 スキーマ契約を満たし続けることの保証。
#       NFR-09（指標追加はカタログ追記のみで完結）の裏付け。
# 発火: PostToolUse / matcher = Write|Edit
# exit: 0 = pass / 2 = stderr フィードバック（ブロックはしない。§1.3 A1）
#
# PostToolUse は exit 2 でもツールをブロックしない（仕様 §1.4 "Never Blockable"）。
# 本 hook は「阻止」ではなく「フィードバック」であり、合否の責任は Stop に集約される。
set -euo pipefail
source "$(dirname "$0")/_common.sh"
rs_read_stdin

path=$(rs_file_path); [[ -z "$path" ]] && exit 0
rs_is_catalog "$path" || exit 0

# 検査本体では握り潰しをしない（NFR-10）。stdout に違反一覧、exit 1 で違反あり。
set +e
report=$(python3 "${RS_REPO_ROOT}/${RS_CODE_ROOT}/validate_catalog.py" "${RS_REPO_ROOT}/$(rs_relpath "$path")" 2>&1)
status=$?
set -e

[[ $status -eq 0 ]] && exit 0
rs_block "$report"
