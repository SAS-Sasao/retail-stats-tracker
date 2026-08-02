"""パス解決・閾値定数（org 依存を集約）。実装設計 §2.3 レイヤ0。

`parse-wbs.py` の `REPO_ROOT = Path(__file__).resolve().parents[2]` は
「考え方のみ移植」（実装設計 §2.4）: 本パッケージは配置階層が異なるため、
`.git` / `.claude-plugin` の存在を上位ディレクトリへ辿って解決する。

正準の配置（実装設計 §2.1 / 要件 §1.4 / IF-05）:
    コード:    scripts/retail-stats-tracker/retail_stats/
    データ:    {workspace}/.companies/{org}/docs/retail-stats/data/
    カタログ:  {workspace}/.companies/{org}/docs/retail-domain/retail-monthly-kpi-catalog.md
    ダイジェスト: {workspace}/.companies/{org}/docs/daily-digest/
    配信 HTML: {workspace}/docs/retail-stats/index.html（org 非依存。配信先リポに追随）

## 本リポジトリ単体で動かすための入力所在ポリシー（origin.md「入力データの所在」）

設計は cc-sier-organization リポジトリ上で動く前提で書かれており、
`.companies/{org}/` はこのリポジトリには存在しない。そこで:

1. **`--org SLUG` の意味は変えない**（実装設計 §2.5）。`--org` は常に
   組織スラグであり、`.companies/{slug}/` を組み立てる。パスは受け取らない。
2. `.companies/` を含むディレクトリ（= ワークスペースルート）だけを
   環境変数 `RETAIL_STATS_WORKSPACE` で差し替え可能にする。未設定なら
   リポジトリルート。これにより cc-sier の作業コピーを外から指せる。
3. **カタログのみ**、正準パスが存在しない場合に本リポジトリのスナップショット
   `docs/design/retail-monthly-kpi-catalog.md` へフォールバックする。
   どちらを読んだかは `resolved_inputs()` が返し、CLI が必ず表示する
   （どの入力を読んだか分からないまま処理が進むことを許さない）。
4. テストは常にフィクスチャ（`tests/fixtures/`）を直接指す。実データの
   所在に依存しない（実装設計 §7.3）。
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ORG = "domain-tech-collection"

# リポジトリルートの判定マーカー（実装設計 §2.4）
REPO_ROOT_MARKERS = (".git", ".claude-plugin")

# `.companies/` を含むディレクトリを差し替える環境変数。`--org` の意味
# （組織スラグ）を保ったまま、データ層が別リポジトリにある状況を吸収する。
WORKSPACE_ENV_VAR = "RETAIL_STATS_WORKSPACE"

# 組織スコープ内の相対パス（`.companies/{org}/` 起点）
CATALOG_RELPATH = "docs/retail-domain/retail-monthly-kpi-catalog.md"
DIGEST_RELPATH = "docs/daily-digest"
DATA_RELPATH = "docs/retail-stats/data"

# 本リポジトリが保持するカタログのスナップショット（リポジトリルート起点）。
# 正準パスが存在しないときのフォールバック先。
CATALOG_SNAPSHOT_RELPATH = "docs/design/retail-monthly-kpi-catalog.md"

# 配信 HTML（IF-05、org 非依存。**ワークスペースルート起点**）。
# 配信は cc-sier-organization の GitHub Pages で行う（origin.md D-G）。
HTML_RELPATH = "docs/retail-stats/index.html"

# 公開 URL。cc-sier の Pages 設定は main ブランチ `/docs` なので、
# `docs/retail-stats/index.html` は下記で配信される。
PUBLIC_SITE_URL = "https://sas-sasao.github.io/cc-sier-organization/retail-stats/"

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

    見つからない場合は FileNotFoundError（CLI の終了コード 3 = I/O エラーに対応）。
    """
    base = Path(start) if start is not None else Path(__file__)
    base = base.resolve()
    for candidate in (base, *base.parents):
        if not candidate.is_dir():
            continue
        if any((candidate / marker).exists() for marker in REPO_ROOT_MARKERS):
            return candidate
    raise FileNotFoundError(
        f"リポジトリルートを解決できません: {REPO_ROOT_MARKERS} のいずれも "
        f"{base} から上位に見つかりませんでした"
    )


