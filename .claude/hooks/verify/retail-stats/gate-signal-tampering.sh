#!/usr/bin/env bash
# .claude/hooks/verify/retail-stats/gate-signal-tampering.sh
# ⑧ 検証信号の改変検知【Stop】
# loop-engineering-design.md §2.3 ⑧ / 導入段階 1（§6）
#
# 目的: 「検査を通すために検査を緩める」経路を塞ぐ。
# 時間予算: 2 秒。Stop 配下のため**読み取り専用**（§2.2 ★ / §7.2 A3）。
#
# 段階 1（最初期）に置くのは意図的である。検証信号を守る仕組みは、守るべき
# 検証信号が生まれるのと同時に必要になる。後から入れると、それまでに緩められた
# 閾値が「既存行」として免責されてしまう（§2.4）。
#
# 未解決率（L_extract）を下げる方法は 3 つあり、**正しいのは 1 つだけ**である。
#   正規表現ルールを増やす       → 分子を減らす。**正しい**
#   confidence 閾値を下げる       → 誤抽出が増える（T1）
#   取りこぼしを out_of_scope へ  → 分母を縮める（T3）
# 後ろ 2 つは数値上は改善に見え、grep でも見つけにくく、AI にとっては圧倒的に簡単。
#
# 検出対象は**追加された差分行のみ**（`^+`）。既存行は見ない（T5 の注記）。
set -euo pipefail
source "$(dirname "$0")/_common.sh"
rs_read_stdin

rs_stop_guard || exit 0

HOOK_DIR=".claude/hooks/verify/retail-stats"
cd "$RS_REPO_ROOT"

# 追加行のみを取り出す（+++ のファイルヘッダは除く）。
#
# **grep を使わない。** `grep -v '^\+\+\+'` は BRE では `\+` が「1 回以上」の
# 量化子になり、環境によっては不正な正規表現として**エラー終了**する
# （実測: ugrep が `(?m)^+++ invalid syntax` で落ちた）。そこに `|| true` が
# 付いていると、エラーが「一致なし」と区別できないまま握り潰され、
# **ゲートが何も検査しないまま緑を返す**。§1.2 の silent accumulation と
# 同型の事故であり、しかもこのゲート自身がそれを防ぐためのものである。
# awk なら量化子の解釈がぶれず、終了コードも一致件数に依存しない。
diff_added() {
  git diff -U0 HEAD -- "$RS_CODE_ROOT" "$HOOK_DIR" 2>/dev/null \
    | awk '/^\+/ && !/^\+\+\+/'
}

added="$(diff_added)"
findings=""

add_finding() {
  findings+="  [$1] $2"$'\n'
  findings+="    → $3"$'\n'
}

# 一致行を返す。grep の終了コード 1（一致なし）は正常、2 以上は**エラー**であり
# 握り潰さない。ここを握り潰すと検査が死んでいることに気づけない。
hits() {
  local out status
  out=$(printf '%s\n' "$added" | grep -nE "$1")
  status=$?
  if (( status > 1 )); then
    rs_block "内部エラー: パターン照合に失敗しました（grep exit ${status}, pattern=${1}）。
検査が動作していない可能性があるため、緑を返さずに停止します。"
  fi
  printf '%s' "$out"
}

# --- T1: confidence 閾値（既定 0.70 / FR-07）の引き下げ ---------------------
t1="$(hits 'CONFIDENCE_THRESHOLD\s*=\s*0\.(0|1|2|3|4|5|6)')"
[[ -n "$t1" ]] && add_finding "T1" \
  "confidence 閾値の引き下げを検出:"$'\n'"$t1" \
  "FR-07 の既定は 0.70。閾値を下げると低品質な抽出が通り、未解決率は下がるが誤抽出が増える。"

# --- T2: NFR 目標値の緩和 ---------------------------------------------------
t2="$(hits '(0\.9|90)[^0-9].*(NFR-04|主要4|主要 4)|(0\.8|80)[^0-9].*NFR-05|fail-on-unresolved-rate[^0-9]*0\.[3-9]|DEFAULT_FAIL_ON_UNRESOLVED_RATE\s*=\s*0\.[3-9]')"
[[ -n "$t2" ]] && add_finding "T2" \
  "NFR 目標値の緩和と読める変更を検出:"$'\n'"$t2" \
  "目標値の変更は要件改訂として扱う（§4.2 SP3）。コード側で緩めない。"

# --- T3: unresolved 退避のスキップ / 分母操作 -------------------------------
t3="$(hits 'permanently[-_]unresolvable|out_of_scope' | grep -vE 'REASON_CODES|#|\"\"\"' || true)"
t3b="$(hits 'unresolved\.(pop|remove|clear)|del\s+unresolved')"
if [[ -n "$t3b" ]]; then
  add_finding "T3" "unresolved からの行削除を検出:"$'\n'"$t3b" \
    "FR-10 は未解決行を破棄しないことを求めている。"
