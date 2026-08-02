#!/usr/bin/env bash
# .claude/hooks/verify/retail-stats/_common.sh
# B 系統（検証用）hooks の共通ライブラリ。source して使う。
# loop-engineering-design.md §2.1 / §2.2「_common.sh（全スクリプト共通）」
#
# 全スクリプトが参照するパスは本ファイルの 1 箇所にのみ書く（§2.1）。
set -euo pipefail

RS_ORG="domain-tech-collection"
RS_CODE_ROOT="scripts/retail-stats-tracker"
RS_DATA_ROOT=".companies/${RS_ORG}/docs/retail-stats/data"
RS_CATALOG=".companies/${RS_ORG}/docs/retail-domain/retail-monthly-kpi-catalog.md"
RS_DIGEST_DIR=".companies/${RS_ORG}/docs/daily-digest"
RS_HTML="docs/retail-stats/index.html"
RS_STATE_DIR=".companies/${RS_ORG}/.retail-stats-verify"

# 本リポジトリ（retail-stats-tracker）が持つカタログのスナップショット。
# 設計原本は cc-sier-organization 側にあり、そこでは $RS_CATALOG が正準。
# 本リポジトリ単体で開発する間は下記が実体になる（origin.md「入力データの所在」/
# retail_stats/config.py の解決順と一致させること）。
RS_CATALOG_SNAPSHOT="docs/design/retail-monthly-kpi-catalog.md"

# 冪等性・再現性の比較対象（§2.3 ⑤）。実装設計 §5.1 の IDEMPOTENT_FILES と同一の 6 ファイル。
# runs.json は実行時刻を含むため必ず除外する。
# CI 側もこの定数を source して同じ集合を使うこと（§2.7 の契約）
RS_REPRO_FILES="observations.json articles.json extraction-cache.json unresolved.json manifest.json series.json"

# リポジトリルート。hook の cwd はプロジェクトルートである前提だが、
# 依存しきらずに解決しておく（Claude Code は $CLAUDE_PROJECT_DIR を渡す）。
RS_REPO_ROOT="${CLAUDE_PROJECT_DIR:-}"
if [[ -z "$RS_REPO_ROOT" ]]; then
  RS_REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi

# stdin の hook イベント JSON を 1 度だけ読み、以後は $RS_INPUT を使う
rs_read_stdin() {
  RS_INPUT=$(cat)
  export RS_INPUT
}

# JSON から dot path で値を取り出す（jq 非依存。python3 は既存 hooks も前提にしている）
rs_json() {
  python3 -c '
import sys, json
d = json.load(sys.stdin)
for k in sys.argv[1].split("."):
    if isinstance(d, dict):
        d = d.get(k, "")
    else:
        d = ""
print(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False))
' "$1" <<<"$RS_INPUT"
}

# 編集対象のファイルパス（Write / Edit / NotebookEdit 共通）
rs_file_path() {
  local p
  p=$(rs_json "tool_input.file_path")
  [[ -z "$p" ]] && p=$(rs_json "tool_input.path")
  [[ -z "$p" ]] && p=$(rs_json "tool_input.notebook_path")
  printf '%s' "$p"
}

# 絶対パスをリポジトリルート相対に正規化する
rs_relpath() {
  local p="${1#./}"
  p="${p#"$RS_REPO_ROOT/"}"
  p="${p#"$PWD/"}"
  printf '%s' "$p"
}

# 本プロジェクトの管轄パスかどうか（§1.3 の必須ガード）
rs_in_scope() {
  local p
  p="$(rs_relpath "$1")"
  case "$p" in
    "${RS_CODE_ROOT}"/*|"${RS_DATA_ROOT}"/*|"${RS_CATALOG}"|"${RS_CATALOG_SNAPSHOT}"|"${RS_HTML}") return 0 ;;
    *) return 1 ;;
  esac
}

# 編集対象が日次ダイジェスト配下かどうか。
# リポジトリ相対（cc-sier 上で実行した場合の正準配置）に加えて、
# RETAIL_STATS_WORKSPACE で外部ワークスペースを指している場合の絶対パスも見る
# （origin.md D-A。ここを見ないと、作業コピーを指した状態でのダイジェスト書き込みを
# ① が素通ししてしまい、IF-01 の読み取り専用契約が環境によって効いたり効かなかったりする）
rs_is_digest() {
  local p abs
  p="$(rs_relpath "$1")"
  case "$p" in "${RS_DIGEST_DIR}"/*) return 0 ;; esac
  if [[ -n "${RETAIL_STATS_WORKSPACE:-}" ]]; then
    abs="${RETAIL_STATS_WORKSPACE%/}/${RS_DIGEST_DIR}"
    case "$1" in "${abs}"/*) return 0 ;; esac
  fi
  return 1
}

# 編集対象がカタログ MD かどうか（正準 / 本リポのスナップショットの両方を受ける）
rs_is_catalog() {
  local p
  p="$(rs_relpath "$1")"
  [[ "$p" == "$RS_CATALOG" || "$p" == "$RS_CATALOG_SNAPSHOT" ]]
}

# Stop hook の再入ガード。session_id ごとに実行回数を数える（理由は §2.6）
rs_stop_guard() {
  local sid limit=2 n
  # 従: すでに stop hook 起因で継続中なら再検査しない（§2.6）
  [[ "$(rs_json "stop_hook_active")" == "true" ]] && return 1
  sid=$(rs_json "session_id"); [[ -z "$sid" ]] && sid="unknown"
  mkdir -p "${RS_STATE_DIR}/stop"
  local f="${RS_STATE_DIR}/stop/${sid}.$(basename "$0").count"
  n=$(cat "$f" 2>/dev/null || echo 0)
  n=$((n + 1)); printf '%s' "$n" > "$f"
  if (( n > limit )); then
    printf '%s %s 未解決のまま %d 回目の Stop。通過させます\n' \
      "$(date -Iseconds)" "$(basename "$0")" "$n" >> "${RS_STATE_DIR}/unresolved-stops.log"
    return 1   # 呼び出し側は exit 0 する
  fi
  return 0
}

# 変更されたファイルの一覧（作業ツリー + main からの差分）
rs_changed_files() {
  { git diff --name-only HEAD 2>/dev/null || true
    git diff --name-only main...HEAD 2>/dev/null || true
    git ls-files --others --exclude-standard 2>/dev/null || true
  } | sort -u
}

# ブロック終了。stderr が Claude に読まれる
rs_block() {
  printf '\n[retail-stats verify: %s]\n%s\n' "$(basename "$0")" "$1" >&2
  exit 2
}