def workspace_root(repo_root: Path | None = None) -> Path:
    """`.companies/` を含むディレクトリを返す。

    環境変数 `RETAIL_STATS_WORKSPACE` が設定されていればそれを使う。
    未設定ならリポジトリルート（= 設計どおり cc-sier 上で実行した場合の挙動）。
    """
    override = os.environ.get(WORKSPACE_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return repo_root if repo_root is not None else find_repo_root()


def org_root(org: str = DEFAULT_ORG, repo_root: Path | None = None) -> Path:
    """`{workspace}/.companies/{org}/` を返す。"""
    return workspace_root(repo_root) / ".companies" / org


def data_dir(org: str = DEFAULT_ORG, repo_root: Path | None = None) -> Path:
    """`.companies/{org}/docs/retail-stats/data/` を返す。

    書き込み先であるためフォールバックを持たない（正準パス 1 本のみ）。
    """
    return org_root(org, repo_root) / DATA_RELPATH


def catalog_path_candidates(
    org: str = DEFAULT_ORG, repo_root: Path | None = None
) -> tuple[Path, ...]:
    """カタログの探索順（正準 → 本リポジトリのスナップショット）を返す。"""
    root = repo_root if repo_root is not None else find_repo_root()
    return (
        org_root(org, root) / CATALOG_RELPATH,
        root / CATALOG_SNAPSHOT_RELPATH,
    )


def catalog_path(org: str = DEFAULT_ORG, repo_root: Path | None = None) -> Path:
    """カタログ MD の実パスを返す。

    正準パス（`.companies/{org}/docs/retail-domain/...`）が存在すればそれを、
    存在しなければ本リポジトリのスナップショット（`docs/design/...`）を返す。
    どちらも存在しない場合は正準パスを返す（エラーメッセージが正準の所在を
    指すようにするため）。実際にどちらを読んだかは `resolved_inputs()` で
    取得でき、CLI が必ず表示する。
    """
    candidates = catalog_path_candidates(org, repo_root)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def digest_dir(org: str = DEFAULT_ORG, repo_root: Path | None = None) -> Path:
    """`.companies/{org}/docs/daily-digest/` を返す。

    本リポジトリにはスナップショットが無いためフォールバックを持たない。
    存在しない場合は `RETAIL_STATS_WORKSPACE` で cc-sier の作業コピーを指すか、
    テスト用フィクスチャ（`tests/fixtures/digests/`）を直接指定する。
    """
    return org_root(org, repo_root) / DIGEST_RELPATH


def html_output_path(repo_root: Path | None = None) -> Path:
    """`docs/retail-stats/index.html`（IF-05、org 非依存）を返す。

    **配信するリポジトリ（= ワークスペースルート）に追随する。**
    配信は cc-sier-organization の GitHub Pages（`main` ブランチ `/docs`、
    `https://sas-sasao.github.io/cc-sier-organization/`）で行うと決めたため
    （origin.md D-G）、`RETAIL_STATS_WORKSPACE` で cc-sier の作業コピーを
    指しているときは**そちらの `docs/` に書き出す**必要がある。

    未設定ならリポジトリルート = 本リポジトリの `docs/` になり、
    ローカルプレビュー（`file://` で開く。NFR-08）として機能する。

    org 非依存である点は変わらない（`.companies/{org}/` の下ではない）。
    """
    return workspace_root(repo_root) / HTML_RELPATH


def resolved_inputs(org: str = DEFAULT_ORG, repo_root: Path | None = None) -> dict[str, str]:
    """実際に使うパスと、その存在有無を返す（`--dry-run` / 実行サマリー用）。

    どの入力を読んだかを黙って決めないための報告口。カタログが正準と
    スナップショットのどちらから読まれたかが必ず出力に現れる。
    """
    root = repo_root if repo_root is not None else find_repo_root()
    catalog = catalog_path(org, root)
    canonical_catalog = catalog_path_candidates(org, root)[0]
    digests = digest_dir(org, root)
    data = data_dir(org, root)
    return {
        "repo_root": str(root),
        "workspace_root": str(workspace_root(root)),
        "workspace_override": os.environ.get(WORKSPACE_ENV_VAR, "") or "(未設定)",
        "org": org,
        "catalog_path": str(catalog),
        "catalog_source": "canonical" if catalog == canonical_catalog else "repo-snapshot",
        "catalog_exists": str(catalog.is_file()),
        "digest_dir": str(digests),
        "digest_dir_exists": str(digests.is_dir()),
        "data_dir": str(data),
        "html_output_path": str(html_output_path(root)),
        "html_public_url": PUBLIC_SITE_URL,
    }
