"""パス解決・閾値定数（org 依存を集約）。実装設計 §2.3 レイヤ0。

依存先は pathlib のみ（他モジュールに依存しない）。`parse-wbs.py` の
`REPO_ROOT = Path(__file__).resolve().parents[2]` は「考え方のみ移植」
（実装設計 §2.4）: 本パッケージは配置階層が異なるため、`.git` /
`.claude-plugin` の存在を上位ディレクトリへ辿って解決する。

このリポジトリでの配置（実装設計 §2.1 の決定を新リポ構成に適用）:
    コード:   scripts/retail-stats-tracker/retail_stats/
    データ:   .companies/{org}/docs/retail-stats/data/
              （cc-sier-organization 側の組織スコープ。本リポには存在しない）
    カタログ: .companies/{org}/docs/retail-domain/retail-monthly-kpi-catalog.md
    配信 HTML: docs/retail-stats/index.html（IF-05）

このリポジトリは cc-sier-organization からの設計スナップショットであり、
実行対象の `.companies/{org}/` はこのリポジトリ自身には存在しない。
`--org` 引数は将来 cc-sier リポジトリ上で実行する、または本リポジトリに
`.companies/` 相当のデータ層を持ち込む場合に備えた抽象化である
（実装設計 §2.5 の `--org SLUG` 引数）。
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_ORG = "domain-tech-collection"

# 決定論パースの確信度しきい値（実装設計 §4.3.7 / FR-07 既定 0.70）
CONFIDENCE_THRESHOLD = 0.70

# NFR-05 未解決率のガード既定値（20% 超で fail。loop-engineering-design §1.2 L_extract）
DEFAULT_FAIL_ON_UNRESOLVED_RATE = 0.20

# 冪等性・再現性の比較対象 6 ファイル（実装設計 §5.1 IDEMPOTENT_FILES と同一）。
# runs.json は実行時刻を含むため必ず除外する。
IDEMPOTENT_FILES = (
    "observations.json",
    "articles.json",
    "extraction-cache.json",
    "unresolved.json",
    "manifest.json",
    "series.json",
)

# DATA_DIR 直下に存在してよいファイルの期待値集合（8種）。IDEMPOTENT_FILES 6 種 +
# runs.json（実行メタデータ）+ permanently-unresolvable.json（人間の判断ファイル）。
# loop-engineering-design.md §3.2「DATA_DIR 直下のファイル集合との関係」参照。
DATA_DIR_EXPECTED_FILES = IDEMPOTENT_FILES + ("runs.json", "permanently-unresolvable.json")


def find_repo_root(start: Path | None = None) -> Path:
    """`.git` または `.claude-plugin` の存在を上位に辿ってリポジトリルートを解決する。

    parse-wbs.py の固定 parents[N] 方式ではなく探索方式にするのは、
    このパッケージが `scripts/retail-stats-tracker/` という深さに置かれており、
    かつ将来の配置変更に対して脆くしないため（実装設計 §2.4）。
    """
    raise NotImplementedError("`.git` を上位に辿って解決する")


def data_dir(org: str = DEFAULT_ORG, repo_root: Path | None = None) -> Path:
    """`.companies/{org}/docs/retail-stats/data/` を返す。"""
    raise NotImplementedError


def catalog_path(org: str = DEFAULT_ORG, repo_root: Path | None = None) -> Path:
    """`.companies/{org}/docs/retail-domain/retail-monthly-kpi-catalog.md` を返す。"""
    raise NotImplementedError


def digest_dir(org: str = DEFAULT_ORG, repo_root: Path | None = None) -> Path:
    """`.companies/{org}/docs/daily-digest/` を返す。"""
    raise NotImplementedError


def html_output_path(repo_root: Path | None = None) -> Path:
    """`docs/retail-stats/index.html`（IF-05、org 非依存）を返す。"""
    raise NotImplementedError
