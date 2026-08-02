"""catalog.py の正常系・異常系テスト。実装設計 §7.2 T-6 / M2 完了条件。

対応するテストケース:
    test_undefined_segment_id_in_llm_output_is_rejected
        LLM 出力に未定義 segment_id が含まれると拒否される（FR-24）。
    test_missing_required_column_raises
        fixtures/catalog/missing_column.md（既定スコープ列を削除）で
        CatalogError が上がり、メッセージに「既定スコープ」を含む。
    test_duplicate_heading_raises
        fixtures/catalog/duplicate_heading.md（見出し多重一致）で
        CatalogError が上がる。
    test_integrity_check_blocks_write
        未定義 ID を含む observation があると書き出さずに例外を上げる
        （store.IntegrityError）。
    test_unknown_authority_in_catalog_raises
        fixtures/catalog/unknown_authority.md（IF-02 発表主体対応表に
        無い値）で CatalogError（V13）。
    test_catalog_has_no_parent_links_today
        現行カタログでは13行すべての parent_segment_id が None であることの
        回帰テスト（実装設計 §7.2 T-9。将来リンクが復活したら気づけるように）。

V1〜V13（実装設計 §3.3）は本ファイルで網羅的に検査すること。

V1〜V13 の異常系は、コミット済みフィクスチャ 5 種では 1 種につき 1 違反しか
表現できないため、`_build_catalog()` が最小のカタログ MD を組み立てて
tmp に書き出す方式を併用する。フィクスチャ 5 種は実カタログ由来の
「本物の形」に対する回帰、`_build_catalog()` は V1〜V13 の網羅に使う。
"""

import tempfile
import unittest
from pathlib import Path

from retail_stats import catalog, config
from retail_stats.models import CatalogError

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "catalog"

SEGMENT_HEADER = ("segment_id", "名称", "別名", "上位業態", "種別", "表示順", "発表主体")
METRIC_HEADER = (
    "metric_id",
    "名称",
    "別名",
    "単位",
    "値種別",
    "方向",
    "既定スコープ",
    "小数桁",
)

BASE_SEGMENT = {
    "segment_id": "`department-store`",
    "名称": "百貨店",
    "別名": "百貨店, 日本百貨店協会",
    "上位業態": "",
    "種別": "association",
    "表示順": "20",
    "発表主体": "日本百貨店協会",
}

BASE_METRIC = {
    "metric_id": "`existing-store-sales-yoy`",
    "名称": "既存店売上高前年比",
    "別名": "既存店売上, 既存店",
    "単位": "%",
    "値種別": "ratio",
    "方向": "higher_is_better",
    "既定スコープ": "既存店",
    "小数桁": "1",
}


def _row(header, values):
    return "| " + " | ".join(values.get(col, "") for col in header) + " |"


def _table(header, rows, renames=None):
    """header は行 dict のキー、renames はヘッダ行にだけ効く表示名の差し替え。"""
    display = [(renames or {}).get(col, col) for col in header]
    return [
        "| " + " | ".join(display) + " |",
        "|" + "|".join("---" for _ in header) + "|",
        *(_row(header, row) for row in rows),
    ]


def _build_catalog(segments=None, metrics=None, header_overrides=None, renames=None):
    """最小のカタログ MD を組み立てて返す（V1〜V13 の網羅用）。

    header_overrides で列の増減、renames で列名の言い換え（許容名テスト）を表現する。
    """
    seg_header, met_header = SEGMENT_HEADER, METRIC_HEADER
    if header_overrides:
        seg_header = header_overrides.get("segments", seg_header)
        met_header = header_overrides.get("metrics", met_header)
    renames = renames or {}
    lines = [
        "# テスト用カタログ",
        "",
        "## 1. 業態区分マスタ",
        "",
        "### 1.1 業態一覧",
        "",
        *_table(
            seg_header,
            segments if segments is not None else [BASE_SEGMENT],
            renames.get("segments"),
        ),
        "",
        "## 2. KPI 定義",
        "",
        "### 2.1 KPI 一覧",
        "",
        *_table(
            met_header,
            metrics if metrics is not None else [BASE_METRIC],
            renames.get("metrics"),
        ),
        "",
    ]
    return "\n".join(lines) + "\n"


def _seg(**overrides):
    return {**BASE_SEGMENT, **overrides}


def _met(**overrides):
    return {**BASE_METRIC, **overrides}


