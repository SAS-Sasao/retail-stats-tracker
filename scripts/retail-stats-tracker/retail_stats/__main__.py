"""python3 -m retail_stats のエントリポイント。

実装設計 §2.5「エントリポイントと CLI インターフェース」に対応する。
実体のサブコマンド解釈は cli.py に委ねる（このファイル自体はドメインロジックを持たない）。

使用例（実装設計 §2.5）:
    python3 -m retail_stats build
    python3 -m retail_stats build --rebuild
    python3 -m retail_stats build --no-llm
    python3 -m retail_stats build --rebuild --invalidate-cache
    python3 -m retail_stats html
    python3 -m retail_stats measure --rebuild --report-json /tmp/measure.json
"""

from retail_stats.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
