"""Backfill SplitCandidate rows for anime with disjoint substance-passing
chains under one row (the BNHA→Vigilante / Toaru Index→Railgun shape).

Two entry points:
- `detect_split_candidates_for_anime` — per-anime helper called from
  inside relation_backfiller's existing SAVEPOINT loop so reclassify +
  split-detect commit atomically per row.
- `backfill_split_candidates` — standalone seeder that walks every
  Anime in the catalog. Used by lifespan + the admin re-trigger
  endpoint. Caller commits.

Both call the pure `find_disjoint_franchises` function on the same
(nodes, edges) shape the classifier already understands — see
[app/services/relation_classifier.py].
"""

import logging
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.split_candidate_dao import SplitCandidateDAO
from app.models.anime import Anime
from app.models.media import Media
from app.services.anime_relation_service import build_classifier_graph
from app.services.relation_classifier import (
    classify_anime_relations,
    find_disjoint_franchises,
)

logger = logging.getLogger(__name__)

split_candidate_dao = SplitCandidateDAO()


class SplitBackfillSummary(TypedDict):
    anime_scanned: int
    candidates_inserted: int
    candidates_unchanged: int


async def detect_split_candidates_for_anime(
    db: AsyncSession, anime: Anime, detected_by: str,
) -> bool:
    """Run find_disjoint_franchises against the anime's current graph
    state and upsert a SplitCandidate if disjoint chains are detected.
    Returns True if a row was inserted or superseded; False if the
    payload matches an already-pending row (idempotent re-detect) OR no
    contamination was found.

    Requires `anime.media` + each media's `relation_edges` sidecar to be
    loaded by the caller (typical pattern is selectinload during the
    enclosing query). Caller commits.
    """
    if not anime.media:
        return False

    graph, edges = build_classifier_graph(anime.media)
    _, anchor = classify_anime_relations(graph, edges)
    if anchor is None:
        return False

    franchises = find_disjoint_franchises(graph, edges, anchor)
    if not franchises:
        return False

    # Re-shape edge tuples to lists so the JSONB roundtrip is stable
    # (tuples serialize as arrays, deserialize as lists — pre-flattening
    # makes the upsert_pending signature compare deterministic).
    payload = [
        {
            "member_mal_ids": list(f["member_mal_ids"]),
            "substance_member_mal_ids": list(f["substance_member_mal_ids"]),
            "suggested_anchor_mal_id": f["suggested_anchor_mal_id"],
            "bridge_edges": [list(e) for e in f["bridge_edges"]],
        }
        for f in franchises
    ]
    return await split_candidate_dao.upsert_pending(
        db, anime_id=anime.id, clusters=payload, detected_by=detected_by,
    )


async def backfill_split_candidates(
    db: AsyncSession, anime_ids: set[int] | None = None,
) -> SplitBackfillSummary:
    """Walk every Anime (or `anime_ids` subset) and emit SplitCandidates
    for any that contain disjoint substance-passing main chains.

    Used at lifespan startup (after relation_backfiller lands TERMINAL
    sidecars) and by the admin re-trigger endpoint. Pure structural
    detection, no MAL calls — fast even on large catalogs.

    Caller commits. Idempotent: re-running over an unchanged catalog
    inserts zero new rows.
    """
    stmt = select(Anime).options(
        selectinload(Anime.media).selectinload(Media.relation_edges),
    )
    if anime_ids is not None:
        stmt = stmt.where(Anime.id.in_(anime_ids))
    all_anime = (await db.execute(stmt)).scalars().all()

    inserted = 0
    unchanged = 0
    for anime in all_anime:
        if await detect_split_candidates_for_anime(
            db, anime, detected_by="backfill",
        ):
            inserted += 1
        else:
            unchanged += 1

    if inserted:
        logger.info(
            "Split-candidate backfill: %d anime scanned, %d new/updated candidates",
            len(all_anime), inserted,
        )

    return {
        "anime_scanned": len(all_anime),
        "candidates_inserted": inserted,
        "candidates_unchanged": unchanged,
    }