class _CatalogTestCase(unittest.TestCase):
    def load_text(self, text):
        """カタログ MD 文字列を一時ファイルに書いて load する。"""
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        path = Path(tmpdir.name) / "catalog.md"
        path.write_text(text, encoding="utf-8")
        return catalog.load(path)

    def assert_violation(self, text, marker):
        """load が CatalogError を上げ、メッセージに marker を含むことを検査する。"""
        with self.assertRaises(CatalogError) as ctx:
            self.load_text(text)
        self.assertIn(marker, str(ctx.exception))
        return str(ctx.exception)


class TestCatalogLoad(_CatalogTestCase):
    """フィクスチャ 5 種に対する正常系・異常系（M2 完了条件）。"""

    def test_valid_fixture_loads(self):
        result = catalog.load(FIXTURES / "valid.md")
        self.assertEqual(len(result.segments), 13)
        self.assertEqual(len(result.metrics), 14)

    def test_missing_required_column_raises(self):
        with self.assertRaises(CatalogError) as ctx:
            catalog.load(FIXTURES / "missing_column.md")
        # 欠けた列が日本語ラベルで名指しされること（FR-24。既定値で埋めて続行しない）
        self.assertIn("既定スコープ", str(ctx.exception))

    def test_duplicate_heading_raises(self):
        with self.assertRaises(CatalogError) as ctx:
            catalog.load(FIXTURES / "duplicate_heading.md")
        self.assertIn("一致数=2", str(ctx.exception))

    def test_unknown_authority_in_catalog_raises(self):
        with self.assertRaises(CatalogError) as ctx:
            catalog.load(FIXTURES / "unknown_authority.md")
        self.assertIn("V13", str(ctx.exception))
        self.assertIn("発表主体", str(ctx.exception))

    def test_undefined_parent_in_catalog_raises(self):
        with self.assertRaises(CatalogError) as ctx:
            catalog.load(FIXTURES / "undefined_id.md")
        self.assertIn("V9", str(ctx.exception))

    def test_catalog_has_no_parent_links_today(self):
        """T-9: 現行カタログでは 13 行すべて parent_segment_id が None。

        `parent_segment_id` は表示上の系統情報としてのみ保持し、値の
        ロールアップ集約には使わない（実装設計 §3.3）。将来リンクが
        復活したときに気づけるようにするための回帰テスト。
        """
        result = catalog.load(config.catalog_path())
        self.assertEqual(len(result.segments), 13)
        self.assertEqual(len(result.metrics), 14)
        self.assertEqual([s.parent_segment_id for s in result.segments], [None] * 13)


