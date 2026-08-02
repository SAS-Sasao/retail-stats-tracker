#!/usr/bin/env bash
# .claude/hooks/verify/retail-stats/gate-html-selfcontained.sh
# ⑥ 配信 HTML 自己完結性ゲート【Stop】
# loop-engineering-design.md §2.3 ⑥ / 導入段階 3（§6）
#
# 目的: NFR-08。ネットワークを切った file:// で全機能が動く状態を守る。
# Stop 配下のため**読み取り専用**（$RS_HTML を読むのみ）。
#
# **出典リンク（a[href]）の外部 URL は許す。** FR-19 が要求する機能であり、
# ここで禁じると検査が要件を殺す（段階 3 の完了条件 (c) が明示的に求める確認）。
# 禁じるのは「ページが自分でネットワークを取りに行く」経路のみ。
set -euo pipefail
source "$(dirname "$0")/_common.sh"
rs_read_stdin

rs_stop_guard || exit 0

html="${RS_REPO_ROOT}/${RS_HTML}"
[[ -f "$html" ]] || exit 0

findings=""
# H1: 外部リソースの取得と動的読み込み
for pattern in 'src="http' "fetch(" "import(" "@import"; do
  n=$(grep -c -F -- "$pattern" "$html" || true)
  if [[ "${n:-0}" -gt 0 ]]; then
    findings+="  [external_reference] ${pattern} が ${n} 件"$'\n'
  fi
done
# H2: サイズ上限 2 MB
size=$(wc -c < "$html")
if (( size > 2097152 )); then
  findings+="  [oversize] ${size} bytes > 2097152 bytes"$'\n'
fi
# H3: 出典リンクが失われていないこと（検査が要件を殺していないかの逆方向の確認）
urls=$(grep -c -oE 'https?://[^"]+' "$html" || true)
if [[ "${urls:-0}" -eq 0 ]]; then
  findings+="  [sources_lost] 出典 URL が 1 件も含まれていない（FR-19）"$'\n'
fi

[[ -z "$findings" ]] && exit 0
rs_block "配信 HTML の自己完結性検査に失敗しました。

${findings}
→ NFR-08: JSON / JS / CSS / Chart.js は全てインラインに埋め込むこと。
  出典リンク（a[href] の外部 URL）は残してよい（FR-19）。"
