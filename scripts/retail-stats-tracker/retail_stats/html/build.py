"""series.json + テンプレート → 単一 HTML（FR-13 / FR-14）。実装設計 §6 / §8 M6。

依存先: models, config。パース系（catalog/digest/parser/llm）には依存しない。
JSON + JS + CSS + Chart.js を単一 HTML にインライン埋め込みする
（NFR-08 自己完結。ネットワークを切った file:// でも動作すること）。

series の一意キーは (segment_id, metric_id, scope, source_authority,
period_type)。同一業態・同一指標でも発表主体が異なれば別系列になる
（要件 7-14。実装設計 §6.1）。

series[].points は欠測期間を含めない（FR-20）。periods.month が全期間の
軸を持ち、points に無い期間は「データなし」として描画される。null 埋めに
しないのは、ライブラリ設定を誤ったときに補間が復活する経路を作らないため。

禁則（実装設計 §6 / §8 M6 完了条件、テスト T-10g）:
    生成 HTML に `src="http`、`fetch(`、`import(` を含めないこと（NFR-08）
    HTML 総サイズは 2 MB 以内
    A4 横で印刷してチャートとテーブルが崩れないこと

チャート描画の禁則（実装設計 §6.4 R1〜R8、テスト T-7 / T-9）:
    R1: 発表主体が異なる系列を同一チャートに混ぜない
        （test_chart_spec_rejects_mixed_authority）
    R6: `meti-commerce-dynamics`（小売業全体）と個別業態を同一チャートに
        混ぜない（集計粒度が1段違うため。
        test_chart_spec_rejects_mixed_granularity）
    R8: parent_segment_id によるロールアップ集計を行わない
        （test_no_parent_rollup）

必須7セクション（SC-01〜SC-06。詳細 HTML の構成順序は
implementation-design.md §6 を参照。P3「対象外」パネルは
out_of_scope_breakdown を独立表示し、未解決件数（reason_code 側）と
混ぜないこと。冒頭固定文言:
「これらは抽出の失敗ではなく、本システムの対象範囲外として意図的に
除外した記事です。NFR-05 の分母には含みません。」）
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

# NFR-08: 生成 HTML に含めてはならないパターン（テスト T-10g）。
# 外部リソースを取りに行く経路をひとつも残さない。
FORBIDDEN = (
    re.compile(r'src\s*=\s*["\']https?:'),
    re.compile(r"\bfetch\s*\("),
    re.compile(r"\bimport\s*\("),
    re.compile(r'<link[^>]+href\s*=\s*["\']https?:'),
    re.compile(r"@import\s"),
)
MAX_BYTES = 2 * 1024 * 1024   # 2 MB（実装設計 §8 M6 の完了条件）


class SelfContainedError(Exception):
    """生成物が自己完結していない / サイズ超過のときに送出する（NFR-08）。"""


def _asset(name: str) -> str:
    return (HERE / name).read_text(encoding="utf-8")


def check_self_contained(html: str) -> None:
    """外部参照とサイズを検査する。**書き出す前**に呼ぶ。

    `a[href]` の外部 URL は**残す**。出典リンクは FR-19 が要求する機能であり、
    ここで消すと検査が要件を殺す（ループ設計 §6 段階 3 の完了条件 (c)）。
    禁じているのは「ページが自分でネットワークを取りに行く」経路のみ。
    """
    problems = []
    for pattern in FORBIDDEN:
        for m in pattern.finditer(html):
            problems.append(f"外部参照または動的読み込み: {m.group(0)!r}（位置 {m.start()}）")
    size = len(html.encode("utf-8"))
    if size > MAX_BYTES:
        problems.append(f"サイズ超過: {size:,} bytes > {MAX_BYTES:,} bytes")
    if problems:
        raise SelfContainedError(
            f"自己完結性の検査に失敗しました（{len(problems)} 件）:\n  - " + "\n  - ".join(problems)
        )


def render(series: dict) -> str:
    """series.json（dict）から単一 HTML の文字列を作る（FR-13 / FR-14）。

    JSON / JS / CSS / Chart.js を全てインラインに埋め込む。
    `</script>` はスクリプト文脈を壊すのでエスケープする。
    """
    payload = json.dumps(series, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")      # </script> でスクリプトを閉じさせない
    html = _asset("template.html")
    html = html.replace("__STYLES__", _asset("styles.css"))
    html = html.replace("__SERIES_JSON__", payload)
    html = html.replace("__CHARTJS__", _asset("vendor/chart.umd.min.js"))
    html = html.replace("__APP__", _asset("app.js"))
    check_self_contained(html)
    return html


def build(series: dict, out_path: Path) -> Path:
    """単一 HTML を書き出す。アトミック置換で、失敗時に既存を壊さない（NFR-12）。"""
    out_path = Path(out_path)
    html = render(series)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(html)
    tmp.replace(out_path)
    return out_path