class TestCatalogStructure(_CatalogTestCase):
    """段階 1〜3（見出し検出 / 定義表の特定 / 列名解決）。実装設計 §3.1。"""

    def test_heading_detection_is_number_agnostic(self):
        text = _build_catalog()
        text = text.replace("## 1. 業態区分マスタ", "## 業態区分")
        text = text.replace("## 2. KPI 定義", "## 7-B. 指標定義について")
        result = self.load_text(text)
        self.assertEqual([s.segment_id for s in result.segments], ["department-store"])

    def test_kpi_heading_accepts_space_variants(self):
        for heading in ("## 2. KPI 定義", "## 2. KPI定義", "## KPI  定義"):
            with self.subTest(heading=heading):
                text = _build_catalog().replace("## 2. KPI 定義", heading)
                self.assertEqual(len(self.load_text(text).metrics), 1)

    def test_missing_heading_raises(self):
        text = _build_catalog().replace("## 1. 業態区分マスタ", "## 1. 業種マスタ")
        self.assert_violation(text, "一致数=0")

    def test_first_table_under_heading_wins(self):
        """§2.2 比較表・§2.3 マトリクスを定義表と誤読しないこと。"""
        text = _build_catalog()
        text = text.replace(
            "\n## 2. KPI 定義",
            "\n| 観点 | 既存店 | 全店 |\n|---|---|---|\n| 対象店舗 | 13ヶ月以上 | 全店舗 |\n"
            "\n## 2. KPI 定義",
        )
        # 業態表の後・次の H2 の前に別テーブルを足しても、最初のテーブルが定義表
        result = self.load_text(text)
        self.assertEqual([s.segment_id for s in result.segments], ["department-store"])

    def test_missing_table_raises(self):
        text = _build_catalog()
        text = text.replace("### 2.1 KPI 一覧", "### 2.1 KPI 一覧\n\n（表は準備中）")
        lines = [ln for ln in text.splitlines() if not ln.startswith("| ") and not ln.startswith("|-")]
        self.assert_violation("\n".join(lines) + "\n", "定義表が見つかりません")

    def test_column_aliases_are_accepted(self):
        """許容列名（`業態ID` / `表記ゆれ` / `KPI ID` / `既存店/全店` 等）を受理する。"""
        text = _build_catalog(
            renames={
                "segments": {"segment_id": "業態ID", "名称": "正式名称", "別名": "表記ゆれ"},
                "metrics": {
                    "metric_id": "KPI ID",
                    "名称": "正式名称",
                    "別名": "表記ゆれ",
                    "既定スコープ": "既存店/全店",
                },
            }
        )
        result = self.load_text(text)
        self.assertEqual(result.segments[0].segment_id, "department-store")
        self.assertEqual(result.metrics[0].metric_id, "existing-store-sales-yoy")
        self.assertEqual(result.metrics[0].default_scope, "existing_store")

    def test_kpiid_without_space_is_accepted(self):
        text = _build_catalog(renames={"metrics": {"metric_id": "KPIID"}})
        self.assertEqual(self.load_text(text).metrics[0].metric_id, "existing-store-sales-yoy")

    def test_unknown_columns_are_ignored(self):
        header = (*SEGMENT_HEADER, "公表サイクル", "定義・カバー範囲")
        text = _build_catalog(
            segments=[{**BASE_SEGMENT, "公表サイクル": "毎月下旬", "定義・カバー範囲": "会員社ベース"}],
            header_overrides={"segments": header},
        )
        self.assertEqual(len(self.load_text(text).segments), 1)

    def test_missing_required_segment_column_raises(self):
        """発表主体は必須列。natural key の第 5 要素の供給源（要件 IF-02 / §9.3 D1）。"""
        header = tuple(c for c in SEGMENT_HEADER if c != "発表主体")
        text = _build_catalog(header_overrides={"segments": header})
        self.assert_violation(text, "発表主体")


class TestCellInterpretation(unittest.TestCase):
    """段階 4（セル値の解釈）。実装設計 §3.1。"""

    def test_clean_cell_strips_emphasis_and_backticks(self):
        self.assertEqual(catalog.clean_cell(" **既存店** "), "既存店")
        self.assertEqual(catalog.clean_cell("`shopping-center`"), "shopping-center")

    def test_cell_head_drops_notes_and_alternatives(self):
        self.assertEqual(
            catalog.cell_head("該当なし（`co-op` は総供給高で上書き。§4.5 参照）"), "該当なし"
        )
        self.assertEqual(catalog.cell_head("経済産業省（商業動態統計）／個社開示"), "経済産業省")
        self.assertEqual(
            catalog.cell_head("業界紙（DCS）集計（協会名は記事本文未確認。※業界一般知識…）"),
            "業界紙",
        )

    def test_split_aliases_handles_separators_and_dashes(self):
        self.assertEqual(
            catalog.split_aliases("総売上高, 総供給高, 売上高"), ["総売上高", "総供給高", "売上高"]
        )
        self.assertEqual(catalog.split_aliases("商業動態統計、経産省調べ"), ["商業動態統計", "経産省調べ"])
        self.assertEqual(catalog.split_aliases("—"), [])

    def test_resolve_unit_collapses_multiple_tokens(self):
        """`億円 / 兆円` は 2 トークンとも jpy_oku に写るため集合は 1 要素。"""
        self.assertEqual(catalog.resolve_unit("億円 / 兆円", "sales-amount-absolute"), "jpy_oku")
        self.assertEqual(catalog.resolve_unit("％", "x"), "percent_yoy")
        self.assertEqual(catalog.resolve_unit("%", "x"), "percent_yoy")

    def test_resolve_unit_rejects_empty_and_ambiguous(self):
        with self.assertRaises(CatalogError):
            catalog.resolve_unit("—", "x")
        with self.assertRaises(CatalogError):
            catalog.resolve_unit("% / 億円", "x")

    def test_split_table_row_and_separator(self):
        self.assertEqual(catalog.split_table_row("| a | b |"), ["a", "b"])
        self.assertTrue(catalog.is_separator_row(["---", ":---", "---:"]))
        self.assertFalse(catalog.is_separator_row(["a", "---"]))


