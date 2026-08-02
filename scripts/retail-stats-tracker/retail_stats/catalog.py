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

`CatalogError` の実体は models.py にある（レイヤ 0 の依存方向を保つため。
models.CatalogError の docstring 参照）。ここでは同じクラスを再輸出する。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from retail_stats.models import (
    ID_RE,
    Catalog,
    CatalogError,
    Metric,
    Segment,
)

__all__ = [
    "CatalogError",
    "SEGMENT_HEADING_KEYWORDS",
    "METRIC_HEADING_KEYWORDS",
    "SEGMENT_COLUMNS",
    "SEGMENT_OPTIONAL_COLUMNS",
    "METRIC_COLUMNS",
    "UNIT_TOKEN_MAP",
    "SCOPE_TOKEN_MAP",
    "AUTHORITY_TOKEN_MAP",
    "clean_cell",
    "cell_head",
    "split_aliases",
    "split_table_row",
    "is_separator_row",
    "normalize_header",
    "resolve_unit",
    "resolve_scope",
    "resolve_authority",
    "load",
]

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

# スコープ対応表（要件 IF-02 / カタログ §4.5）。`co-op` × `sales-amount-absolute`
# の `total_supply` 上書きはカタログ表の 1 セルでは表現されないため、
# ローダではなく parser.resolve_scope() 側の解決規則として実装する（§3.3）。
SCOPE_TOKEN_MAP = {
    "既存店": "existing_store",
    "全店": "all_store",
    "総供給高": "total_supply",
    "該当なし": "n_a",
}

# 発表主体対応表（要件 IF-02）。セルは注記を含むため cell_head() で
# 先頭トークン（最初の `（` / `／` より前）を取ってから照合する。
AUTHORITY_TOKEN_MAP = {
    "経済産業省": "meti",
    "総務省": "mic",
    "日本ショッピングセンター協会": "sc-association",
    "日本百貨店協会": "department-store-association",
    "日本チェーンストア協会": "chain-store-association",
    "日本フードサービス協会": "food-service-association",
    "日本生活協同組合連合会": "co-op-union",
    "業界団体": "industry-association",
    "業界団体合同発表": "industry-association",
    "業界紙": "trade-press",
    "民間調査機関": "private-research",
}

ALIAS_SPLIT_RE = re.compile(r"[,、/／]")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_H2_RE = re.compile(r"^##\s+([^#].*)$")
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
_WS_RE = re.compile(r"\s+")
_HEAD_SPLIT_RE = re.compile(r"[（(／/]")
_DASH_LIKE = ("", "—", "-", "－", "ー", "―", "–")


# --- `parse-wbs.py` からそのまま移植（実装設計 §2.4）------------------------


def split_table_row(line: str) -> list[str]:
    """MD テーブル行を `|` で分解し、各セルの前後空白を除く。"""
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [cell.strip() for cell in s.split("|")]


def is_separator_row(cells: list[str]) -> bool:
    """`|---|:---|---:|` のような区切り行かどうか。"""
    return bool(cells) and all(_SEPARATOR_CELL_RE.match(cell) for cell in cells)


# --- 段階4: セル値の解釈（実装設計 §3.1）------------------------------------


def clean_cell(cell: str) -> str:
    """強調記法（`**`）とバッククォートを剥がす（実装設計 §3.1 段階4）。"""
    s = cell.strip()
    s = _BOLD_RE.sub(r"\1", s)
    s = s.replace("`", "")
    return s.strip()


def cell_head(cell: str) -> str:
    """括弧注記・併記を落として先頭ラベルのみ取る（実装設計 §3.1 段階4）。

    例: '該当なし（`co-op` は総供給高で上書き。§4.5 参照）' → '該当なし'
        '経済産業省（商業動態統計）／個社開示'                → '経済産業省'
        '業界紙（DCS）集計（協会名は記事本文未確認…）'        → '業界紙'
    """
    s = clean_cell(cell)
    s = _HEAD_SPLIT_RE.split(s, maxsplit=1)[0]
    return s.strip()


def split_aliases(cell: str) -> list[str]:
    """別名セルを区切り文字（, 、 / ／）で分割し、空・ダッシュ相当を除く。"""
    s = clean_cell(cell)
    out = [alias.strip() for alias in ALIAS_SPLIT_RE.split(s) if alias.strip()]
    return [alias for alias in out if alias not in _DASH_LIKE]