elif [[ -n "$t3" ]]; then
  add_finding "T3" "out_of_scope 判定木 / permanently-unresolvable への変更を検出:"$'\n'"$t3" \
    "no_segment_match へ落ちる条件を狭める・out_of_scope へ落ちる条件を広げる変更は NFR-05 の分母操作にあたる。件数と原文は保持されるため FR-10 の検査は通ってしまう点に注意（§2.3 ⑧ の表）。"
fi

# --- T4: テストの skip / xfail 追加、assert の純減 --------------------------
t4="$(hits '[sS]kipTest|@unittest\.skip|expectedFailure|pytest\.mark\.(skip|xfail)')"
[[ -n "$t4" ]] && add_finding "T4" \
  "テストの skip 追加を検出:"$'\n'"$t4" \
  "未実装マイルストーンの skip は正当だが、既存の green を skip に変える変更は検証信号の削除にあたる。"

removed_assert=$(git diff -U0 HEAD -- "$RS_CODE_ROOT" 2>/dev/null | grep -cE '^-\s*self\.assert' || true)
added_assert=$(printf '%s\n' "$added" | grep -cE '^\+\s*self\.assert' || true)
if (( removed_assert > added_assert )); then
  add_finding "T4" \
    "assert が純減しています（削除 ${removed_assert} / 追加 ${added_assert}）" \
    "検証の粒度を落とす変更でないことを説明してください。"
fi

# --- T5: 握り潰しの新規追加（NFR-10）----------------------------------------
# _common.sh の rs_changed_files が使う `|| true` は既存行のため対象外
t5="$(hits '2>/dev/null|\|\|\s*true|except\s*:\s*pass|except\s+Exception\s*:\s*pass')"
[[ -n "$t5" ]] && add_finding "T5" \
  "握り潰しの新規追加を検出:"$'\n'"$t5" \
  "NFR-10。失敗が緑に見える経路を増やさないこと。失敗が自明に「対象なし」を意味する箇所に限る。"

# --- T6: 本 hooks ディレクトリ自身の削除・無効化 ----------------------------
deleted_hooks="$(git diff --name-status HEAD -- "$HOOK_DIR" 2>/dev/null | grep -E '^D' || true)"
[[ -n "$deleted_hooks" ]] && add_finding "T6" \
  "検証 hooks の削除を検出:"$'\n'"$deleted_hooks" \
  "検査そのものを消す変更。意図的な場合は理由を明記し retail-stats-qa のレビューを要求してください。"

settings_removed="$(git diff -U0 HEAD -- .claude/settings.json 2>/dev/null | grep -E '^-.*verify/retail-stats' || true)"
[[ -n "$settings_removed" ]] && add_finding "T6" \
  "settings.json からの hook 配線の削除を検出:"$'\n'"$settings_removed" \
  "配線を外すと検査は静かに動かなくなる。"

# --- T7: Stop 経路のスクリプトが $RS_DATA_ROOT に書き込む変更 ---------------
# Stop 配下の全ゲートが読み取り専用であることが、並列実行下で ④ / ⑦ が
# 中間状態を読まないことの唯一の根拠になっている（§2.2 ★）。
for script in "$HOOK_DIR"/gate-*.sh; do
  [[ -f "$script" ]] || continue
  changed="$(git diff -U0 HEAD -- "$script" 2>/dev/null | awk '/^\+/ && !/^\+\+\+/')"
  [[ -z "$changed" ]] && continue
  writes="$(printf '%s\n' "$changed" | grep -E '>\s*"?\$\{?RS_DATA_ROOT|rm |mv |mkdir .*RS_DATA_ROOT|tee .*RS_DATA_ROOT' || true)"
  [[ -n "$writes" ]] && add_finding "T7" \
    "Stop 配下の $(basename "$script") が RS_DATA_ROOT へ書き込む変更を検出:"$'\n'"$writes" \
    "hook は並列実行されるため、Stop 配下は全て読み取り専用でなければ ④ / ⑦ が再構築途中の中間状態を読む。破壊的検査は --full（/retail-stats-verify と CI）に限定すること。"
done

[[ -z "$findings" ]] && exit 0

rs_block "検証信号を弱める変更を検出しました。

${findings}
意図的な場合は、
  (a) 変更前後の値
  (b) 緩和が正当である理由
  (c) 代替の検証手段
を応答に明記し、retail-stats-qa のレビューを要求してください。
機械では意図の善悪を判定できないため、判断を人間と checker に戻します。"
