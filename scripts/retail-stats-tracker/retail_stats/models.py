"""全 dataclass 定義と enum。ロジックを持たない（実装設計 §2.3 レイヤ0）。

依存先なし。他の全モジュールから参照される基盤モジュール。
フィールド定義の出典は実装設計 §3.2（Segment/Metric/Catalog）・
§4.1（DigestRow）・§5.2（Observation/SourceArticle の JSON スキーマ）・
§4.2 unresolved_rows（要件定義 §4.2、reason_code 7 値）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# reason_code の enum 7 値（要件定義 §4.2 / v0.1.1 で out_of_scope を追加）。
# 要件 v0.1.2 で **9 値**（cc-sier #728 / #729 で確定）。NFR-05 の分母への
# 影響で 3 群に分かれる（要件 §4.2）。
#   分母に残る失敗: no_metric_match / no_segment_match / no_numeric /
#                   ambiguous_period / low_confidence / llm_schema_error
#   対象外（除外）: out_of_scope / company_disclosure
#   値単位の退避  : no_metric_match_in_multi_value
#                   （行は抽出に成功しているので分母にも分子にも加算しない）
REASON_CODES = (
    "no_metric_match_in_multi_value",
    "company_disclosure",
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

# --- カタログの enum（IF-02 / 実装設計 §3.2・§3.3）-------------------------
# ここは「値の集合」だけを持つ。カタログ日本語表記からこれらへの変換表
# （単位対応表・スコープ対応表・発表主体対応表）は catalog.py 側にある。
ENTITY_TYPES = ("association", "company", "macro")
VALUE_TYPES = ("ratio", "absolute")
DIRECTION_HINTS = ("higher_is_better", "lower_is_better", "neutral")
UNITS = ("percent_yoy", "percent", "jpy_oku", "count", "index")
SCOPES = ("existing_store", "all_store", "total_supply", "n_a")

# 発表主体コード（要件 IF-02 発表主体対応表）。natural key の第 5 要素に
# 入るため、自由記述の日本語ではなく kebab-case のコードで保持する。
SOURCE_AUTHORITY_CODES = (
    "meti",
    "mic",
    "sc-association",
    "department-store-association",
    "chain-store-association",
    "food-service-association",
    "co-op-union",
    "industry-association",
    "trade-press",
    "private-research",
)

# V1: segment_id / metric_id の形式（kebab-case）
ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


class CatalogError(Exception):
    """カタログが IF-02 スキーマ契約に違反したときに送出する（FR-24）。

    実装設計 §3.3 は `catalog.py` に置くと書いているが、`Catalog.validate()`
    が同じ例外を送出する以上、レイヤ 0 の models.py が catalog.py を import
    することになり §2.3 の依存方向（models は何にも依存しない）が壊れる。
    そこで実体を models.py に置き、`catalog.CatalogError` は同じクラスへの
    別名にする（クラスは 1 つだけ）。origin.md「設計書に無い判断」に記録。
    """


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
        for seg in self.segments:
            if seg.segment_id == segment_id:
                return seg
        raise CatalogError(f"未定義の segment_id: {segment_id!r}")

    def metric(self, metric_id: str) -> Metric:
        """未定義なら CatalogError を送出する（FR-24）。"""
        for met in self.metrics:
            if met.metric_id == metric_id:
                return met
        raise CatalogError(f"未定義の metric_id: {metric_id!r}")

    def segment_alias_index(self) -> tuple[tuple[str, str], ...]:
        """(別名, segment_id) の索引。長さ降順（最長一致のため。§3.2）。"""
        return _alias_index((s.aliases, s.segment_id) for s in self.segments)

    def metric_alias_index(self) -> tuple[tuple[str, str], ...]:
        """(別名, metric_id) の索引。長さ降順。"""
        return _alias_index((m.aliases, m.metric_id) for m in self.metrics)

    def validate(self) -> None:
        """V1〜V13（実装設計 §3.3）を検査し、違反があれば CatalogError を送出する。

        1 つでも違反があれば全件を列挙して停止する（部分的に読み込んで続行しない）。

        カタログ MD の行番号は Catalog に持たせていないため、ここでの
        メッセージは ID ベースになる。行番号付きのメッセージは
        `catalog.load()` がパース中に（生セルと行番号が手元にある位置で）
        組み立てる。両者は同じ述語ヘルパを共有しており判定は一致する。
        """
        violations: list[str] = []
        violations += _validate_ids(self.segments, "segment_id")
        violations += _validate_ids(self.metrics, "metric_id")
        violations += _validate_enums(self.segments, self.metrics)
        violations += _validate_parents(self.segments)
        violations += _validate_aliases(self.segments, "segment_id")
        violations += _validate_aliases(self.metrics, "metric_id")
        if violations:
            raise CatalogError(
                f"カタログのバリデーションに失敗しました（{len(violations)} 件）:\n  - "
                + "\n  - ".join(violations)
            )


def _alias_index(pairs) -> tuple[tuple[str, str], ...]:
    """(aliases, id) の並びを (別名, id) の長さ降順索引に畳む。

    同長の別名は文字列昇順で安定させる（走査順に結果が依存しないこと =
    NFR-06 の再現性がキャッシュキーや upsert 順にも効くため）。
    """
    out: list[tuple[str, str]] = []
    for aliases, identifier in pairs:
        out.extend((alias, identifier) for alias in aliases)
    out.sort(key=lambda pair: (-len(pair[0]), pair[0], pair[1]))
    return tuple(out)


def _id_of(row: Segment | Metric, field: str) -> str:
    return getattr(row, field)


def _validate_ids(rows, field: str) -> list[str]:
    """V1（kebab-case）/ V2（一意）。"""
    violations: list[str] = []
    seen: dict[str, int] = {}
    for row in rows:
        identifier = _id_of(row, field)
        if not ID_RE.match(identifier):
            violations.append(f"[V1] 不正な ID 形式: {identifier!r}（{field}）")
        seen[identifier] = seen.get(identifier, 0) + 1
    for identifier, count in seen.items():
        if count > 1:
            violations.append(f"[V2] {field} が重複しています: {identifier!r}（{count} 件）")
    return violations


def _validate_enums(segments, metrics) -> list[str]:
    """V3 / V4 / V5 / V6 / V7 / V8 / V13。"""
    violations: list[str] = []
    for seg in segments:
        if seg.entity_type not in ENTITY_TYPES:
            violations.append(
                f"[V3] 未知の 種別: {seg.entity_type!r}（segment_id={seg.segment_id}）"
            )
        if not _is_non_negative_int(seg.display_order):
            violations.append(
                f"[V8] 表示順が非負整数ではありません: {seg.display_order!r}"
                f"（segment_id={seg.segment_id}）"
            )
        if seg.source_authority not in SOURCE_AUTHORITY_CODES:
            violations.append(
                f"[V13] 未知の発表主体コード: {seg.source_authority!r}"
                f"（segment_id={seg.segment_id}、原文={seg.source_authority_label!r}）。"
                " IF-02 発表主体対応表への追加が必要です"
            )
    for met in metrics:
        if met.value_type not in VALUE_TYPES:
            violations.append(
                f"[V4] 未知の 値種別: {met.value_type!r}（metric_id={met.metric_id}）"
            )
        if met.direction_hint not in DIRECTION_HINTS:
            violations.append(
                f"[V5] 未知の 方向: {met.direction_hint!r}（metric_id={met.metric_id}）"
            )
        if met.unit not in UNITS:
            violations.append(f"[V6] 未知の 単位: {met.unit!r}（metric_id={met.metric_id}）")
        if met.default_scope not in SCOPES:
            violations.append(
                f"[V7] 未知の 既定スコープ: {met.default_scope!r}（metric_id={met.metric_id}）"
            )
        if not _is_non_negative_int(met.precision):
            violations.append(
                f"[V8] 小数桁が非負整数ではありません: {met.precision!r}"
                f"（metric_id={met.metric_id}）"
            )
    return violations


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_parents(segments) -> list[str]:
    """V9（参照先の存在）/ V10（循環なし）。

    `parent_segment_id` は表示上の系統情報としてのみ保持し、ロールアップ
    集約には一切使わない（実装設計 §3.3）。現行カタログでは 13 行すべて
    空欄であり、この 2 検査は将来 `種別=company` 行が追加された場合に
    備えた防御的検査である。
    """
    violations: list[str] = []
    parents = {s.segment_id: s.parent_segment_id for s in segments}
    for segment_id, parent in parents.items():
        if parent is not None and parent not in parents:
            violations.append(f"[V9] 未定義の 上位業態: {parent!r}（segment_id={segment_id}）")
    for segment_id in parents:
        path = [segment_id]
        current = parents[segment_id]
        while current is not None and current in parents:
            if current in path:
                violations.append(
                    "[V10] 上位業態に循環があります: " + " → ".join([*path, current])
                )
                break
            path.append(current)
            current = parents[current]
    return sorted(set(violations), key=violations.index)


def _validate_aliases(rows, field: str) -> list[str]:
    """V11（別名が空でない）/ V12（同一索引内で別名が重複しない）。

    V12 は決定論パースの解決可能性に直結する。別名が衝突していると
    どの ID に寄せるかがコード側の暗黙のルールになり、NFR-09
    （カタログ追記だけで完結する）が崩れる（実装設計 §3.3）。

    **2026-08-02 改訂（cc-sier #729）**: `値種別`（ratio / absolute）が異なる
    指標間では同一別名を許す。記事の実表記では同じ語が率と絶対額の両方を指す
    （`売上高3.2％増` は率 / `売上高1兆4505億円` は絶対額）。この曖昧性は
    記事側に実在するものであり、カタログ §2.2 も「絶対額か率かでさらに分岐」と
    分岐条件を言語化している。パーサは値の型で候補を絞るため一意に決まる。

    **値種別が同一の指標間では引き続き禁止する。** ここを緩めると値の型で
    絞っても一意に決まらず、「どの ID に寄せるか」が結局コード側の暗黙ルールに
    なる。NFR-09 が崩れる境界はここである。
    """
    violations: list[str] = []
    owners: dict[str, list] = {}
    for row in rows:
        identifier = _id_of(row, field)
        if not row.aliases:
            violations.append(f"[V11] 別名が空です: {field}={identifier}")
        for alias in row.aliases:
            owners.setdefault(alias, []).append((identifier, getattr(row, "value_type", None)))
    for alias, holders in owners.items():
        distinct = {i for i, _ in holders}
        if len(distinct) <= 1:
            continue
        # 値種別ごとに分けて、同一値種別の中で重複していれば違反
        by_type: dict[object, set] = {}
        for identifier, value_type in holders:
            by_type.setdefault(value_type, set()).add(identifier)
        for value_type, ids in by_type.items():
            if len(ids) > 1:
                joined = " と ".join(f"{field}={i}" for i in sorted(ids))
                suffix = f"（値種別={value_type}）" if value_type is not None else ""
                violations.append(
                    f"[V12] 別名 {alias!r} が {joined} で重複しています{suffix}"
                )
    return violations


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
        \\x1f 区切りで連結する（実装設計 §5.3）。

        区切りに \\x1f（ASCII Unit Separator）を使うのは、ID 中に現れうる
        `-` との衝突を避けるため（§4.7 と同じ規約）。
        """
        return "\x1f".join((
            self.segment_id, self.metric_id, self.scope, self.period_key, self.source_authority,
        ))


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