def normalize_header(cell: str) -> str:
    """ヘッダセルの照合キー（前後空白除去 + 内部空白除去 + バッククォート除去）。

    `KPI ID` と `KPIID` の両方を同じキーに畳むため、許容リスト側も同じ
    関数で正規化してから照合する（実装設計 §3.1 段階3）。
    """
    return _WS_RE.sub("", clean_cell(cell))


def resolve_unit(cell: str, metric_id: str) -> str:
    """単位セルをトークンごとに UNIT_TOKEN_MAP と照合する（実装設計 §3.1）。

    `億円 / 兆円` のような複数トークン併記は、写像後の集合が1要素であれば
    その値に一本化する。0要素または2要素以上なら CatalogError。
    """
    value, error = _resolve_unit(cell, metric_id)
    if error is not None:
        raise CatalogError(error)
    return value


def resolve_scope(cell: str, metric_id: str) -> str:
    """既定スコープセル（日本語ラベル）を scope enum に変換する（要件 IF-02）。"""
    value, error = _resolve_scope(cell, metric_id)
    if error is not None:
        raise CatalogError(error)
    return value


def resolve_authority(cell: str, segment_id: str) -> str:
    """発表主体セルの先頭トークンを source_authority コードに変換する（要件 IF-02）。"""
    value, error = _resolve_authority(cell, segment_id)
    if error is not None:
        raise CatalogError(error)
    return value


def _resolve_unit(cell: str, metric_id: str) -> tuple[str, str | None]:
    tokens = [t.strip() for t in re.split(r"[/／,、]", clean_cell(cell)) if t.strip()]
    units = {UNIT_TOKEN_MAP[t] for t in tokens if t in UNIT_TOKEN_MAP}
    if not units:
        return "", f"[V6] 単位を解決できません: metric_id={metric_id} cell={cell!r}"
    if len(units) > 1:
        return (
            "",
            f"[V6] 単位が複数の enum に解決されます: metric_id={metric_id} {sorted(units)}",
        )
    return units.pop(), None


def _resolve_scope(cell: str, metric_id: str) -> tuple[str, str | None]:
    head = cell_head(cell)
    if head not in SCOPE_TOKEN_MAP:
        return "", f"[V7] 既定スコープを解決できません: metric_id={metric_id} cell={cell!r}"
    return SCOPE_TOKEN_MAP[head], None


def _resolve_authority(cell: str, segment_id: str) -> tuple[str, str | None]:
    head = cell_head(cell)
    if head not in AUTHORITY_TOKEN_MAP:
        return (
            "",
            f"[V13] 未知の発表主体: {head!r} (segment_id={segment_id})。"
            " IF-02 発表主体対応表への追加が必要です",
        )
    return AUTHORITY_TOKEN_MAP[head], None


# --- 段階1〜3: 見出し検出・定義表の特定・列名解決 ---------------------------


class _Table:
    """定義表 1 つ分。行番号を保持して違反メッセージに載せる。"""

    def __init__(self, header_lineno: int, header: list[str], rows: list[tuple[int, list[str]]]):
        self.header_lineno = header_lineno
        self.header = header
        self.rows = rows


def _find_h2(lines: list[str], keywords: tuple[str, ...], label: str) -> int:
    """条件に一致する H2 の行番号（0 始まり）を返す。0 個または 2 個以上ならエラー停止。"""
    hits: list[int] = []
    for i, line in enumerate(lines):
        m = _H2_RE.match(line.strip())
        if not m:
            continue
        text = _WS_RE.sub("", m.group(1))  # "KPI 定義" → "KPI定義"
        if any(kw in text for kw in keywords):
            hits.append(i)
    if len(hits) != 1:
        raise CatalogError(
            f"{label}の見出し検出に失敗しました: keywords={keywords} 一致数={len(hits)}"
            f" 一致行={[lines[i].strip() for i in hits]}"
        )
    return hits[0]


def _find_first_table(lines: list[str], h2_lineno: int, label: str) -> _Table:
    """H2 の次行から次の H2 の直前までを走査し、最初の MD テーブルを返す。

    H3 小見出しを挟んでもよい。「最初のテーブル」規則は、`## 2. KPI 定義`
    配下の §2.2 比較表・§2.3 対応マトリクスを定義表と誤読することを
    構造的に防いでいる（実装設計 §3.1 段階2）。
    """
    end = len(lines)
    for i in range(h2_lineno + 1, len(lines)):
        if _H2_RE.match(lines[i].strip()):
            end = i
            break

    i = h2_lineno + 1
    while i < end:
        stripped = lines[i].strip()
        if stripped.startswith("|"):
            header_cells = split_table_row(lines[i])
            if i + 1 < end and is_separator_row(split_table_row(lines[i + 1])):
                rows: list[tuple[int, list[str]]] = []
                j = i + 2
                while j < end and lines[j].strip().startswith("|"):
                    cells = split_table_row(lines[j])
                    if not is_separator_row(cells) and any(c.strip() for c in cells):
                        rows.append((j + 1, cells))  # 1 始まりの行番号で保持する
                    j += 1
                return _Table(i + 1, header_cells, rows)
        i += 1
    raise CatalogError(f"{label}の定義表が見つかりません（見出し 行 {h2_lineno + 1} の配下）")


