"""LLM フォールバック（FR-07 / IF-03）。実装設計 §4.6 / §2.5。

未解決行 → Observation[]。スキーマ検証と1回リトライ。
依存先: models, catalog, cache。parser には依存しない。

`--no-llm` の意味は **(A) LLM を新規に呼ばない**であり、
**(B) LLM 由来の抽出を一切使わない（キャッシュヒットも捨てる）ではない**
（実装設計 §2.5、確定事項）。閾値未満の行の処理順序:
    extraction-cache.json にヒット → キャッシュの observation を採用
                                       （--no-llm でも同じ）
    キャッシュミス
        --no-llm あり → LlmClient を呼ばずに unresolved へ（NullClient と同じ）
        --no-llm なし → ClaudeCliClient を呼び、結果をキャッシュに追記

リトライは1回のみ（FR-07）。1回目のプロンプト末尾に検証エラーを付けて
再送し、それでも失敗すれば reason_code="llm_schema_error" で unresolved
へ退避する。リトライ結果は成否によらずキャッシュに記録する（NFR-11の
キャッシュヒット率95%達成のため。空配列を返した記事を毎回再問い合わせしない）。

実行主体は claude-code-action ではなく `claude` CLI の subprocess 呼び出し
（ClaudeCliClient）。GitHub Actions ワークフロー定義自体は ci-cd-engineer の
管轄（cicd-design.md）。

テストは implementation-design.md §7.2 T-6
（test_undefined_segment_id_in_llm_output_is_rejected）を参照。
"""

from __future__ import annotations

from typing import Protocol

from retail_stats.models import Catalog, Observation


class LlmClient(Protocol):
    """LLM 抽出クライアントのインターフェース（実装設計 §4.6）。"""

    def extract(self, title: str, summary: str) -> str:
        """observation スキーマの JSON 配列を文字列で返す。"""
        ...


class NullClient:
    """`--no-llm` 指定時に使うクライアント。常に何も抽出しない。

    キャッシュ層より下に位置する（キャッシュヒット時はそもそも呼ばれない）。
    """

    def extract(self, title: str, summary: str) -> str:
        raise NotImplementedError


class ClaudeCliClient:
    """`claude` CLI を subprocess で呼び出す実クライアント（IF-03）。"""

    def extract(self, title: str, summary: str) -> str:
        raise NotImplementedError


def validate_llm_output(
    raw: str, catalog: Catalog, pub
) -> tuple[list[Observation], list[str]]:
    """LLM 出力の JSON をスキーマ検証する。戻り値は (妥当な Observation, エラー一覧)。

    カタログに存在しない segment_id / metric_id を含む出力は拒否する
    （FR-24。implementation-design.md §7.2 T-6
    test_undefined_segment_id_in_llm_output_is_rejected）。
    推測で値を埋めない。タイトルに現れない情報は null とし、根拠となる
    部分文字列を raw_expression に必ず含める
    （loop-engineering-design.md §4.1 retail-stats-extractor の description）。
    """
    raise NotImplementedError
