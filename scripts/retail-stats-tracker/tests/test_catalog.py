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
"""

import unittest


class TestCatalogLoad(unittest.TestCase):
    def test_missing_required_column_raises(self):
        raise unittest.SkipTest("M2 実装後に fixtures/catalog/missing_column.md で検証する")

    def test_duplicate_heading_raises(self):
        raise unittest.SkipTest("M2 実装後に fixtures/catalog/duplicate_heading.md で検証する")

    def test_unknown_authority_in_catalog_raises(self):
        raise unittest.SkipTest("M2 実装後に fixtures/catalog/unknown_authority.md で検証する（V13）")

    def test_catalog_has_no_parent_links_today(self):
        raise unittest.SkipTest("M2 実装後、実カタログ読み込みで13行すべて parent_segment_id is None を確認する")


class TestCatalogIntegrity(unittest.TestCase):
    def test_undefined_segment_id_in_llm_output_is_rejected(self):
        raise unittest.SkipTest("M5 実装後に llm.validate_llm_output() で検証する（FR-24）")

    def test_integrity_check_blocks_write(self):
        raise unittest.SkipTest("M4 実装後に store.validate_integrity() で検証する")


if __name__ == "__main__":
    unittest.main()