def _resolve_columns(
    table: _Table,
    required: dict[str, tuple[str, ...]],
    optional: dict[str, tuple[str, ...]],
    label: str,
) -> dict[str, int]:
    """許容リストでヘッダ列を canonical 名 → index に解決する（実装設計 §3.1 段階3）。

    必須列が 1 つでも解決できなければ CatalogError で停止する（FR-24）。
    欠損列を既定値で埋めて続行しない。許容リスト外の列は無視する。
    """
    normalized = {normalize_header(cell): idx for idx, cell in enumerate(table.header)}
    index: dict[str, int] = {}
    missing: list[str] = []
    for canonical, allowed in required.items():
        for name in allowed:
            key = normalize_header(name)
            if key in normalized:
                index[canonical] = normalized[key]
                break
        else:
            missing.append(f"{allowed[0]}（許容名: {' / '.join(allowed)}）")
    for canonical, allowed in optional.items():
        for name in allowed:
            key = normalize_header(name)
            if key in normalized:
                index[canonical] = normalized[key]
                break
    if missing:
        raise CatalogError(
            f"{label}の必須列が解決できません（{len(missing)} 件、ヘッダ 行 "
            f"{table.header_lineno}）: " + " / ".join(missing)
        )
    return index


# --- 行のパース -------------------------------------------------------------


def _cell(row: list[str], index: dict[str, int], key: str) -> str:
    idx = index.get(key)
    if idx is None or idx >= len(row):
        return ""
    return row[idx]


def _parse_int(raw: str) -> tuple[int, bool]:
    text = clean_cell(raw)
    try:
        return int(text), True
    except ValueError:
        return 0, False


def _build_aliases(alias_cell: str, name: str) -> tuple[str, ...]:
    """別名に名称を含めて重複除去し、長さ降順（同長は文字列昇順）で返す。

    長さ降順にするのは最長一致のため。`既存店売上高`（6 文字）→
    `既存店売上`（5 文字）→ `既存店`（3 文字）の順に照合しないと、
    `既存店売上高` が `既存店` にマッチする（実装設計 §3.2）。
    """
    aliases = split_aliases(alias_cell)
    if name and name not in aliases:
        aliases.append(name)
    unique = list(dict.fromkeys(aliases))
    unique.sort(key=lambda a: (-len(a), a))
    return tuple(unique)


def _parse_segments(table: _Table, violations: list[str]) -> list[Segment]:
    index = _resolve_columns(table, SEGMENT_COLUMNS, SEGMENT_OPTIONAL_COLUMNS, "業態定義表")
    segments: list[Segment] = []
    seen: dict[str, int] = {}
    for lineno, row in table.rows:
        if len(row) < len(table.header):
            violations.append(
                f"[列数] 業態定義表 行 {lineno}: 列数が {len(row)} でヘッダ "
                f"{len(table.header)} に足りません"
            )
            continue
        segment_id = clean_cell(_cell(row, index, "segment_id"))
        name = clean_cell(_cell(row, index, "name"))
        _check_id(segment_id, "segment_id", lineno, seen, violations)

        alias_cell = _cell(row, index, "aliases")
        if not split_aliases(alias_cell):
            violations.append(f"[V11] 別名が空です: segment_id={segment_id}（行 {lineno}）")

        entity_type = clean_cell(_cell(row, index, "entity_type"))

        authority_cell = _cell(row, index, "source_authority")
        authority, error = _resolve_authority(authority_cell, segment_id)
        if error is not None:
            violations.append(f"{error}（行 {lineno}）")

        display_order, ok = _parse_int(_cell(row, index, "display_order"))
        if not ok or display_order < 0:
            violations.append(
                f"[V8] 表示順が非負整数ではありません: "
                f"{clean_cell(_cell(row, index, 'display_order'))!r}（行 {lineno}）"
            )

        parent_raw = clean_cell(_cell(row, index, "parent_segment_id"))
        parent = parent_raw if parent_raw and parent_raw not in _DASH_LIKE else None

        segments.append(
            Segment(
                segment_id=segment_id,
                name=name,
                aliases=_build_aliases(alias_cell, name),
                parent_segment_id=parent,
                entity_type=entity_type,
                source_authority=authority,
                source_authority_label=clean_cell(authority_cell),
                display_order=display_order,
            )
        )
    return segments


