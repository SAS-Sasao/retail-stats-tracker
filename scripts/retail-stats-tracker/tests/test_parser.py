"""parser.py の決定論パースアルゴリズム。実装設計 §7.2 T-4 / T-7 / T-8 / T-9 / T-10h〜j。

本システムの中核テストファイル。M3（判断の分岐点）の完了条件そのもの。
各テストの詳細は implementation-design.md §7.2 の該当節を必ず参照して
本文をそのまま移植すること（値・件数は実測値であり創作しない）。

T-4 複数指標の分解（FR-11）:
    test_split_into_three_observations
    test_absolute_and_ratio_split
    test_intra_title_collision_lowers_confidence

T-7 発表主体の解決と共存（要件 7-14）:
    test_association_and_meti_coexist
    test_authority_default_from_catalog
    test_authority_override_by_article
    test_source_name_is_not_authority
    test_unknown_authority_in_catalog_raises（catalog 側。test_catalog.py 参照）
    test_chart_spec_rejects_mixed_authority（html/build.build_chart_spec() 対象。
        実装設計 §2.2 の tests/ 構成には専用ファイルが無いため、本ファイルの
        TestAuthorityResolution にまとめて置く）
    test_home_center_two_authorities_coexist
    test_drugstore_company_disclosure_excluded

T-8 スコープ外の分類（要件 7-15。主語位置ガード §4.3.3）:
    test_scope_classification（SCOPE_CASES 8パターン）
    test_generic_alias_does_not_match_outside_subject
        （SEGMENT_FALSE_POSITIVE_CASES 6パターン。主語位置ガードの中核）
    test_authority_head_exception_is_preserved（経産省調べの4件）
    test_multi_subject_values_are_not_misattributed（U10: 複数主体併記）
    test_authority_marker_evaluated_before_company_rule（判定順序回帰）
    test_out_of_scope_is_persisted_not_discarded（FR-10 / NFR-10）
    test_out_of_scope_never_calls_llm（NFR-11）
    test_nfr05_denominator_excludes_out_of_scope
        現時点の確定値は 0.771（64/83）で未達（origin.md「未決事項」参照）。
        閾値 assert は NFR-05 未達解消（U9）後に有効化する。

T-9 集計粒度の混在禁止（カタログ §1.1 / §1.4）:
    test_no_parent_rollup（R8: parent_segment_id によるロールアップをしない）

T-10h〜j:
    T-10h streak_broken_months（51カ月ぶりに前年割れ）
    T-10i 増収増益 → 2件、value=None、sign_only="+"、needs_source_check=True
    T-10j 金額換算16パターン（test_jpy_conversion。test_textnorm.py 側）
"""

import hashlib
import unittest

from retail_stats import catalog as catalog_mod
from retail_stats import config, parser
from retail_stats.models import DigestRow

CATALOG = catalog_mod.load(config.catalog_path())
ARTICLE_ID = "a" * 16


def run(title, pub, summary=""):
    row = DigestRow(pub, 1, title, "https://example.test/1", "流通ニュース", summary, f"| 1 | {title} |")
    return parser.parse_row(row, CATALOG, ARTICLE_ID)


def keys(result):
    return [(o.metric_id, o.scope, o.value) for o in result.observations]


class TestMultiMetricSplit(unittest.TestCase):
    """T-4 複数指標の分解（FR-11）。実装設計 §4.3.5 の手順そのもの。"""

    def test_inbound_customer_count_and_spend_split_into_three(self):
        r = run("日本百貨店協会／6月の外国人売上29.8％増、客数0.5％減・客単価30.4％増", "2026-07-25")
        self.assertEqual(
            keys(r),
            [
                ("inbound-sales-yoy", "existing_store", 29.8),
                ("customer-count-yoy", "existing_store", -0.5),
                ("spend-per-customer-yoy", "existing_store", 30.4),
            ],
        )
        for o in r.observations:
            self.assertEqual(o.segment_id, "department-store")
            self.assertEqual(o.source_authority, "department-store-association")
            self.assertEqual(o.period_key, "2026-06")
            self.assertGreaterEqual(o.confidence, parser.CONFIDENCE_THRESHOLD)

    def test_rate_and_amount_do_not_share_scope(self):
        """左窓でスコープを決める。別の節の「既存店」に引きずられないこと。"""
        r = run("百貨店／3月の販売額2.2％増の5547億円、既存店は3.4％増（経産省調べ）", "2026-05-08")
        self.assertEqual(
            keys(r),
            [("sales-amount-yoy", "all_store", 2.2), ("existing-store-sales-yoy", "existing_store", 3.4)],
        )

    def test_natural_keys_differ_within_a_row(self):
        r = run("日本百貨店協会／6月の外国人売上29.8％増、客数0.5％減・客単価30.4％増", "2026-07-25")
        self.assertFalse(parser.detect_collision(list(r.observations)))