class TestCatalogValidation(_CatalogTestCase):
    """V1〜V13（実装設計 §3.3）の網羅。"""

    def test_v1_id_must_be_kebab_case(self):
        self.assert_violation(_build_catalog(segments=[_seg(segment_id="Shopping Center")]), "[V1]")
        self.assert_violation(_build_catalog(metrics=[_met(metric_id="Existing_Store")]), "[V1]")

    def test_v2_id_must_be_unique(self):
        segments = [_seg(表示順="20"), _seg(名称="百貨店（再掲）", 表示順="21")]
        self.assert_violation(_build_catalog(segments=segments), "[V2]")

    def test_v3_entity_type_enum(self):
        self.assert_violation(_build_catalog(segments=[_seg(種別="アソシエーション")]), "[V3]")

    def test_v4_value_type_enum(self):
        self.assert_violation(_build_catalog(metrics=[_met(値種別="比率")]), "[V4]")

    def test_v5_direction_hint_enum(self):
        self.assert_violation(_build_catalog(metrics=[_met(方向="up")]), "[V5]")

    def test_v6_unit_must_resolve(self):
        self.assert_violation(_build_catalog(metrics=[_met(単位="—")]), "[V6]")
        self.assert_violation(_build_catalog(metrics=[_met(単位="% / 億円")]), "[V6]")

    def test_v7_default_scope_must_resolve(self):
        self.assert_violation(_build_catalog(metrics=[_met(既定スコープ="店舗別")]), "[V7]")

    def test_v7_scope_note_in_cell_is_tolerated(self):
        """`該当なし（co-op は総供給高で上書き…）` は cell_head で n_a に解決する。"""
        text = _build_catalog(
            metrics=[_met(既定スコープ="該当なし（`co-op` は総供給高で上書き。§4.5 参照）")]
        )
        self.assertEqual(self.load_text(text).metrics[0].default_scope, "n_a")

    def test_v8_precision_and_display_order_must_be_non_negative_int(self):
        self.assert_violation(_build_catalog(metrics=[_met(小数桁="N/A")]), "[V8]")
        self.assert_violation(_build_catalog(segments=[_seg(表示順="-1")]), "[V8]")

    def test_v9_parent_must_exist(self):
        self.assert_violation(_build_catalog(segments=[_seg(上位業態="`no-such-segment`")]), "[V9]")

    def test_v10_parent_must_not_cycle(self):
        segments = [
            _seg(segment_id="`a-seg`", 名称="A", 別名="A業態", 上位業態="`b-seg`", 表示順="10"),
            _seg(segment_id="`b-seg`", 名称="B", 別名="B業態", 上位業態="`a-seg`", 表示順="20"),
        ]
        self.assert_violation(_build_catalog(segments=segments), "[V10]")

    def test_v11_aliases_must_not_be_empty(self):
        self.assert_violation(_build_catalog(segments=[_seg(別名="")]), "[V11]")
        self.assert_violation(_build_catalog(metrics=[_met(別名="—")]), "[V11]")

    def test_v12_aliases_must_not_collide(self):
        metrics = [
            _met(metric_id="`metric-a`", 名称="指標A", 別名="売上高"),
            _met(metric_id="`metric-b`", 名称="指標B", 別名="売上高"),
        ]
        message = self.assert_violation(_build_catalog(metrics=metrics), "[V12]")
        self.assertIn("売上高", message)

    def test_v12_allows_same_alias_across_segment_and_metric_indexes(self):
        """別名の一意性は「業態内 / 指標内」で見る。索引をまたぐ重複は許す。"""
        text = _build_catalog(
            segments=[_seg(別名="ECプラットフォーム市場規模")],
            metrics=[_met(別名="ECプラットフォーム市場規模")],
        )
        self.assertEqual(len(self.load_text(text).segments), 1)

    def test_v13_authority_must_map_to_code(self):
        self.assert_violation(_build_catalog(segments=[_seg(発表主体="日本DIY協会")]), "[V13]")

    def test_v13_authority_head_token_is_used(self):
        text = _build_catalog(
            segments=[_seg(発表主体="経済産業省（商業動態統計）／個社開示")]
        )
        segment = self.load_text(text).segments[0]
        self.assertEqual(segment.source_authority, "meti")
        # 表示用ラベルは原文のまま保持する（注記を落とさない）
        self.assertEqual(segment.source_authority_label, "経済産業省（商業動態統計）／個社開示")

    def test_all_violations_are_reported_at_once(self):
        """1 つ直すたびに再実行させないため、行単位の違反は全件を列挙する。"""
        message = self.assert_violation(
            _build_catalog(metrics=[_met(単位="—", 既定スコープ="店舗別", 小数桁="N/A")]), "[V6]"
        )
        self.assertIn("[V7]", message)
        self.assertIn("[V8]", message)
        self.assertIn("3 件", message)


