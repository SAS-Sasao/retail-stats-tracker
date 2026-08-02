"""引数解析とパイプラインの結線（実装設計 §2.5 / §2.3 レイヤ4）。

責務: ドメインロジックを持たず、全レイヤ（store / report / llm / html.build /
parser など）を結線して build / html / measure の3サブコマンドを実行するのみ。

対応する実装設計の記述:
    §2.5 エントリポイントと CLI インターフェース（引数表・終了コード契約）
    §2.3 モジュールの責務と依存方向（cli.py は全レイヤに依存してよい唯一のモジュール）

引数（実装設計 §2.5 の表をそのまま反映）:
    --org SLUG                  既定 "domain-tech-collection"
    --rebuild                   manifest を無視して全 MD を処理（FR-12）
    --since YYYY-MM-DD          指定日以降の digest のみ処理（デバッグ用）
    --invalidate-cache          extraction-cache.json を破棄して LLM を再実行
    --no-llm                    LLM を新規に呼ばない（キャッシュヒットは使う）
    --dry-run                   標準出力にサマリーを出すのみでファイルを書かない
    --report-json PATH          差分レポートを JSON で書き出す（FR-22）
    --fail-on-unresolved-rate R 未解決率が R を超えたら exit 1（NFR-05 の CI ガード）

終了コード契約（実装設計 §2.5）:
    0 = 正常
    1 = データ不整合（カタログ検証失敗・未解決率超過）
    2 = 引数エラー
    3 = I/O エラー
`2>/dev/null` や `|| true` による握り潰しをしないこと（NFR-10）。
"""

from __future__ import annotations

import argparse
import sys


def build_arg_parser() -> argparse.ArgumentParser:
    """build / html / measure の3サブコマンドを持つ ArgumentParser を構築する。

    実装設計 §2.5 の引数表に従う。各サブコマンドがどの引数を受け付けるかは
    表の「対象サブコマンド」列のとおりに絞ること（例: --invalidate-cache は
    build のみ）。
    """
    raise NotImplementedError("実装設計 §2.5 の引数表に基づき実装する")


def cmd_build(args: argparse.Namespace) -> int:
    """build サブコマンド。

    digest.py → catalog.py → cache.py → parser.py → llm.py → store.upsert()
    の順に結線する（実装設計 §1.3 パイプライン内部のデータフロー図）。
    """
    raise NotImplementedError("M1〜M5 の完成後に結線する（実装設計 §8 マイルストーン）")


def cmd_html(args: argparse.Namespace) -> int:
    """html サブコマンド。series.json は変更せず HTML のみ再生成する（M6）。"""
    raise NotImplementedError("実装設計 §8 M6 で実装する")


def cmd_measure(args: argparse.Namespace) -> int:
    """measure サブコマンド。

    reason_code 別の未解決分布、NFR-04 / NFR-05 の達成率、発表主体別の
    observation 件数などを計測する（実装設計 §8 M3、要件リスク 7-7 の実装先）。
    独立した PoC フェーズを設けず、恒久的な CLI サブコマンドとして残す。
    """
    raise NotImplementedError("実装設計 §8 M3 で実装する（判断の分岐点）")


def main(argv: list[str] | None = None) -> int:
    """CLI エントリポイント。__main__.py から呼ばれる。"""
    raise NotImplementedError("build_arg_parser() の結果からサブコマンドを振り分ける")
