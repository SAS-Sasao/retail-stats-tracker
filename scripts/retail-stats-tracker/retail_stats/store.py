"""JSON 永続化・冪等 upsert（FR-09 / FR-23）。実装設計 §5。

依存先: models, config。parser / llm には依存しない（永続化の都合を
上位に漏らさない。実装設計 §2.3）。

natural key は5要素 (segment_id, metric_id, scope, period_key,
source_authority)（要件 v0.1.1 FR-09、実装設計 §9.3 D1）。
source_authority を含めることで、協会統計と経産省統計など発表主体の
異なる系列を上書きさせず共存させる（要件 7-14）。

冪等性の担保（NFR-06 バイト一致。実装設計 §5.4 の6規則。1つでも欠けると
一致しない）:
    1. dict のキー順に依存しない出力（sort_keys=True 相当）
    2. 書き出し前に全コレクションをソートする（observations は
       natural key の各要素順、articles は article_id、unresolved は
       (article_id, reason_code)、cache は cache_key の昇順）
    3〜6. 実装時に implementation-design.md §5.4 を直接参照して実装する

比較対象6ファイル（config.IDEMPOTENT_FILES と同一。runs.json は実行時刻を
含むため除外）: observations.json / articles.json / extraction-cache.json /
unresolved.json / manifest.json / series.json
"""

from __future__ import annotations

from pathlib import Path

from retail_stats.models import Observation, UpsertResult

NATURAL_KEY_FIELDS = ("segment_id", "metric_id", "scope", "period_key", "source_authority")


def natural_key(o: Observation) -> str:
    """NATURAL_KEY_FIELDS を \\x1f 区切りで連結する（実装設計 §5.3）。"""
    raise NotImplementedError


def observation_id(o: Observation) -> str:
    """natural_key の sha256 先頭16桁（実装設計 §5.3）。"""
    raise NotImplementedError


def upsert(index: dict[str, Observation], new: Observation) -> UpsertResult:
    """natural key で収束させる（実装設計 §5.3）。

    - manual_override=True の既存レコードは自動 upsert で上書きしない（FR-23）
    - _wins() が True の場合のみ更新。confidence が高い方が勝つ。同値なら
      掲載日が新しい方。それも同値なら既存を維持する（走査順非依存、NFR-06）
    - 発表主体が異なる観測（natural key が異なる）は upsert 対象にならず、
      別レコードとして共存する（要件 7-14 への構造的対処）
    """
    raise NotImplementedError


def _wins(new: Observation, old: Observation) -> bool:
    """FR-09 の勝敗規則。完全同点では False（既存維持）を返すこと（NFR-06）。"""
    raise NotImplementedError


def validate_integrity(observations: list[Observation], catalog, articles) -> None:
    """参照整合性を検査する（実装設計 §5.5 / D1〜D6 相当）。

    違反があれば IntegrityError を送出し、書き出さない
    （implementation-design.md §7.2 T-6 test_integrity_check_blocks_write）。
    """
    raise NotImplementedError


class IntegrityError(Exception):
    """未定義 ID の混入や natural key 重複など、参照整合性違反時に送出する。"""


def load_all(data_dir: Path) -> dict:
    """observations.json / articles.json / unresolved.json / manifest.json /
    extraction-cache.json / series.json / runs.json を読み込む。

    存在しないファイルは「未構築」として扱い、空の状態を返す。
    """
    raise NotImplementedError


def save_all(data_dir: Path, state: dict) -> None:
    """全コレクションをソートしてから、一時ファイル + os.replace() で
    アトミックに書き出す（NFR-12）。生成失敗時は既存の成果物を空で
    上書きしない。
    """
    raise NotImplementedError
