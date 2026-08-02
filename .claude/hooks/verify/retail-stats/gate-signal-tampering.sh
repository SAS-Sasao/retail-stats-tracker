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

# T3 の判定木スキャンは**実装コードと hooks に限る**。
# `tests/fixtures/golden-60.candidates.jsonl` は区分名として `out_of_scope` の
# 文字列を全行に持つ機械生成物であり、キーワード一致では常に発火してしまう。
# ただし**評価データを緩める経路は塞いだままにする**必要があるので、
# 凍結済み golden-60 の期待値変更は下の専用検査で捕まえる。
code_added="$(git diff -U0 HEAD -- "${RS_CODE_ROOT}/retail_stats" "$HOOK_DIR" | awk '/^\+/ && !/^\+\+\+/')"

hits_in() {
  local body="$1" pattern="$2" out status
  out=$(printf '%s\n' "$body" | grep -nE "$pattern")
  status=$?
  if (( status > 1 )); then
    rs_block "内部エラー: パターン照合に失敗しました（grep exit ${status}）。"
  fi
  printf '%s' "$out"
}
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
t3="$(hits_in "$code_added" 'permanently[-_]unresolvable|out_of_scope' | awk '!/REASON_CODES|#/')"
t3b="$(hits_in "$code_added" 'unresolved\.(pop|remove|clear)|del\s+unresolved')"

# T3-c 凍結済み golden-60 の**期待値そのもの**の変更。
# 評価データの正解を `no_segment_match` → `out_of_scope` に書き換えるのは、
# 判定木を緩めるのと同じ効果（NFR-05 の分母操作）を、コードに触れずに達成する経路。
# 候補ファイル（機械生成・再生成される）ではなく、凍結ファイルだけを見る。
GOLDEN_FROZEN="${RS_CODE_ROOT}/tests/fixtures/golden-60.jsonl"
t3c="$(git diff -U0 HEAD -- "$GOLDEN_FROZEN" | awk '/^[+-]/ && !/^(\+\+\+|---)/ && /reason_code/' | wc -l)"
if [[ "${t3c:-0}" -gt 0 ]]; then
  add_finding "T3" \
    "凍結済み golden-60 の期待値（reason_code）の変更を検出（${t3c} 行）" \
    "評価データの正解を書き換えるのは、判定木を緩めるのと同じ効果をコードに触れずに達成する経路。変更理由と、その行の期待値が本当に誤っていた根拠を示すこと。"
fi
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
# パターン中の末尾 1 文字を文字クラス（`[l]` `[e]` `[s]`）にしてあるのは、
# **この行自身が検出対象に一致するのを避けるため**である。検出器のパターン定義が
# 自分自身に当たると、ゲートは毎回自分を指摘して赤のままになる。文字クラス化しても
# 対象文字列への一致は変わらないので、検出力は落ちない。
# 同じ理由で、この節のコメントには検出対象の文字列そのものを書かない。
t5="$(hits '2>/dev/nul[l]|\|\|\s*tru[e]|except\s*:\s*pas[s]|except\s+[A-Za-z]+\s*:\s*pas[s]')"
[[ -n "$t5" ]] && add_finding "T5" \
  "握り潰しの新規追加を検出:"$'\n'"$t5" \
  "NFR-10。失敗が緑に見える経路を増やさないこと。失敗が自明に「対象なし」を意味する箇所に限る。"

# **例外の握り潰しは 2 行に分かれるのが普通**。`except Exception:` と `pass` が
# 別行にあるのが Python の通常の書き方であり、1 行形式しか見ないと実質検出できない。
# 追加行に except と（コメントのみを伴う）pass の両方があれば申告を求める。
t5_except="$(hits '^\+\s*except\b.*:\s*$')"
t5_pass="$(hits '^\+\s*pas[s]\s*(#.*)?$')"
if [[ -n "$t5_except" && -n "$t5_pass" ]]; then
  add_finding "T5" \
    "例外の握り潰し（複数行の except / pass）の追加を検出:"$'\n'"${t5_except}"$'\n'"${t5_pass}" \
    "NFR-10。except で握り潰すと失敗が緑に見える。捕捉するなら理由を限定し、再送出するか記録すること。"
fi

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
