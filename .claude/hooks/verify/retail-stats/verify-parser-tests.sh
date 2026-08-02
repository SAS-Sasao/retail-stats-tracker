#!/usr/bin/env bash
# .claude/hooks/verify/retail-stats/verify-parser-tests.sh
# ③ 触ったモジュールのテスト実行【PostToolUse】
# loop-engineering-design.md §2.3 ③ / 導入段階 1（§6）
#
# 目的: パーサ変更の即時勾配。編集から数秒で赤が返る状態を作る。
# 発火: PostToolUse / matcher = Write|Edit
# 時間予算: 15 秒（settings.json の timeout は 60 秒）
# exit: 0 = pass / 2 = stderr フィードバック（PostToolUse はブロックしない。§7.2 A1）
#
# テストランナーは標準ライブラリの unittest（U2 で決着。pytest は導入しない）。
set -euo pipefail
source "$(dirname "$0")/_common.sh"
rs_read_stdin

path=$(rs_file_path); [[ -z "$path" ]] && exit 0
rel="$(rs_relpath "$path")"

# 1. $RS_CODE_ROOT 配下の *.py でなければ対象外
case "$rel" in
  "${RS_CODE_ROOT}"/*.py) ;;
  *) exit 0 ;;
esac

code_dir="${RS_REPO_ROOT}/${RS_CODE_ROOT}"
inner="${rel#"${RS_CODE_ROOT}"/}"          # 例: retail_stats/catalog.py / tests/test_catalog.py
base="$(basename "$inner" .py)"

# 2. 対応テストを解決する
#      retail_stats/foo.py → tests.test_foo
#      tests/test_foo.py   → 自分自身
#      見つからない場合    → tests パッケージ全体を discover
target=""
case "$inner" in
  tests/test_*.py) target="tests.${base}" ;;
  retail_stats/*.py|retail_stats/*/*.py)
    [[ -f "${code_dir}/tests/test_${base}.py" ]] && target="tests.test_${base}"
    ;;
esac

# 3. 実行
set +e
if [[ -n "$target" ]]; then
  out=$(cd "$code_dir" && python3 -m unittest "$target" -q 2>&1)
  status=$?
  label="$target"
else
  out=$(cd "$code_dir" && python3 -m unittest discover -s tests -q 2>&1)
  status=$?
  label="tests（discover）"
fi
set -e

[[ $status -eq 0 ]] && exit 0

# 4. 非 0 なら末尾 30 行を stderr へ
rs_block "$(printf 'テストが失敗しています: %s\n\n%s\n' "$label" "$(printf '%s\n' "$out" | tail -30)")"
