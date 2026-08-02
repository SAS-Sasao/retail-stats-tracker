"""retail_stats — 小売月次統計トラッカーのパッケージ本体。

日次ダイジェストの「B5. 決算・統計」章を決定論パース + LLM フォールバックで
構造化し、単一 HTML のトレンド可視化サイトとして配信する。

設計の出自:
    docs/design/implementation-design.md（実装設計）
    docs/design/loop-engineering-design.md（開発ループ・検証 hooks・Subagent 編成）
    docs/design/cicd-design.md（CI/CD・日次自動更新）
    docs/design/requirements.md（要件定義 v0.1.1、上位文書）

依存方向（実装設計 §2.3）:
    レイヤ0 models / textnorm / config
    レイヤ1 catalog / digest / cache
    レイヤ2 parser（→ period）
    レイヤ3 store / report / llm / html.build
    レイヤ4 cli
"""
