"""カタログローダ（FR-03 / FR-24 / IF-02）。実装設計 §3。

業態名・指標名・別名をコードに一切書かない、唯一のカタログ読取口。
パーサは Catalog オブジェクト経由でのみ ID を得る。カタログに無い ID を
コードが生成する経路を持たない（FR-24）。

依存先: models, textnorm。digest / parser には依存しない（対称性のため）。

4段階の処理（実装設計 §3.1）:
    段階1 見出し検出（部分一致・番号非依存。0個/2個以上ならエラー停止）
    段階2 定義表の特定（見出し直後〜次の H2 直前の「最初の MD テーブル」）
    段階3 列名解決（許容リスト。必須列が1つでも解決できなければ CatalogError）
    段階4 セル値の解釈（clean_cell / cell_head / split_aliases / resolve_unit）
"""

from __future__ import annotations

from pathlib import Path

from retail_stats.models import Catalog

SEGMENT_HEADING_KEYWORDS = ("業態区分",)
METRIC_HEADING_KEYWORDS = ("指標定義", "KPI定義")  # 照合前に空白を除去する

SEGMENT_COLUMNS: dict[str, tuple[str, ...]] = {
    "segment_id": ("segment_id", "業態ID"),
    "name": ("名称", "正式名称"),
    "aliases": ("別名", "表記ゆれ"),
    "entity_type": ("種別",),
    "source_authority": ("発表主体",),  # 必須。natural key の第5要素の供給源
    "display_order": ("表示順",),
}
SEGMENT_OPTIONAL_COLUMNS: dict[str, tuple[str, ...]] = {"parent_segment_id": ("上位業態",)}

METRIC_COLUMNS: dict[str, tuple[str, ...]] = {
    "metric_id": ("metric_id", "KPI ID", "KPIID"),
    "name": ("名称", "正式名称"),
    "aliases": ("別名", "表記ゆれ"),
    "unit_raw": ("単位",),
    "value_type": ("値種別",),
    "direction_hint": ("方向",),
    "default_scope_raw": ("既定スコープ", "既存店/全店"),
    "precision": ("小数桁",),
}

UNIT_TOKEN_MAP = {"%": "percent_yoy", "％": "percent_yoy", "億円": "jpy_oku", "兆円": "jpy_oku"}


class CatalogError(Exception):
    """カタログが IF-02 スキーマ契約に違反したときに送出する（FR-24）。"""


def clean_cell(cell: str) -> str:
    """強調記法（`**`）とバッククォートを剥がす（実装設計 §3.1 段階4）。"""
    raise NotImplementedError


def cell_head(cell: str) -> str:
    """括弧注記・併記を落として先頭ラベルのみ取る（実装設計 §3.1 段階4）。

    例: '該当なし（`co-op` は総供給高で上書き。§4.5 参照）' → '該当なし'
    """
    raise NotImplementedError


def split_aliases(cell: str) -> list[str]:
    """別名セルを区切り文字（, 、 / ／）で分割し、空・ダッシュ相当を除く。"""
    raise NotImplementedError


def resolve_unit(cell: str, metric_id: str) -> str:
    """単位セルをトークンごとに UNIT_TOKEN_MAP と照合する（実装設計 §3.1）。

    `億円 / 兆円` のような複数トークン併記は、写像後の集合が1要素であれば
    その値に一本化する。0要素または2要素以上なら CatalogError。
    """
    raise NotImplementedError


def load(path: Path) -> Catalog:
    """カタログ MD を読み込み、4段階処理を経て Catalog を返す。

    末尾で `Catalog.validate()`（V1〜V13）を実行し、1件でも違反があれば
    CatalogError を送出して停止する（部分的な読み込みで続行しない）。
    """
    raise NotImplementedError("実装設計 §3 の4段階処理 + §3.3 バリデーションを実装する")
