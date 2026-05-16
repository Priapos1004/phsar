"""Re-classify every Anime's media via the two-pass relation classifier.

Runs at lifespan startup (gated by `settings.RELATION_BACKFILL_ON_STARTUP`).
Idempotent: subsequent restarts find no changes and exit without touching
the catalog.

For each anime:
1. Load media + each media's `relation_edges` sidecar.
2. Any media with empty sidecar edges → lazily fetch
   `/anime/{mal_id}/relations` from MAL and populate. One MAL hit per
   stale media; the per-second rate limit caps the cold-start cost.
3. Build (nodes, edges) from media columns + sidecars.
4. Run the classifier; diff against current `Media.relation_type`.
5. If the canonical anchor changed, also rewrite `Anime.mal_id` /
   `title` / `name_eng` / `name_jap` from the new anchor media and
   regenerate the anime embedding (the embedding combines title fields).

`dry_run=True` walks the same paths but only logs the would-change rows.
Use this during the audit pause between step 5 and step 6 (see the plan)
to validate the new classifier against real catalog data before flipping
on writes.
"""

import logging
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.anime import Anime
from app.models.media import Media, RelationType
from app.models.media_relation_edges import MediaRelationEdges
from app.services.jikan_scraper import JikanScraper, parse_relation_edges
from app.services.relation_classifier import (
    classify_anime_relations,
    pick_anchor,
)
from app.services.vector_embedding_service import regenerate_anime_embedding

logger = logging.getLogger(__name__)


class BackfillDiff(TypedDict):
    anime_id: int
    anime_title: str
    reclassified: list[tuple[int, str, str]]  # (mal_id, old_rt, new_rt)
    anchor_changed: bool
    old_anchor_mal_id: int
    new_anchor_mal_id: int


class BackfillSummary(TypedDict):
    anime_scanned: int
    anime_changed: int
    media_reclassified: int
    anchor_changes: int
    diffs: list[BackfillDiff]


def _media_to_node(media: Media) -> dict:
    return {
        "media_type": media.media_type.value,
        "aired_from": media.aired_from.isoformat() if media.aired_from else None,
        "episodes": media.episodes,
        "duration_seconds": media.duration_seconds,
        "scored_by": media.scored_by or 0,
    }


async def _ensure_media_edges(
    db: AsyncSession, scraper: JikanScraper, media: Media,
) -> bool:
    """Populate `media.relation_edges.edges` lazily from MAL if empty.
    Returns True if a MAL fetch happened, False if the sidecar was
    already populated. Caller commits."""
    sidecar = media.relation_edges
    if sidecar is None:
        sidecar = MediaRelationEdges(edges=[])
        media.relation_edges = sidecar
    if sidecar.edges:
        return False
    raw = await scraper.fetch_relations(media.mal_id)
    fetched = [[target, rel] for target, rel in parse_relation_edges(raw)]
    sidecar.edges = fetched
    logger.debug(
        "Backfiller fetched %d edges for media mal_id=%s", len(fetched), media.mal_id,
    )
    return True


async def backfill_relations(
    db: AsyncSession, *, dry_run: bool = False,
    anime_ids: set[int] | None = None,
) -> BackfillSummary:
    """Returns a BackfillSummary. Callers commit when `dry_run=False`.
    Pass `anime_ids` to scope the run to a subset (admin re-classify
    endpoint, tests).
    """
    stmt = select(Anime).options(
        selectinload(Anime.media).selectinload(Media.relation_edges),
    )
    if anime_ids is not None:
        stmt = stmt.where(Anime.id.in_(anime_ids))
    all_anime = (await db.execute(stmt)).scalars().all()

    summary: BackfillSummary = {
        "anime_scanned": len(all_anime),
        "anime_changed": 0,
        "media_reclassified": 0,
        "anchor_changes": 0,
        "diffs": [],
    }

    async with JikanScraper() as scraper:
        for anime in all_anime:
            if not anime.media:
                continue

            fetched_any = False
            for media in anime.media:
                if await _ensure_media_edges(db, scraper, media):
                    fetched_any = True

            nodes = {m.mal_id: _media_to_node(m) for m in anime.media}
            # Sidecar edges can point outside this anime's media set
            # (cross-links to media that now lives under a different
            # anime, or stale targets MAL has since reorganized). The
            # classifier requires both endpoints in `nodes`, so filter
            # dangling targets out — same discipline as
            # `jikan_scraper.search_title` applies on its own output.
            graph_ids = set(nodes.keys())
            edges: list[tuple[int, int, str]] = []
            for media in anime.media:
                for target_mal_id, rel in media.relation_edges.edges:
                    if target_mal_id in graph_ids:
                        edges.append((media.mal_id, target_mal_id, rel))

            classifications = classify_anime_relations(nodes, edges)
            new_anchor_mal_id = pick_anchor(nodes)

            current_by_mal = {m.mal_id: m for m in anime.media}
            reclassified: list[tuple[int, str, str]] = []
            for mal_id, new_rt in classifications.items():
                old_rt = current_by_mal[mal_id].relation_type.value
                if old_rt != new_rt:
                    reclassified.append((mal_id, old_rt, new_rt))

            anchor_changed = new_anchor_mal_id != anime.mal_id

            if not reclassified and not anchor_changed:
                continue

            summary["anime_changed"] += 1
            summary["media_reclassified"] += len(reclassified)
            if anchor_changed:
                summary["anchor_changes"] += 1
            summary["diffs"].append({
                "anime_id": anime.id,
                "anime_title": anime.title,
                "reclassified": reclassified,
                "anchor_changed": anchor_changed,
                "old_anchor_mal_id": anime.mal_id,
                "new_anchor_mal_id": new_anchor_mal_id,
            })

            logger.info(
                "Backfiller %s: anime id=%d %r — %d media reclassified, anchor_changed=%s",
                "would change" if dry_run else "changing", anime.id, anime.title,
                len(reclassified), anchor_changed,
            )

            if not dry_run:
                for mal_id, _old, new_rt in reclassified:
                    current_by_mal[mal_id].relation_type = RelationType(new_rt)

                if anchor_changed:
                    new_anchor_media = current_by_mal[new_anchor_mal_id]
                    # Regenerate embedding from the new anchor's title
                    # texts BEFORE mutating the row, so a regen failure
                    # leaves both row and embedding consistent (same
                    # discipline as anime_title_backfiller).
                    await regenerate_anime_embedding(
                        db, anime.id,
                        title_texts=[
                            new_anchor_media.title, new_anchor_media.name_eng,
                            new_anchor_media.name_jap, *(anime.other_names or []),
                        ],
                        description_text=anime.description or "",
                    )
                    anime.mal_id = new_anchor_media.mal_id
                    anime.title = new_anchor_media.title
                    anime.name_eng = new_anchor_media.name_eng
                    anime.name_jap = new_anchor_media.name_jap

            # Per-anime commit so lazily-fetched sidecar edges land
            # incrementally — a crash mid-run doesn't lose hours of
            # MAL pagination, and a follow-up dry-run inherits the
            # already-fetched sidecars instead of re-paying the rate-
            # limited round-trips. In dry_run mode this commits only
            # the sidecar fetches; classification changes were never
            # made.
            should_commit = fetched_any or (
                not dry_run and (reclassified or anchor_changed)
            )
            if should_commit:
                await db.commit()

    if summary["anime_changed"]:
        verb = "would change" if dry_run else "changed"
        logger.info(
            "Relation backfill: %d anime %s, %d media reclassified, %d anchor changes",
            summary["anime_changed"], verb, summary["media_reclassified"],
            summary["anchor_changes"],
        )

    return summary
