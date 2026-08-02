#!/usr/bin/env bash
# .claude/hooks/verify/retail-stats/guard-readonly-inputs.sh
# ① 入力の読み取り専用契約【PreToolUse】
# loop-engineering-design.md §2.3 ① / 導入段階 0（§6）
#
# 目的: IF-01 / 前提 13「本システムは日次ダイジェスト MD を書き換えない」の機械化。
# 発火: PreToolUse / matcher = Write|Edit|NotebookEdit
# 出力: JSON stdout（permissionDecision: "deny"）。§2.5 の限定採用はこの 1 本のみ。
#
# 判定対象: リポジトリ相対の $RS_DIGEST_DIR（cc-sier 上での正準配置）に加えて、
# RETAIL_STATS_WORKSPACE で外部ワークスペースを指している場合の絶対パスも見る
# （rs_is_digest / origin.md D-A）。本リポジトリ単体で作業コピーを指して開発する
# 場合でも IF-01 の読み取り専用契約が効くようにするため。
set -euo pipefail
source "$(dirname "$0")/_common.sh"
rs_read_stdin

RS_AGENTS="retail-stats-qa retail-stats-extractor backend-developer frontend-developer"

path=$(rs_file_path); [[ -z "$path" ]] && exit 0
rs_is_digest "$path" || exit 0

agent=$(rs_json "agent_type"); [[ -z "$agent" ]] && exit 0
grep -qw -- "$agent" <<<"$RS_AGENTS" || exit 0

cat <<JSON
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "retail-stats-tracker は日次ダイジェスト MD を読み取り専用で扱う契約（要件 IF-01 / 前提 13）。${path} への書き込みは、ダイジェストの 3 層レビュー結果を無効化するため許可されない。パース側が入力に合わせるのが正しい方向であり、入力をパースしやすい形に書き換えてはならない。"
  }
}
JSON
exit 0