class TestCatalogObject(_CatalogTestCase):
    """Catalog の内部表現（実装設計 §3.2）。"""

    def setUp(self):
        self.catalog = catalog.load(FIXTURES / "valid.md")

    def test_segments_are_sorted_by_display_order(self):
        orders = [s.display_order for s in self.catalog.segments]
        self.assertEqual(orders, sorted(orders))
        self.assertEqual(self.catalog.segments[0].segment_id, "shopping-center")

    def test_metrics_keep_catalog_order(self):
        self.assertEqual(self.catalog.metrics[0].metric_id, "existing-store-sales-yoy")
        self.assertEqual(self.catalog.metrics[-1].metric_id, "ec-market-size-yoy")

    def test_aliases_include_name(self):
        metric = self.catalog.metric("existing-store-sales-yoy")
        self.assertIn("既存店売上高前年比", metric.aliases)
        self.assertIn("既存店", metric.aliases)

    def test_alias_index_is_longest_first(self):
        index = self.catalog.metric_alias_index()
        lengths = [len(alias) for alias, _ in index]
        self.assertEqual(lengths, sorted(lengths, reverse=True))
        # 最長一致: `既存店売上高` が `既存店` より先に照合される
        aliases = [alias for alias, _ in index]
        self.assertLess(aliases.index("既存店売上高"), aliases.index("既存店"))

    def test_alias_index_is_deterministic(self):
        again = catalog.load(FIXTURES / "valid.md")
        self.assertEqual(self.catalog.metric_alias_index(), again.metric_alias_index())
        self.assertEqual(self.catalog.segment_alias_index(), again.segment_alias_index())

    def test_lookup_of_undefined_id_raises(self):
        """カタログに無い ID をコードが生成する経路を持たない（FR-24）。"""
        with self.assertRaises(CatalogError):
            self.catalog.segment("takashimaya")
        with self.assertRaises(CatalogError):
            self.catalog.metric("gross-margin-yoy")

    def test_source_sha256_detects_revision(self):
        """カタログ改訂の検知に使う（実装設計 §3.3）。"""
        self.assertEqual(len(self.catalog.source_sha256), 64)
        changed = self.load_text(_build_catalog())
        self.assertNotEqual(self.catalog.source_sha256, changed.source_sha256)

    def test_co_op_default_scope_stays_n_a(self):
        """`co-op` × `sales-amount-absolute` の total_supply 上書きはパーサ側の責務。

        ローダは `default_scope = n_a` をそのまま保持する（実装設計 §3.3）。
        """
        self.assertEqual(self.catalog.metric("sales-amount-absolute").default_scope, "n_a")


class TestCatalogPathResolution(unittest.TestCase):
    """入力所在ポリシー（origin.md「入力データの所在」/ config.py）。"""

    def test_catalog_path_falls_back_to_repo_snapshot(self):
        resolved = config.catalog_path()
        self.assertTrue(resolved.is_file(), f"カタログが見つかりません: {resolved}")

    def test_resolved_inputs_reports_which_catalog_was_read(self):
        info = config.resolved_inputs()
        self.assertIn(info["catalog_source"], ("canonical", "repo-snapshot"))
        self.assertEqual(info["catalog_path"], str(config.catalog_path()))

    def test_org_slug_is_not_a_path(self):
        """`--org` は組織スラグのまま（実装設計 §2.5）。パスを受け取らない。"""
        root = config.find_repo_root()
        self.assertEqual(
            config.data_dir("other-org", root),
            config.workspace_root(root) / ".companies" / "other-org" / config.DATA_RELPATH,
        )


class TestCatalogIntegrity(unittest.TestCase):
    def test_undefined_segment_id_in_llm_output_is_rejected(self):
        raise unittest.SkipTest("M5 実装後に llm.validate_llm_output() で検証する（FR-24）")

    def test_integrity_check_blocks_write(self):
        raise unittest.SkipTest("M4 実装後に store.validate_integrity() で検証する")


if __name__ == "__main__":
    unittest.main()
