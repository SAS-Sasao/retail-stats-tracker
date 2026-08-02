#!/usr/bin/env bash
# .claude/skills/retail-stats-verify/scripts/verify.sh
# loop-engineering-design.md §3.2 `/retail-stats-verify`
#
# ②〜⑧ の全検査を逐次実行し、**終了コードで合否を返す**。LLM の目視判断を挟まない。
#
# - 1 つでも非 0 なら全体を非 0 で終える
# - ただし**最初の失敗で止めず全ゲートを走らせる**（--only 指定時を除く）。
#   開発者が 1 往復で全ての問題を把握できるほうがループの回転数が上がる
# - **⑤ は必ず --full 付きで呼ぶ。** Stop hook では並列実行のため読み取り専用に
#   限定しており、破壊的な冪等性検査（R1 / R2）が実際に走る経路は
#   この Skill と CI の 2 つだけである
# - 出力の最終行は必ず機械可読の 1 行サマリー
#
# 未導入のゲート（段階 2 以降）は skip として数え、pass に含めない。
# 「まだ入れていない」ことが緑に見えないようにするため。
set -uo pipefail

REPO_ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$REPO_ROOT"
HOOK_DIR=".claude/hooks/verify/retail-stats"
CODE_ROOT="scripts/retail-stats-tracker"

ONLY=""
CI_MODE=0
for arg in "$@"; do
  case "$arg" in
    --ci) CI_MODE=1 ;;
    --only) ;;
    --only=*) ONLY="${arg#--only=}" ;;
    -h|--help)
      echo "usage: verify.sh [--ci] [--only <gate-name>]"
      exit 0
      ;;
    *) [[ -z "$ONLY" ]] && ONLY="$arg" ;;
  esac
done
[[ $CI_MODE -eq 1 ]] && export RS_CI=1

# ゲート名 → 実行方法。順序は依存の浅い順（契約違反を先に出す）。
GATES=(
  "catalog-contract"
  "parser-tests"
  "dataset-integrity"
  "idempotency"
  "html-selfcontained"
  "coverage-regression"
  "signal-tampering"
)

pass=0; fail=0; skip=0; failed_names=""

run_gate() {
  local name="$1"; shift
  if [[ -n "$ONLY" && "$ONLY" != "$name" ]]; then return 0; fi
  printf '\n=== %s ===\n' "$name"
  "$@"
  local status=$?
  case $status in
    0) pass=$((pass + 1)); printf '  PASS\n' ;;
    77) skip=$((skip + 1)); printf '  SKIP（未導入）\n' ;;
    *) fail=$((fail + 1)); failed_names="${failed_names:+$failed_names,}gate-$name"; printf '  FAIL (exit %d)\n' "$status" ;;
  esac
  return 0
}

# ② カタログ IF-02 契約。hook ではなく検査本体を直接呼ぶ（stdin 非依存）
gate_catalog_contract() {
  python3 "${CODE_ROOT}/validate_catalog.py"
}

# ③ テスト一式（unittest。外部依存なし）
gate_parser_tests() {
  (cd "$CODE_ROOT" && python3 -m unittest discover -s tests)
}

# ④〜⑦ 未導入なら 77（skip）を返す
gate_script() {
  local script="${HOOK_DIR}/$1"; shift
  [[ -x "$script" || -f "$script" ]] || return 77
  bash "$script" "$@" </dev/null
}

run_gate "catalog-contract"   gate_catalog_contract
run_gate "parser-tests"       gate_parser_tests
run_gate "dataset-integrity"  gate_script "gate-dataset-integrity.sh"
run_gate "idempotency"        gate_script "gate-idempotency.sh" --full
run_gate "html-selfcontained" gate_script "gate-html-selfcontained.sh"
run_gate "coverage-regression" gate_script "gate-coverage-regression.sh"
run_gate "signal-tampering"   gate_script "gate-signal-tampering.sh"

total=$((pass + fail + skip))
printf '\n'
printf 'RESULT gates=%d pass=%d fail=%d skip=%d failed=%s\n' \
  "$total" "$pass" "$fail" "$skip" "${failed_names:-none}"

[[ $fail -eq 0 ]] || exit 1
exit 0