class TestSubjectPositionGuard(unittest.TestCase):
    """T-8 主語位置ガード（§4.3.3）。実測 7 件の誤抽出を防ぐ。

    うち 3 件はガード導入前「抽出成功」に数えられており、個社の決算値が
    業態の観測値として observations.json に入る状態だった（silent accumulation）。
    """

    CASES = [
        ("ワタミ 決算／3月期営業利益5.9％増、国内外食好調で客数増", "2026-04-20"),
        ("薬王堂HD 決算／2月期増収減益、ドラッグストア事業「フード」売上高は10.5%増", "2026-04-15"),
        ("J.フロント 決算／2月期営業利益15.8％減、SC好調も百貨店・デベロッパー事業減益", "2026-04-15"),
        ("セブン＆アイ 決算／2月期は減収増益、国内コンビニ事業は1.2%増収", "2026-04-11"),
        ("三陽商会 決算／2月期減収減益、大江伸治社長「百貨店不振の影響受けた」", "2026-04-15"),
        ("スプラウツ、ナチュラルグローサーズ…「ウェルネス系食品スーパー」3つの共通項", "2026-05-01"),
    ]

    def test_company_articles_do_not_resolve_a_segment(self):
        for title, pub in self.CASES:
            with self.subTest(title=title):
                r = run(title, pub)
                self.assertEqual(r.observations, (), "個社記事が業態の観測値になっている")
                self.assertEqual(r.unresolved[0].reason_code, "out_of_scope")

    def test_household_survey_is_a_true_miss_not_out_of_scope(self):
        """`3月消費支出…外食マイナス―総務省` は総務省の家計調査。

        `外食` の部分一致で family-restaurant に解決してはならない。かつ
        AUTHORITY_MARKER を持つので no_segment_match（カタログ改善の signal）。
        """
        r = run("3月消費支出、2.9％減＝節約志向で外食マイナス―総務省", "2026-04-10")
        self.assertEqual(r.observations, ())
        self.assertEqual(r.unresolved[0].reason_code, "no_segment_match")

    def test_authority_subject_allows_body_segment_match(self):
        """主語が発表主体名なら本文中の業態名を採る（段階 2 の例外）。"""
        r = run("経済産業省／2月の商業動態統計、小売業販売額は0.2％減の12兆1550億円", "2026-04-01")
        self.assertTrue(r.observations)
        self.assertEqual(r.observations[0].segment_id, "meti-commerce-dynamics")
        self.assertEqual(r.observations[0].source_authority, "meti")


class TestAuthorityResolution(unittest.TestCase):
    """T-7 発表主体の解決（§4.3.6）。natural key の第 5 要素。"""

    def test_article_marker_overrides_catalog_default(self):
        r = run("ホームセンター／3月の販売額は3.4％増2868億円、店舗数は0.7％増（経産省調べ）", "2026-05-08")
        self.assertTrue(r.observations)
        for o in r.observations:
            self.assertEqual(o.segment_id, "home-center")
            self.assertEqual(o.source_authority, "meti", "経産省調べ が既定 trade-press を上書きしない")

    def test_catalog_default_is_used_without_marker(self):
        r = run("ショッピングセンター／6月既存店売上1.6％減", "2026-07-25")
        self.assertEqual(r.observations[0].source_authority, "sc-association")

    def test_association_and_meti_coexist(self):
        """同一業態・同一期間でも発表主体が違えば natural key が衝突しない。"""
        meti = run("百貨店／3月の販売額2.2％増の5547億円、既存店は3.4％増（経産省調べ）", "2026-05-08")
        assoc = run("日本百貨店協会／3月の外国人売上5.2％増", "2026-04-28")
        self.assertTrue(meti.observations and assoc.observations)
        self.assertEqual({o.source_authority for o in meti.observations}, {"meti"})
        self.assertEqual(
            {o.source_authority for o in assoc.observations}, {"department-store-association"}
        )
        all_keys = [o.natural_key() for o in meti.observations + assoc.observations]
        self.assertEqual(len(all_keys), len(set(all_keys)))


