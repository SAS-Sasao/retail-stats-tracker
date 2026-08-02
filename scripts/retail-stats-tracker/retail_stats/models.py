"""全 dataclass 定義と enum。ロジックを持たない（実装設計 §2.3 レイヤ0）。

依存先なし。他の全モジュールから参照される基盤モジュール。
フィールド定義の出典は実装設計 §3.2（Segment/Metric/Catalog）・
§4.1（DigestRow）・§5.2（Observation/SourceArticle の JSON スキーマ）・
§4.2 unresolved_rows（要件定義 §4.2、reason_code 7 値）。
"""

from __future__ import annotations

from dataclasses import dataclass

# reason_code の enum 7 値（要件定義 §4.2 / v0.1.1 で out_of_scope を追加）。
REASON_CODES = (
    "no_metric_match",
    "no_segment_match",
    "no_numeric",
    "ambiguous_period",
    "low_confidence",
    "llm_schema_error",
    "out_of_scope",
)

# extraction_method の値（実装設計 §1.2 二段ハイブリッド）
EXTRACTION_METHODS = ("deterministic", "llm")


@dataclass(frozen=True)
class Segment:
    """業態マスタ 1 件（実装設計 §3.2）。カタログ「## 1. 業態区分マスタ」の 1 行。"""

    segment_id: str
    name: str
    aliases: tuple[str, ...]  # name を含めて重複除去済み・長さ降順ソート済み
    parent_segment_id: str | None  # 表示のみに使う。集約には使わない（§3.3）
    entity_type: str  # association / company / macro
    source_authority: str  # 既定の発表主体コード（IF-02 発表主体対応表で解決）
    source_authority_label: str  # 表示用。カタログ「発表主体」列の原文
    display_order: int


@dataclass(frozen=True)
class Metric:
    """指標マスタ 1 件（実装設計 §3.2）。カタログ「## 2. KPI 定義」の 1 行。"""

    metric_id: str
    name: str
    unit: str  # percent_yoy / percent / jpy_oku / count / index
    value_type: str  # ratio / absolute
    direction_hint: str  # higher_is_better / lower_is_better / neutral
    aliases: tuple[str, ...]
    default_scope: str  # existing_store / all_store / total_supply / n_a
    precision: int


@dataclass(frozen=True)
class Catalog:
    """業態・指標マスタ全体（実装設計 §3.2）。`catalog.py` の唯一の返却型。"""

    segments: tuple[Segment, ...]  # display_order 昇順
    metrics: tuple[Metric, ...]  # カタログ記載順
    source_path: str
    source_sha256: str  # カタログ改訂の検知に使う（§3.3）

    def segment(self, segment_id: str) -> Segment:
        """未定義なら CatalogError を送出する（FR-24）。"""
        raise NotImplementedError

    def metric(self, metric_id: str) -> Metric:
        """未定義なら CatalogError を送出する（FR-24）。"""
        raise NotImplementedError

    def segment_alias_index(self) -> tuple[tuple[str, str], ...]:
        """(別名, segment_id) の索引。長さ降順（最長一致のため。§3.2）。"""
        raise NotImplementedError

    def metric_alias_index(self) -> tuple[tuple[str, str], ...]:
        """(別名, metric_id) の索引。長さ降順。"""
        raise NotImplementedError

    def validate(self) -> None:
        """V1〜V13（実装設計 §3.3）を検査し、違反があれば CatalogError を送出する。

        1 つでも違反があれば全件を列挙して停止する（部分的に読み込んで続行しない）。
        """
        raise NotImplementedError


@dataclass(frozen=True)
class DigestRow:
    """日次ダイジェスト「決算・統計」章の表 1 行（実装設計 §4.1）。"""

    digest_date: str  # "2026-07-25"（ファイル名由来）
    row_index: int  # 表内の # 列の値
    title: str  # 原文（正規化前）
    url: str
    source_name: str
    summary: str
    raw_line: str  # 未解決時の証跡（FR-10）


@dataclass(frozen=True)
class Period:
    """期間解決の結果（実装設計 §4、period.py が返す型）。"""

    period_key: str  # 例: "2026-06" / "FY2026-02" / "2026-03~2026-05" / "2026-H1"
    period_type: str  # month / quarter / half / fiscal_year
    period_start: str  # ISO 日付
    period_end: str


@dataclass(frozen=True)
class Observation:
    """観測値 1 件（実装設計 §5.2 の JSON スキーマに対応）。

    natural key は (segment_id, metric_id, scope, period_key, source_authority)
    の 5 要素（要件 v0.1.1 FR-09、実装設計 §9.3 D1）。source_authority を
    含めることで、協会統計と経産省統計など発表主体の異なる系列を
    上書きさせずに共存させる（要件 7-14）。
    """

    observation_id: str
    segment_id: str
    metric_id: str
    scope: str  # existing_store / all_store / total_supply / n_a
    source_authority: str
    period_key: str
    period_type: str
    period_start: str
    period_end: str
    value: float | None  # sign_only の場合は None（制約 11）
    unit: str
    streak_broken_months: int | None
    sign_only: str | None  # "+" / "-" / None
    needs_source_check: bool
    raw_expression: str
    article_id: str
    extraction_method: str  # deterministic / llm
    confidence: float
    manual_override: bool  # True の場合、自動 upsert は上書きしない（FR-23）
    first_seen_date: str
    last_updated_date: str

    def natural_key(self) -> str:
        """(segment_id, metric_id, scope, period_key, source_authority) を
        \\x1f 区切りで連結する（実装設計 §5.3）。"""
        raise NotImplementedError


@dataclass(frozen=True)
class SourceArticle:
    """記事（URL 単位）1 件（実装設計 §5.2）。"""

    article_id: str  # sha256(url) の先頭16桁
    url: str
    title_first_seen: str
    title_variants: tuple[str, ...]  # 原文のまま。辞書順ソート済み
    source_name: str
    source_name_normalized: str
    first_published_date: str
    appeared_dates: tuple[str, ...]  # 昇順。非連続日も許容する（NFR-07）


@dataclass(frozen=True)
class UnresolvedRow:
    """未解決行 1 件（要件定義 §4.2 unresolved_rows。5 列のまま拡張しない）。

    実装設計 §4.3.7: 同一記事の重複行は (article_id, reason_code) で
    1 エントリに集約し、digest_date には初出日を入れる。掲載回数は持たせない。
    """

    id: str
    digest_date: str
    raw_line: str
    reason_code: str  # REASON_CODES のいずれか
    last_attempted_at: str


@dataclass(frozen=True)
class UpsertResult:
    """store.upsert() の結果（実装設計 §5.3）。"""

    action: str  # created / updated / unchanged / skipped_manual
    key: str
    before: Observation | None
    after: Observation
