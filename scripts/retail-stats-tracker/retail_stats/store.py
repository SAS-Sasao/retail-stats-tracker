"""JSON 永続化・冪等 upsert（FR-09 / FR-23）。実装設計 §5。

依存先: models, config。parser / llm には依存しない（永続化の都合を
上位に漏らさない。実装設計 §2.3）。

natural key は5要素 (segment_id, metric_id, scope, period_key,
source_authority)（要件 v0.1.1 FR-09、実装設計 §9.3 D1）。
source_authority を含めることで、協会統計と経産省統計など発表主体の
異なる系列を上書きさせず共存させる（要件 7-14）。

冪等性の担保（NFR-06 バイト一致。実装設計 §5.4 の6規則。1つでも欠けると
一致しない）:
    1. dict のキー順に依存しない出力（sort_keys=True 相当）
    2. 書き出し前に全コレクションをソートする（observations は
       natural key の各要素順、articles は article_id、unresolved は
       (article_id, reason_code)、cache は cache_key の昇順）
    3〜6. 実装時に implementation-design.md §5.4 を直接参照して実装する

比較対象6ファイル（config.IDEMPOTENT_FILES と同一。runs.json は実行時刻を
含むため除外）: observations.json / articles.json / extraction-cache.json /
unresolved.json / manifest.json / series.json
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, replace
from pathlib import Path

from retail_stats.models import Observation, SourceArticle, UnresolvedRow, UpsertResult

SCHEMA_VERSION = 1

NATURAL_KEY_FIELDS = ("segment_id", "metric_id", "scope", "period_key", "source_authority")


class IntegrityError(Exception):
    """参照整合性の検査（§5.5）に違反したときに送出する。書き出し前に停止する。"""


def natural_key(o: Observation) -> str:
    return "\x1f".join(getattr(o, f) for f in NATURAL_KEY_FIELDS)


def observation_id(o: Observation) -> str:
    return hashlib.sha256(natural_key(o).encode("utf-8")).hexdigest()[:16]


def article_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _wins(new: Observation, old: Observation) -> bool:
    """FR-09: confidence が高い方。同値なら掲載日が新しい方。それも同値なら既存を維持。

    **最後に False を返す（既存を維持する）ことが重要**。完全同点で新側を採ると
    ファイル走査順に依存し、NFR-06（バイト一致）が崩れる。
    """
    if new.confidence != old.confidence:
        return new.confidence > old.confidence
    if new.first_seen_date != old.first_seen_date:
        return new.first_seen_date > old.first_seen_date
    return False


def upsert(index: dict[str, Observation], new: Observation) -> UpsertResult:
    """natural key で収束させる（FR-09 / FR-23）。パーサは重複を意識しない。

    **発表主体が異なる観測は上書き対象にならない。** `source_authority` が
    natural key に含まれるため、協会統計と経産省統計は別キーとして共存する
    （要件 7-14）。`_wins()` の勝敗判定に発表主体を持ち込まない
    ——どちらが「正しい」かを本システムは判定しない。
    """
    key = natural_key(new)
    old = index.get(key)
    if old is None:
        index[key] = replace(
            new, observation_id=observation_id(new),
            first_seen_date=new.first_seen_date, last_updated_date=new.first_seen_date,
        )
        return UpsertResult(action="created", key=key, before=None, after=index[key])

    if old.manual_override:      # FR-23: 手動補正は自動 upsert で上書きしない
        return UpsertResult(action="skipped_manual", key=key, before=old, after=old)

    if _wins(new, old):
        merged = replace(
            new, observation_id=old.observation_id,
            first_seen_date=min(old.first_seen_date, new.first_seen_date),
            last_updated_date=max(old.last_updated_date, new.first_seen_date),
        )
        index[key] = merged
        return UpsertResult(action="updated", key=key, before=old, after=merged)

    # 負けた場合でも観測日レンジは伸ばす
    index[key] = replace(old, last_updated_date=max(old.last_updated_date, new.first_seen_date))
    return UpsertResult(action="unchanged", key=key, before=old, after=index[key])


def merge_article(index: dict[str, SourceArticle], url: str, title: str, source_name: str,
                  digest_date: str) -> SourceArticle:
    """URL で dedup し、title_variants と appeared_dates を伸ばす（NFR-07）。

    同一記事が N 日掲載されても observation は増えない。`s041442` は
    非連続 6 日（04-15/16/17/18/22/23）に出現するため、連続日を前提にした
    実装では落ちる（T-1）。
    """
    aid = article_id(url)
    existing = index.get(aid)
    if existing is None:
        index[aid] = SourceArticle(
            article_id=aid, url=url, title_first_seen=title, title_variants=(title,),
            source_name=source_name, source_name_normalized=source_name,
            first_published_date=digest_date, appeared_dates=(digest_date,),
        )
        return index[aid]

    variants = tuple(sorted(set(existing.title_variants) | {title}))
    dates = tuple(sorted(set(existing.appeared_dates) | {digest_date}))
    first_date = min(existing.first_published_date, digest_date)
    # title_first_seen は初出日のタイトル。掲載日が早い方を採る（走査順非依存）
    first_title = title if digest_date < existing.first_published_date else existing.title_first_seen
    index[aid] = replace(
        existing, title_first_seen=first_title, title_variants=variants,
        first_published_date=first_date, appeared_dates=dates,
    )
    return index[aid]


def merge_unresolved(index: dict[tuple[str, str], UnresolvedRow], row: UnresolvedRow,
                     article: str) -> None:
    """`(article_id, reason_code)` で 1 エントリに集約する（§4.3.7）。

    `digest_date` には**初出日**を入れる。掲載回数は持たせない
    （必要なら `articles.json` の `appeared_dates` の長さから導出する）。
    """
    key = (article, row.reason_code)
    existing = index.get(key)
    if existing is None or row.digest_date < existing.digest_date:
        index[key] = replace(row, digest_date=min(row.digest_date, existing.digest_date)
                             if existing else row.digest_date)


def round_values(observations, catalog) -> list[Observation]:
    """value を `metric.precision` に丸める（§5.4 規則 4）。

    `-1.6000000000000001` のような表現差を防ぐ。**書き出し時に行う**。
    """
    out = []
    for o in observations:
        if o.value is None:
            out.append(o)
            continue
        out.append(replace(o, value=round(o.value, catalog.metric(o.metric_id).precision)))
    return out


def validate_integrity(observations, articles, catalog) -> None:
    """§5.5 参照整合性。**書き出し前**に検査し、違反があれば書かずに停止する。

    出典を持たない observation や、カタログに無い ID を含むデータを
    永続化させない（FR-24 / NFR-12）。
    """
    article_ids = {a.article_id for a in articles}
    segments = {s.segment_id for s in catalog.segments}
    metrics = {m.metric_id for m in catalog.metrics}
    problems: list[str] = []
    for o in observations:
        if o.article_id not in article_ids:
            problems.append(f"[I1] 出典を持たない observation: {o.observation_id} article_id={o.article_id}")
        if o.segment_id not in segments:
            problems.append(f"[I2] 未定義の segment_id: {o.segment_id}（{o.observation_id}）")
        if o.metric_id not in metrics:
            problems.append(f"[I3] 未定義の metric_id: {o.metric_id}（{o.observation_id}）")
        if o.period_start > o.period_end:
            problems.append(f"[I7] period_start > period_end: {o.observation_id}")
        if (o.value is None) == (o.sign_only is None):
            problems.append(f"[I8] value と sign_only の一方だけが埋まっていない: {o.observation_id}")
    if problems:
        raise IntegrityError(
            f"参照整合性の検査に失敗しました（{len(problems)} 件）:\n  - " + "\n  - ".join(problems)
        )


def write_json(path: Path, payload: dict) -> None:
    """§5.4 の規則 3 / 5 / 6 を満たす書き出し。

    キー順とインデントを固定し、改行は LF、`{path}.tmp` 経由でアトミックに置換する。
    生成途中で失敗しても成果物を空で壊さない（NFR-12）。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True, separators=(",", ": ")
    ) + "\n"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _sorted_observations(index) -> list[dict]:
    return [asdict(o) for o in sorted(index.values(), key=natural_key)]