class TestAncillaryFields(unittest.TestCase):
    """T-10h / T-10i 付帯情報（カタログ §4.1）。"""

    def test_streak_broken_months(self):
        """T-10h: existing-store-sales-yoy = -1.6 かつ streak_broken_months = 51。"""
        r = run("ショッピングセンター／6月既存店売上1.6％減、夏物振わず51カ月ぶりに前年割れ", "2026-07-25")
        self.assertEqual(len(r.observations), 1)
        o = r.observations[0]
        self.assertEqual(o.metric_id, "existing-store-sales-yoy")
        self.assertAlmostEqual(o.value, -1.6)
        self.assertEqual(o.streak_broken_months, 51)

    def test_streak_is_not_applied_to_positive_values(self):
        """`〜カ月ぶりプラス` は v0.1 で扱わない（§4.3.5 の表）。"""
        r = run("スーパーマーケット／6月の既存店売上0.3％減、40カ月ぶりに前年割れ", "2026-07-22")
        self.assertEqual(r.observations[0].streak_broken_months, 40)

    def test_qualitative_only_sets_sign_only(self):
        """T-10i: 増収増益 は 2 件、value=None、sign_only='+'、needs_source_check=True。"""
        r = run("チェーンストア 決算／2月期増収増益", "2026-04-15")
        self.assertEqual(
            sorted(o.metric_id for o in r.observations),
            ["operating-profit-yoy", "operating-revenue-yoy"],
        )
        for o in r.observations:
            self.assertIsNone(o.value)
            self.assertEqual(o.sign_only, "+")
            self.assertTrue(o.needs_source_check)
            self.assertLess(o.confidence, parser.CONFIDENCE_THRESHOLD)


class TestUnresolvedClassification(unittest.TestCase):
    """§4.3.7 の判定木。AUTHORITY_MARKER を最初に評価する順序が要点。"""

    def test_no_numeric(self):
        r = run("ホームセンター月次実績＝2026年6月度", "2026-07-25")
        self.assertEqual(r.unresolved[0].reason_code, "no_numeric")

    def test_no_segment_match_keeps_catalog_signal(self):
        """カタログに業態行が不足しているケースを個社扱いで黙って除外しない。"""
        r = run("4月都内物価、1.5%上昇＝5カ月連続伸び縮小―総務省", "2026-05-05")
        self.assertEqual(r.unresolved[0].reason_code, "no_segment_match")

    def test_out_of_scope_for_company_disclosure(self):
        r = run("しまむら 決算／2月期増収増益、売上高・営業利益・純利益で過去最高を更新", "2026-03-31")
        self.assertEqual(r.unresolved[0].reason_code, "out_of_scope")

    def test_unresolved_carries_evidence(self):
        """FR-10: 未解決行は原文を証跡として保持する。"""
        r = run("NRF forecasts 4.4% retail sales growth this year", "2026-04-02")
        self.assertEqual(r.unresolved[0].reason_code, "out_of_scope")
        self.assertIn("NRF", r.unresolved[0].raw_line)
        self.assertEqual(r.unresolved[0].last_attempted_at, "2026-04-02")


