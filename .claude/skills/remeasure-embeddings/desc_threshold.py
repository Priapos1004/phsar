"""The study behind merge detection's `DESC_THRESHOLD`, old model against new.

Run from `phsar/`, twice:
    PYTHONPATH=. ../.venv/bin/python ../.claude/skills/remeasure-embeddings/desc_threshold.py export DIR
        BEFORE the re-embed — saves the old model's anime and media vectors to DIR.
    PYTHONPATH=. ../.venv/bin/python ../.claude/skills/remeasure-embeddings/desc_threshold.py compare DIR
        AFTER it — reads the new vectors from the database.

Population: the pairs the title+desc rule decides — studios overlap, title score in
[TITLE_FLOOR_FOR_DESC, TITLE_ALONE_THRESHOLD).
- Negatives: catalogue anime pairs. A curated catalogue holds distinct anime by the admin's
  past merges, so none of them should flag.
- Positives: main-story media pairs inside one anime — the shape of a duplicate a scrape
  would save twice ("Dr. Stone" vs "Dr. Stone: New World").
"""
import asyncio
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sqlalchemy import func, select

from app.core.db import async_session_maker
from app.models.anime_search import AnimeSearch
from app.models.media import MAIN_STORY_RELATIONS, Media
from app.models.media_search import MediaSearch
from app.models.media_studio import MediaStudio
from app.models.merge_candidate import MergeCandidate
from app.services.merge_detection_service import (
    DESC_THRESHOLD,
    TITLE_ALONE_THRESHOLD,
    TITLE_FLOOR_FOR_DESC,
    _title_score,
    merge_candidate_dao,
    normalize_title,
)
from app.services.vector_embedding_service import cosine_similarity

THRESHOLDS = np.round(np.arange(0.80, 0.98, 0.01), 2)


def write(path: Path, rows) -> None:
    with open(path, "w", newline="") as f:
        csv.writer(f).writerows([row_id, json.dumps([float(x) for x in vec])] for row_id, vec in rows)


async def export(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    async with async_session_maker() as s:
        for name, stmt in (
            ("anime", select(AnimeSearch.anime_id, AnimeSearch.description_embedding)),
            ("media", select(MediaSearch.media_id, MediaSearch.description_embedding)),
        ):
            write(out / f"{name}.csv", (await s.execute(stmt)).all())
    print(f"exported to {out}")


def load(path: Path) -> dict[int, list[float]]:
    return {int(i): json.loads(v) for i, v in csv.reader(open(path))}


def in_band(a: str, b: str) -> float | None:
    t = _title_score(normalize_title(a), normalize_title(b))
    return t if TITLE_FLOOR_FOR_DESC <= t < TITLE_ALONE_THRESHOLD else None


async def compare(old_dir: Path):
    old_anime, old_media = load(old_dir / "anime.csv"), load(old_dir / "media.csv")
    async with async_session_maker() as s:
        catalogue = await merge_candidate_dao.get_anime_for_detection(s)
        verdicts = {(c.anime_a_id, c.anime_b_id): c.status.value for c in (await s.execute(select(MergeCandidate))).scalars()}
        media = (await s.execute(
            select(Media.id, Media.anime_id, Media.title, MediaSearch.description_embedding,
                   func.array_agg(MediaStudio.studio_id))
            .join(MediaSearch, MediaSearch.media_id == Media.id)
            .outerjoin(MediaStudio, MediaStudio.media_id == Media.id)
            .where(Media.relation_type.in_(MAIN_STORY_RELATIONS), Media.description != "")
            .group_by(Media.id, MediaSearch.description_embedding)
        )).all()

    negatives = []
    for i, a in enumerate(catalogue):
        for b in catalogue[i + 1:]:
            if (a.studios and not a.studios.isdisjoint(b.studios) and a.description_embedding is not None
                    and b.description_embedding is not None and a.id in old_anime and b.id in old_anime
                    and in_band(a.title, b.title) is not None):
                negatives.append((cosine_similarity(old_anime[a.id], old_anime[b.id]),
                                  cosine_similarity(a.description_embedding, b.description_embedding),
                                  a.title, b.title, verdicts.get((min(a.id, b.id), max(a.id, b.id)))))
    by_anime = defaultdict(list)
    for mid, aid, title, vec, studios in media:
        by_anime[aid].append((mid, title, vec, {x for x in studios if x}))
    positives = []
    for rows in by_anime.values():
        for i, (ma, ta, ea, sa) in enumerate(rows):
            for mb, tb, eb, sb in rows[i + 1:]:
                if not sa.isdisjoint(sb) and ma in old_media and mb in old_media and in_band(ta, tb) is not None:
                    positives.append((cosine_similarity(old_media[ma], old_media[mb]), cosine_similarity(ea, eb), ta, tb))

    old_n, new_n = (np.array([p[k] for p in negatives]) for k in (0, 1))
    old_p, new_p = (np.array([p[k] for p in positives]) for k in (0, 1))
    print(f"{len(negatives)} negative pairs, {len(positives)} positive pairs")
    print(f"old model at the current DESC_THRESHOLD ({DESC_THRESHOLD}): "
          f"flags {int((old_n >= DESC_THRESHOLD).sum())} negatives, recall {float((old_p >= DESC_THRESHOLD).mean()):.2f}")
    print("new model:")
    for th in THRESHOLDS:
        print(f"  >= {th:.2f}: flags {int((new_n >= th).sum()):3d} negatives, recall {float((new_p >= th).mean()):.2f}")
    print("\nnearest negatives under the new model:")
    for old, new, a, b, verdict in sorted(negatives, key=lambda p: -p[1])[:15]:
        print(f"  new {new:.3f} old {old:.3f} {verdict or '':<10} {a[:32]!r} ~ {b[:32]!r}")


if __name__ == "__main__":
    mode, folder = sys.argv[1], Path(sys.argv[2])
    asyncio.run(export(folder) if mode == "export" else compare(folder))
