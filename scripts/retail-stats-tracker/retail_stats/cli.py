"""引数解析とパイプラインの結線（実装設計 §2.5 / §2.3 レイヤ4）。

責務: ドメインロジックを持たず、全レイヤ（store / report / llm / html.build /
parser など）を結線して build / html / measure の3サブコマンドを実行するのみ。

対応する実装設計の記述:
    §2.5 エントリポイントと CLI インターフェース（引数表・終了コード契約）
    §2.3 モジュールの責務と依存方向（cli.py は全レイヤに依存してよい唯一のモジュール）

引数（実装設計 §2.5 の表をそのまま反映）:
    --org SLUG                  既定 "domain-tech-collection"
    --rebuild                   manifest を無視して全 MD を処理（FR-12）
    --since YYYY-MM-DD          指定日以降の digest のみ処理（デバッグ用）
    --invalidate-cache          extraction-cache.json を破棄して LLM を再実行
    --no-llm                    LLM を新規に呼ばない（キャッシュヒットは使う）
    --dry-run                   標準出力にサマリーを出すのみでファイルを書かない
    --report-json PATH          差分レポートを JSON で書き出す（FR-22）
    --fail-on-unresolved-rate R 未解決率が R を超えたら exit 1（NFR-05 の CI ガード）

終了コード契約（実装設計 §2.5）:
    0 = 正常
    1 = データ不整合（カタログ検証失敗・未解決率超過）
    2 = 引数エラー
    3 = I/O エラー
`2>/dev/null` や `|| true` による握り潰しをしないこと（NFR-10）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_NUM_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")

from retail_stats import catalog as catalog_mod
from retail_stats import config, digest
from retail_stats.models import CatalogError

# 終了コード契約（実装設計 §2.5）
EXIT_OK = 0
EXIT_DATA_ERROR = 1
EXIT_ARG_ERROR = 2
EXIT_IO_ERROR = 3


def build_arg_parser() -> argparse.ArgumentParser:
    """build / html / measure の3サブコマンドを持つ ArgumentParser を構築する。

    実装設計 §2.5 の引数表に従う。各サブコマンドがどの引数を受け付けるかは
    表の「対象サブコマンド」列のとおりに絞ること（例: --invalidate-cache は
    build のみ）。
    """
    parser = argparse.ArgumentParser(
        prog="python3 -m retail_stats",
        description="小売月次統計トラッカー（日次ダイジェスト B5 章 → 時系列データ → 単一 HTML）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        """build / html / measure に共通する引数（§2.5 の表）。"""
        p.add_argument(
            "--org",
            default=config.DEFAULT_ORG,
            metavar="SLUG",
            help="処理対象組織。`.companies/{slug}/` を基点にする（既定: %(default)s）。"
            " パスではなく組織スラグを渡すこと。データ層の所在は環境変数"
            f" {config.WORKSPACE_ENV_VAR} で差し替える",
        )

    def add_scan(p: argparse.ArgumentParser) -> None:
        """build / measure に共通する走査系の引数（§2.5 の表）。"""
        p.add_argument("--rebuild", action="store_true", help="manifest を無視して全 MD を処理（FR-12）")
        p.add_argument("--since", metavar="YYYY-MM-DD", help="指定日以降の digest のみ処理（デバッグ用）")
        p.add_argument(
            "--no-llm",
            action="store_true",
            help="LLM を新規に呼ばない。extraction-cache.json のヒットは通常どおり使う",
        )
        p.add_argument("--report-json", metavar="PATH", help="差分レポートを JSON で書き出す（FR-22）")
        p.add_argument(
            "--fail-on-unresolved-rate",
            type=float,
            metavar="R",
            help="未解決率が R を超えたら exit 1（NFR-05 の CI ガード）",
        )

    p_build = sub.add_parser("build", help="増分実行（既定）")
    add_common(p_build)
    add_scan(p_build)
    p_build.add_argument(
        "--invalidate-cache",
        action="store_true",
        help="extraction-cache.json を破棄して LLM を再実行する。指定しない限りキャッシュは絶対に破棄しない",
    )
    p_build.add_argument(
        "--dry-run", action="store_true", help="標準出力にサマリーを出すのみでファイルを書かない"
    )

    p_html = sub.add_parser("html", help="HTML のみ再生成（データは変更しない）")
    add_common(p_html)

    p_measure = sub.add_parser("measure", help="reason_code 別の未解決分布を計測する")
    add_common(p_measure)
    add_scan(p_measure)

    return parser


def _print_resolved_inputs(org: str) -> dict[str, str]:
    """どの入力を読んだかを必ず出力する（origin.md D-A）。

    カタログが正準パスとリポジトリ内スナップショットのどちらから読まれたかが
    出力に現れないと、入力を取り違えたまま処理が進んだことに誰も気づけない。
    """
    info = config.resolved_inputs(org)
    print("入力の解決結果")
    print(f"  repo_root       : {info['repo_root']}")
    print(f"  workspace_root  : {info['workspace_root']}")
    print(f"  {config.WORKSPACE_ENV_VAR:<16}: {info['workspace_override']}")
    print(f"  org             : {info['org']}")
    print(f"  catalog         : {info['catalog_path']}")
    print(f"                    source={info['catalog_source']} exists={info['catalog_exists']}")
    print(f"  digest_dir      : {info['digest_dir']} (exists={info['digest_dir_exists']})")
    print(f"  data_dir        : {info['data_dir']}")
    # 配信先も必ず出す。どこに書き出してどこで見えるのかが分からないまま
    # 実行できてしまうと、Pages に載らない場所へ出力していても気づけない（D-G）
    print(f"  html_output     : {info['html_output_path']}")
    print(f"  公開 URL        : {info['html_public_url']}")
    return info


def _scan_digests(digest_dir: Path, since: str | None) -> list:
    files = digest.iter_digest_files(digest_dir, since=since)
    return [digest.parse_file(p) for p in files]


def _print_scan_summary(results: list) -> None:
    """M1 の完了条件が読み取れる形でサマリーを出す（実装設計 §8 M1）。"""
    with_section = [r for r in results if r.has_section]
    with_table = [r for r in results if r.has_table]
    rows = [row for r in results for row in r.rows]
    malformed = [m for r in results for m in r.malformed]
    without_section = [r.digest_date for r in results if not r.has_section]
    variants = Counter(r.header_variant for r in with_table)

    print()
    print("ダイジェスト走査（FR-01 / FR-02）")
    print(f"  走査ファイル              : {len(results)}")
    print(f"  決算・統計章を持つファイル: {len(with_section)}")
    print(f"  表を持つファイル          : {len(with_table)}")
    print(f"  データ行（延べ）          : {len(rows)}")
    print(f"  リンク抽出成功            : {len(rows)} / {len(rows) + len(malformed)}")
    print(f"  一意 URL                  : {len({row.url for row in rows})}")
    print(f"  ヘッダのバリエーション    : {len(variants)} 種")
    for variant, count in variants.most_common():
        print(f"      {variant}  x{count}")

    # 章が無い日は例外ではなく通常系。スキップ日数を必ず出す（要件 7-1）
    print(f"  files_without_section     : {len(without_section)}")
    if without_section:
        print(f"      {', '.join(without_section)}")

    # 捨てずに落とした行は必ず可視化する（要件 7-12 / NFR-10）
    if malformed:
        reasons = Counter(m.reason for m in malformed)
        print(f"  malformed（未解決へ退避） : {len(malformed)} {dict(reasons)}")
        for item in malformed[:5]:
            print(f"      [{item.reason}] {item.digest_date}: {item.raw_line[:100]}")


def _print_catalog_summary(cat) -> None:
    """M2 の完了条件（ID 一覧と発表主体コードの一覧）を出す（実装設計 §8 M2）。"""
    print()
    print("カタログ（IF-02）")
    print(f"  source_sha256 : {cat.source_sha256}")
    print(f"  業態          : {len(cat.segments)} 件")
    print(f"      {', '.join(s.segment_id for s in cat.segments)}")
    print(f"  指標          : {len(cat.metrics)} 件")
    print(f"      {', '.join(m.metric_id for m in cat.metrics)}")
    authorities = Counter(s.source_authority for s in cat.segments)
    print(f"  発表主体コード: {len(authorities)} 種")
    for code, count in sorted(authorities.items()):
        owners = [s.segment_id for s in cat.segments if s.source_authority == code]
        print(f"      {code:<30} x{count}  ({', '.join(owners)})")


def cmd_build(args: argparse.Namespace) -> int:
    """build サブコマンド。

    digest.py → catalog.py → cache.py → parser.py → llm.py → store.upsert()
    の順に結線する（実装設計 §1.3 パイプライン内部のデータフロー図）。

    M1 時点では `--dry-run` のみが完走する。パース以降（M3〜M5）と永続化
    （M4）は未実装であり、`--dry-run` なしの実行は「書ける中身が無い」
    ため exit 1 で止める。空の成果物で既存を上書きしない（NFR-12）。
    """
    info = _print_resolved_inputs(args.org)

    try:
        cat = catalog_mod.load(config.catalog_path(args.org))
    except CatalogError as exc:
        print(f"カタログの検証に失敗しました:\n{exc}", file=sys.stderr)
        return EXIT_DATA_ERROR
    except OSError as exc:
        print(f"カタログを読み込めません: {exc}", file=sys.stderr)
        return EXIT_IO_ERROR
    _print_catalog_summary(cat)

    digest_dir = config.digest_dir(args.org)
    if not digest_dir.is_dir():
        print(
            f"ダイジェストのディレクトリがありません: {digest_dir}\n"
            f"  → cc-sier-organization の作業コピーを {config.WORKSPACE_ENV_VAR} で指すか、"
            f"テスト用フィクスチャを使ってください（origin.md D-A）",
            file=sys.stderr,
        )
        return EXIT_IO_ERROR

    try:
        results = _scan_digests(digest_dir, args.since)
    except OSError as exc:
        print(f"ダイジェストを読み込めません: {exc}", file=sys.stderr)
        return EXIT_IO_ERROR
    _print_scan_summary(results)

    # --- パース（M3）→ 永続化（M4）--------------------------------------
    from retail_stats import parser as parser_mod
    from retail_stats import store, textnorm

    rows = [row for r in results for row in r.rows]
    by_url: dict[str, list] = {}
    for row in rows:
        by_url.setdefault(row.url, []).append(row)

    observations: dict = {}
    articles: dict = {}
    unresolved: dict = {}
    actions = Counter()
    upsert_results: list = []
    for url in sorted(by_url):
        group = sorted(by_url[url], key=lambda r: r.digest_date)
        for row in group:
            store.merge_article(articles, url, row.title, row.source_name, row.digest_date)
        # 抽出は**代表 variant 1 つ**に対して行う（§4.7）。掲載日は初出日を使い、
        # 実行時刻も走査順も持ち込まない（NFR-06）。
        representative = max(
            group,
            key=lambda r: (
                len(_NUM_RE.findall(textnorm.normalize(r.title))), len(r.title), r.title
            ),
        )
        aid = store.article_id(url)
        first_seen = min(r.digest_date for r in group)
        target = type(representative)(
            digest_date=first_seen, row_index=representative.row_index,
            title=representative.title, url=url, source_name=representative.source_name,
            summary=representative.summary, raw_line=representative.raw_line,
        )
        result = parser_mod.parse_row(target, cat, aid)
        for obs in result.observations:
            upsert_result = store.upsert(observations, obs)
            upsert_results.append(upsert_result)
            actions[upsert_result.action] += 1
        for row in result.unresolved:
            store.merge_unresolved(unresolved, row, aid)

    manifest = {
        str(p.name): {
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "mtime_date": digest.date_from_filename(p),
            "row_count": len(r.rows),
        }
        for p, r in zip(digest.iter_digest_files(digest_dir, since=args.since), results)
    }

    print()
    print("パース結果")
    print(f"  observations : {len(observations)}  {dict(actions)}")
    print(f"  articles     : {len(articles)}")
    print(f"  unresolved   : {len(unresolved)}")

    if args.dry_run:
        print("\n--dry-run のためファイルは書き出していません。")
        return EXIT_OK

    data_dir = config.data_dir(args.org)
    try:
        store.write_all(data_dir, observations, articles, unresolved, manifest, cat)
    except store.IntegrityError as exc:
        # 書き出し前に停止する。壊れた成果物を残さない（NFR-12）
        print(f"参照整合性の検査に失敗しました:\n{exc}", file=sys.stderr)
        return EXIT_DATA_ERROR
    except OSError as exc:
        print(f"書き出しに失敗しました: {exc}", file=sys.stderr)
        return EXIT_IO_ERROR

    # --- 配信 JSON + 単一 HTML（M6 / FR-13 / FR-14）------------------------
    from retail_stats import report
    from retail_stats.html import build as html_build

    meta = {
        "generated_from_digest_max_date": max(
            (r.digest_date for r in results if r.digest_date), default=""),
        "digest_files_scanned": len(results),
        "digest_files_with_section": sum(1 for r in results if r.has_section),
        "observation_count": len(observations),
        "unresolved_count": len(unresolved),
        "catalog_sha256": cat.source_sha256,
    }
    series = report.build_series(
        list(observations.values()), list(articles.values()),
        list(unresolved.values()), cat, meta,
    )
    store.write_json(data_dir / "series.json", series)

    html_path = config.html_output_path()
    try:
        html_build.build(series, html_path)
    except html_build.SelfContainedError as exc:
        # 自己完結でない成果物は配信しない（NFR-08）。既存 HTML も壊さない
        print(f"HTML の自己完結性検査に失敗しました:\n{exc}", file=sys.stderr)
        return EXIT_DATA_ERROR

    print(f"\n書き出しました: {data_dir}")
    for name in config.IDEMPOTENT_FILES:
        path = data_dir / name
        if path.is_file():
            print(f"  {name:<24} {path.stat().st_size:>8,} bytes")
    print(f"\n配信 HTML: {html_path}  ({html_path.stat().st_size:,} bytes / 上限 2 MB)")
    print(f"  公開 URL: {config.PUBLIC_SITE_URL}")

    # --- 差分レポート（FR-22 / 要件リスク 7-8）-----------------------------
    diff = report.build_diff_report(upsert_results, list(unresolved.values()), series["quality"])
    if diff["value_changes"]:
        print(f"\n**値が変わった観測 {len(diff['value_changes'])} 件**"
              "（速報→確報の改定か記事の誤記訂正）")
        for change in diff["value_changes"][:20]:
            key = change["natural_key"].replace("\x1f", " / ")
            print(f"  {key}")
            print(f"      {change['before']['value']} → {change['after']['value']}")
    if args.report_json:
        Path(args.report_json).write_text(
            json.dumps(diff, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        markdown = Path(args.report_json).with_suffix(".md")
        markdown.write_text(report.format_diff_report_markdown(diff), encoding="utf-8")
        print(f"\n差分レポート: {args.report_json}")
        print(f"  PR 本文向け: {markdown}")

    # --- NFR-05 の CI ガード（--fail-on-unresolved-rate）--------------------
    threshold = args.fail_on_unresolved_rate
    if threshold is not None:
        unresolved_rate = 1.0 - series["quality"]["nfr05"]["rate"]
        if unresolved_rate > threshold:
            print(
                f"\n未解決率 {unresolved_rate:.1%} が閾値 {threshold:.1%} を超えています"
                "（NFR-05 の CI ガード）",
                file=sys.stderr,
            )
            return EXIT_DATA_ERROR
    return EXIT_OK


def cmd_html(args: argparse.Namespace) -> int:
    """html サブコマンド。series.json は変更せず HTML のみ再生成する（M6）。"""
    from retail_stats.html import build as html_build

    _print_resolved_inputs(args.org)
    series_path = config.data_dir(args.org) / "series.json"
    if not series_path.is_file():
        print(f"series.json がありません: {series_path}\n"
              f"  → 先に `build` を実行してください", file=sys.stderr)
        return EXIT_IO_ERROR
    series = json.loads(series_path.read_text(encoding="utf-8"))
    html_path = config.html_output_path()
    try:
        html_build.build(series, html_path)
    except html_build.SelfContainedError as exc:
        print(f"HTML の自己完結性検査に失敗しました:\n{exc}", file=sys.stderr)
        return EXIT_DATA_ERROR
    print(f"\n配信 HTML: {html_path}  ({html_path.stat().st_size:,} bytes)")
    print(f"  公開 URL: {config.PUBLIC_SITE_URL}")
    return EXIT_OK


def cmd_measure(args: argparse.Namespace) -> int:
    """measure サブコマンド。

    reason_code 別の未解決分布、NFR-04 / NFR-05 の達成率、発表主体別の
    observation 件数などを計測する（実装設計 §8 M3、要件リスク 7-7 の実装先）。
    独立した PoC フェーズを設けず、恒久的な CLI サブコマンドとして残す。

    **母集団は一意 URL の代表 variant**（§4.7 の選択規則）。延べ行で数えると
    同一記事の再掲が成功／失敗の双方を水増しし、NFR-05 の分母が §4.3.7 の
    実測（83）と別物になる（ループ設計 §2.3 ⑦ の「単位を取り違えない」）。
    """
    from retail_stats import parser as parser_mod
    from retail_stats import report, textnorm

    _print_resolved_inputs(args.org)
    try:
        cat = catalog_mod.load(config.catalog_path(args.org))
    except CatalogError as exc:
        print(f"カタログの検証に失敗しました:\n{exc}", file=sys.stderr)
        return EXIT_DATA_ERROR

    digest_dir = config.digest_dir(args.org)
    if not digest_dir.is_dir():
        print(f"ダイジェストのディレクトリがありません: {digest_dir}", file=sys.stderr)
        return EXIT_IO_ERROR

    results = _scan_digests(digest_dir, args.since)
    _print_scan_summary(results)

    rows = [row for r in results for row in r.rows]
    by_url: dict[str, list] = {}
    for row in rows:
        by_url.setdefault(row.url, []).append(row)

    observations, unresolved = [], []
    for url in sorted(by_url):
        group = by_url[url]
        representative = max(
            group,
            key=lambda r: (
                len(_NUM_RE.findall(textnorm.normalize(r.title))), len(r.title), r.title
            ),
        )
        article_id = hashlib.sha256(url.encode()).hexdigest()[:16]
        result = parser_mod.parse_row(representative, cat, article_id)
        observations.extend(result.observations)
        unresolved.extend(result.unresolved)

    articles = [
        _Article(
            hashlib.sha256(url.encode()).hexdigest()[:16],
            tuple(sorted({r.digest_date for r in group})),
        )
        for url, group in sorted(by_url.items())
    ]
    quality = report.build_quality_summary(observations, unresolved, articles, cat)
    _print_measure(quality, unresolved, report)

    if args.report_json:
        Path(args.report_json).write_text(
            json.dumps(quality, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"\nレポートを書き出しました: {args.report_json}")

    threshold = args.fail_on_unresolved_rate
    if threshold is not None:
        unresolved_rate = 1.0 - quality["nfr05"]["rate"]
        if unresolved_rate > threshold:
            print(
                f"\n未解決率 {unresolved_rate:.1%} が閾値 {threshold:.1%} を超えています"
                " （NFR-05 の CI ガード）",
                file=sys.stderr,
            )
            return EXIT_DATA_ERROR
    return EXIT_OK


@dataclass(frozen=True)
class _Article:
    """measure が duplication を数えるための最小の記事表現（M4 の store.py に移す）。"""

    article_id: str
    appeared_dates: tuple[str, ...]


def _print_measure(quality: dict, unresolved, report) -> None:
    nfr05, nfr04 = quality["nfr05"], quality["nfr04"]
    print()
    print("NFR-05 対象内行の抽出成功率（母集団: 一意 URL の代表 variant）")
    print(f"  分子 / 分母        : {nfr05['numerator']} / {nfr05['denominator']}")
    print(f"  達成率             : {nfr05['rate']:.1%}  （目標 {nfr05['target']:.0%}）")
    print(f"  判定               : {'達成' if nfr05['met'] else '**未達**'}")

    print()
    print("NFR-04 主要 4 業態の月次既存店指標")
    print(f"  カバー             : {len(nfr04['covered'])} / 4  {nfr04['covered']}")
    if nfr04["missing"]:
        print(f"  **欠落**           : {nfr04['missing']}")
    print(f"  observation 件数   : {nfr04['observation_count']}")
    print(f"  達成率             : {nfr04['rate']:.1%}  （目標 {nfr04['target']:.0%}）")
    print(f"  判定               : {'達成' if nfr04['met'] else '**未達**'}")

    print()
    print("reason_code 別の件数")
    for code, count in quality["by_reason_code"].items():
        mark = "  （分母から除外）" if code == "out_of_scope" else ""
        print(f"  {code:<20} {count:>4}{mark}")
    oos = quality["out_of_scope_breakdown"]
    print(f"    ├ 個社開示       {oos['company_disclosure']:>4}")
    print(f"    └ 非統計記事     {oos['non_statistical']:>4}")

    print()
    print("発表主体別の observation 件数")
    for authority, count in quality["by_authority"].items():
        print(f"  {authority:<32} {count:>4}")
    multi = quality["multi_authority_segments"]
    print(f"  複数主体を持つ業態 : {multi if multi else '（なし）'}")

    dup = quality["duplication"]
    print()
    print(f"重複: 一意 {dup['unique_articles']} / 延べ {dup['total_rows']} "
          f"/ 重複 {dup['duplicate_rows']} / 最大掲載 {dup['max_appeared']} 日")

    print()
    print("未解決行の原文（reason_code 別・上位 20 件）")
    for code, samples in sorted(report.unresolved_samples(unresolved).items()):
        print(f"  [{code}] {len(samples)} 件")
        for line in samples[:20]:
            print(f"      {line[:110]}")


def main(argv: list[str] | None = None) -> int:
    """CLI エントリポイント。__main__.py から呼ばれる。"""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    handlers = {"build": cmd_build, "html": cmd_html, "measure": cmd_measure}
    handler = handlers.get(args.command)
    if handler is None:  # argparse の required=True により通常は到達しない
        parser.error(f"未知のサブコマンド: {args.command}")
        return EXIT_ARG_ERROR
    try:
        return handler(args)
    except NotImplementedError as exc:
        # 未実装は「握り潰さずに終了コードで示す」（NFR-10 / §2.5 の終了コード契約）
        print(f"未実装のサブコマンドです: {exc}", file=sys.stderr)
        return EXIT_DATA_ERROR
    except FileNotFoundError as exc:
        print(f"パス解決に失敗しました: {exc}", file=sys.stderr)
        return EXIT_IO_ERROR