def write_all(data_dir: Path, observations: dict, articles: dict, unresolved: dict,
              manifest: dict, catalog) -> None:
    """§5.4 の 6 規則に従って全ファイルを書き出す。

    **書き出し前に全コレクションをソートする**（規則 2）。dict の挿入順や
    ファイル走査順への依存を断つため。
    """
    data_dir = Path(data_dir)
    rounded = {natural_key(o): o for o in round_values(list(observations.values()), catalog)}
    validate_integrity(rounded.values(), articles.values(), catalog)

    write_json(data_dir / "observations.json",
               {"schema_version": SCHEMA_VERSION, "observations": _sorted_observations(rounded)})
    write_json(data_dir / "articles.json", {
        "schema_version": SCHEMA_VERSION,
        "articles": [asdict(a) for a in sorted(articles.values(), key=lambda a: a.article_id)],
    })
    write_json(data_dir / "unresolved.json", {
        "schema_version": SCHEMA_VERSION,
        "rows": [asdict(u) for _, u in sorted(unresolved.items(), key=lambda kv: kv[0])],
    })
    write_json(data_dir / "manifest.json",
               {"schema_version": SCHEMA_VERSION, "files": dict(sorted(manifest.items()))})


def load_observations(path: Path) -> dict[str, Observation]:
    """既存の observations.json を natural key 索引として読む。"""
    path = Path(path)
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    index: dict[str, Observation] = {}
    for record in payload.get("observations", []):
        o = Observation(**record)
        index[natural_key(o)] = o
    return index