def _parse_metrics(table: _Table, violations: list[str]) -> list[Metric]:
    index = _resolve_columns(table, METRIC_COLUMNS, {}, "指標定義表")
    metrics: list[Metric] = []
    seen: dict[str, int] = {}
    for lineno, row in table.rows:
        if len(row) < len(table.header):
            violations.append(
                f"[列数] 指標定義表 行 {lineno}: 列数が {len(row)} でヘッダ "
                f"{len(table.header)} に足りません"
            )
            continue
        metric_id = clean_cell(_cell(row, index, "metric_id"))
        name = clean_cell(_cell(row, index, "name"))
        _check_id(metric_id, "metric_id", lineno, seen, violations)

        alias_cell = _cell(row, index, "aliases")
        if not split_aliases(alias_cell):
            violations.append(f"[V11] 別名が空です: metric_id={metric_id}（行 {lineno}）")

        unit, unit_error = _resolve_unit(_cell(row, index, "unit_raw"), metric_id)
        if unit_error is not None:
            violations.append(f"{unit_error}（行 {lineno}）")

        scope, scope_error = _resolve_scope(_cell(row, index, "default_scope_raw"), metric_id)
        if scope_error is not None:
            violations.append(f"{scope_error}（行 {lineno}）")

        precision, ok = _parse_int(_cell(row, index, "precision"))
        if not ok or precision < 0:
            violations.append(
                f"[V8] 小数桁が非負整数ではありません: "
                f"{clean_cell(_cell(row, index, 'precision'))!r}（行 {lineno}）"
            )

        metrics.append(
            Metric(
                metric_id=metric_id,
                name=name,
                unit=unit,
                value_type=clean_cell(_cell(row, index, "value_type")),
                direction_hint=clean_cell(_cell(row, index, "direction_hint")),
                aliases=_build_aliases(alias_cell, name),
                default_scope=scope,
                precision=precision,
            )
        )
    return metrics


def _check_id(
    identifier: str,
    field: str,
    lineno: int,
    seen: dict[str, int],
    violations: list[str],
) -> None:
    """V1（kebab-case）/ V2（一意）を行番号つきで検査する。"""
    if not ID_RE.match(identifier):
        violations.append(f"[V1] 不正な ID 形式: {identifier!r}（{field}、行 {lineno}）")
    if identifier in seen:
        violations.append(
            f"[V2] {field} が重複しています: {identifier!r}"
            f"（行 {seen[identifier]}, {lineno}）"
        )
    else:
        seen[identifier] = lineno


# --- 入口 -------------------------------------------------------------------


def load(path: Path) -> Catalog:
    """カタログ MD を読み込み、4段階処理を経て Catalog を返す。

    末尾で `Catalog.validate()`（V1〜V13）を実行し、1件でも違反があれば
    CatalogError を送出して停止する（部分的な読み込みで続行しない）。

    段階 1〜3 の失敗（見出しの多重一致・定義表の不在・必須列の欠落）は
    以降のセル解釈を無意味にするため、その場で送出する。段階 4 の
    行単位の違反は全件を集めてから一度に送出する（1 行直すたびに
    再実行させないため）。
    """
    path = Path(path)
    raw = path.read_bytes()
    lines = raw.decode("utf-8").splitlines()

    segment_h2 = _find_h2(lines, SEGMENT_HEADING_KEYWORDS, "業態定義")
    metric_h2 = _find_h2(lines, METRIC_HEADING_KEYWORDS, "指標定義")
    segment_table = _find_first_table(lines, segment_h2, "業態定義")
    metric_table = _find_first_table(lines, metric_h2, "指標定義")

    violations: list[str] = []
    segments = _parse_segments(segment_table, violations)
    metrics = _parse_metrics(metric_table, violations)
    if violations:
        raise CatalogError(
            f"カタログのバリデーションに失敗しました（{len(violations)} 件）:\n  - "
            + "\n  - ".join(violations)
        )

    catalog = Catalog(
        segments=tuple(sorted(segments, key=lambda s: s.display_order)),
        metrics=tuple(metrics),
        source_path=str(path),
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )
    catalog.validate()
    return catalog