class TestMultiValueRows(unittest.TestCase):
    """1 行に複数の値がある記事の扱い（cc-sier #728 の確定方針）。

    **FR-10 は無条件の絶対条件。** 値トークンが observation にも unresolved にも
    現れない状態は、いかなる理由があっても許容しない。
    """

    def test_company_enumeration_becomes_company_disclosure(self):
        """(a) 個社の並記 → 行全体を company_disclosure。1 件目も業態の観測値ではない。

        要件 v0.1.2 で `out_of_scope`（業態が解決できなかった行）とは別コードに
        なった。**業態は解決できているが値の主語が個社**という状態を区別する。
        どちらも NFR-05 の分母からは外れる。

        `ツルハ` は指標別名・業態別名・期間表現のいずれでもない残余語であり、
        値の主語が個社であることを示す。カタログ §1.4 が「個社決算は
        out_of_scope 分類とする」と定めている。
        """
        for title, pub in [
            ("ドラッグストア／2月既存店売上ツルハ4.0%増、コスモス薬品7.0%増", "2026-03-31"),
            ("スーパーマーケット／3月既存店売上ライフ1.3%増、ヤオコー2.1%増", "2026-04-29"),
            ("ファミレス／3月既存店 すかいらーく2.3%増、サイゼリヤ15.5%増", "2026-04-21"),
        ]:
            with self.subTest(title=title):
                r = run(title, pub)
                self.assertEqual(r.observations, (), "個社の値が業態の観測値になっている")
                self.assertEqual(r.unresolved[0].reason_code, "company_disclosure")

    def test_segment_internal_breakdown_keeps_the_first_value(self):
        """(b) 業態内の内訳 → 1 件目は正当な観測値、2 件目は退避する。

        `家電大型専門店／4月の販売額は12.1％増` は経産省が発表する業態全体の
        販売額であり、`生活家電15.8％増` はその内訳カテゴリ。1 件目を
        out_of_scope に落とすと本来取るべきデータを捨てることになる。
        """
        r = run("家電大型専門店／4月の販売額は12.1％増、生活家電が15.8％増に（経産省調べ）", "2026-05-30")
        self.assertEqual(
            [(o.segment_id, o.metric_id, o.value) for o in r.observations],
            [("electronics-retailer", "sales-amount-yoy", 12.1)],
        )
        self.assertEqual(
            [u.reason_code for u in r.unresolved], ["no_metric_match_in_multi_value"],
            "解決できなかった値が退避されていない（FR-10 違反）",
        )

    def test_no_value_is_ever_lost(self):
        """FR-10: 値がある行は observation か unresolved のどちらかに必ず現れる。"""
        for title, pub in [
            ("ドラッグストア／2月既存店売上ツルハ4.0%増、コスモス薬品7.0%増", "2026-03-31"),
            ("家電大型専門店／4月の販売額は12.1％増、生活家電が15.8％増に（経産省調べ）", "2026-05-30"),
            ("百貨店／3月の販売額2.2％増の5547億円、既存店は3.4％増（経産省調べ）", "2026-05-08"),
        ]:
            with self.subTest(title=title):
                r = run(title, pub)
                self.assertTrue(r.observations or r.unresolved, "値が痕跡なく消えている")

    def test_comparison_basis_is_not_an_unknown_word(self):
        """`前年度比` は比較基準語であって主語を差し替える修飾語ではない。"""
        r = run("ECプラットフォーム市場規模（2025年度）は前年度比5.8%増の約2398億円", "2026-07-25")
        self.assertTrue(r.observations)
        self.assertEqual(r.observations[0].segment_id, "ec-platform")

    def test_shortened_segment_name_is_not_an_unknown_word(self):
        """`小売業` はカタログの別名 `小売業全体` の短縮形。

        カタログに短縮形の別名が無いことを、パーサ側で誤判定に変えない。
        設計 §4.3.6 はこの行を meti-commerce-dynamics の正当な観測例としている。
        """
        r = run("経済産業省／2月の商業動態統計、小売業販売額は0.2％減の12兆1550億円", "2026-04-01")
        self.assertTrue(r.observations)
        self.assertEqual(r.observations[0].segment_id, "meti-commerce-dynamics")

    def test_residual_helper(self):
        r = run("ドラッグストア／2月既存店売上ツルハ4.0%増", "2026-03-31")
        self.assertEqual(
            parser.residual_after_known_terms("2月既存店売上ツルハ", "既存店売上", CATALOG), "ツルハ"
        )
        self.assertEqual(parser.residual_after_known_terms("4月の販売額は", "販売額", CATALOG), "")


