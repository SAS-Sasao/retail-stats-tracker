"""抽出キャッシュ（FR-08）。実装設計 §4 / extraction-cache.json。

`cache_key → 抽出結果` の読み書き。追記のみ。依存先: models。
llm.py に依存しない（llm が cache を使う、逆ではない。実装設計 §2.3）。

非決定性の封じ込め（NFR-06 / リスク7-6、実装設計 §1.2）:
    LLM は cache.py の背後にのみ存在する。キャッシュヒット時は LLM を
    呼ばない。`--invalidate-cache` を明示指定しない限りキャッシュは
    絶対に破棄しない。

キャッシュキーの決定性（制約3 / 実装設計 §8 M5）: 同一 URL に複数の
title variant が存在する場合でも、キャッシュキーは「数値トークン数 →
長さ → 辞書順」で決定論的に選んだ1 variant から導出する（走査順に
依存させない）。
"""

from __future__ import annotations

from pathlib import Path


def cache_key(url: str, title_variants: tuple[str, ...]) -> str:
    """URL と title_variants から決定論的なキャッシュキーを導出する。

    variant 選択規則: 数値トークン数の多い順 → 文字列長の長い順 →
    辞書順、で1つを選ぶ（実装設計 §8 M5 完了条件）。
    """
    raise NotImplementedError


def load(path: Path) -> dict:
    """extraction-cache.json を読み込む。存在しなければ空の状態を返す。"""
    raise NotImplementedError


def get(cache: dict, key: str) -> dict | None:
    """キャッシュヒットなら抽出結果を返す。ミスなら None。"""
    raise NotImplementedError


def put(cache: dict, key: str, result: dict) -> dict:
    """抽出結果を追記する（既存キーの上書きも含む）。追記のみで削除はしない。"""
    raise NotImplementedError


def save(path: Path, cache: dict) -> None:
    """`cache_key` の昇順にソートしてから書き出す（実装設計 §5.4 冪等性の規則）。

    一時ファイル + os.replace() によるアトミック置換とする（NFR-12）。
    """
    raise NotImplementedError