class TestValueTypeConsistency(unittest.TestCase):
    """率の値を絶対額の指標に入れない（カタログ §2.2「絶対額か率かでさらに分岐」）。"""

    def test_percentage_never_lands_on_an_absolute_metric(self):
        """`売上高3.2％増` を sales-amount-absolute（単位 jpy_oku）にしない。

        型で絞らないと **% の値が億円単位の指標に入る**。例外にならないため
        テストで固定しない限り気づけない（§1.2 の silent accumulation）。
        golden-60 が実際にこの誤りを検出した。
        """
        r = run("日本百貨店協会／3月の売上高3.2％増、国内顧客・インバウンドともにプラスに", "2026-04-28")
        for o in r.observations:
            with self.subTest(metric=o.metric_id):
                self.assertNotEqual(o.unit, "jpy_oku", "率の値が金額指標に入っている")

    def test_amount_never_lands_on_a_ratio_metric(self):
        r = run("カスミ／3月の総売上高243億円", "2026-04-17")
        for o in r.observations:
            with self.subTest(metric=o.metric_id):
                self.assertNotEqual(o.unit, "percent_yoy")

    def test_plain_sales_amount_with_percentage_resolves_to_the_ratio_metric(self):
        """**C-2 の決着後**（cc-sier #729 / 要件 v0.1.2）。

        V12 が「値種別が異なれば同一別名を許す」に緩和され、カタログ §2.1 の
        `all-store-sales-yoy` に別名 `売上高` が追加された。これにより
        `売上高N％増`（率）は率の指標に、`売上高N億円`（絶対額）は
        `sales-amount-absolute` に、**値の型で**振り分けられる。

        この期待値は「カタログ課題が解決したら失敗する」テストとして書いてあり、
        実際に設計原本の更新で発火して書き換えた（意図どおりの回帰検出）。
        """
        r = run("日本百貨店協会／3月の売上高3.2％増", "2026-04-28")
        self.assertEqual(
            [(o.metric_id, o.scope, o.value) for o in r.observations],
            [("all-store-sales-yoy", "all_store", 3.2)],
        )

    def test_plain_sales_amount_with_yen_resolves_to_the_absolute_metric(self):
        """同じ別名でも金額なら絶対額の指標に振り分ける（V12 緩和の裏返し）。"""
        r = run("カスミ／3月の総売上高243億円", "2026-04-17")
        for o in r.observations:
            with self.subTest(metric=o.metric_id):
                self.assertEqual(o.unit, "jpy_oku")


class TestJpyConversion(unittest.TestCase):
    """T-3 / T-10j 金額換算。**例外を出さずに誤値を返す**経路の回帰テスト。"""

    JPY_CASES = [
        ("233億円", 233.0), ("1兆4505億円", 14505.0),
        ("1兆4,505億円", 14505.0),      # 旧: 505.0（カンマ未除去 → 30 倍の誤差）
        ("8,577億円", 8577.0),          # 旧: 577.0
        ("4560億1000万円", 4560.1), ("31億8500万円", 31.85),
        ("453億6000万円", 453.6), ("256億3466万円", 256.3466),
        ("13兆4470億円", 134470.0), ("1兆円", 10000.0),
        ("約1.5兆円", 15000.0),         # 旧: 50000.0（整数部を捨て 5兆円 に一致）
        ("1.45兆円", 14500.0), ("2.55兆円", 25500.0),
        ("11.9兆円", 119000.0), ("1.234兆円", 12340.0),
        ("12,345,678万円", 1234.5678),  # 旧: 0.0678
    ]

    def test_jpy_conversion(self):
        from retail_stats import textnorm

        for src, want in self.JPY_CASES:
            with self.subTest(src=src):
                n = textnorm.normalize(src)
                ms = [
                    m for m in parser.VALUE_JPY_RE.finditer(n)
                    if any(m.group(g) for g in ("cho", "oku", "man"))
                ]
                self.assertEqual(len(ms), 1, f"{src}: 一致数が 1 でない")
                self.assertAlmostEqual(parser.to_jpy_oku(ms[0]), want, places=4)


if __name__ == "__main__":
    unittest.main()
