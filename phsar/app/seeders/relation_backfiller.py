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
from app.models.media import Media
from app.models.media_relation_edges import MediaRelationEdges
from app.services.anime_relation_service import ReclassifyDiff, reclassify_anime
from app.services.jikan_scraper import JikanScraper, parse_relation_edges

logger = logging.getLogger(__name__)


class BackfillDiff(ReclassifyDiff):
    anime_id: int
    anime_title: str


class BackfillSummary(TypedDict):
    anime_scanned: int
    anime_changed: int
    media_reclassified: int
    anchor_changes: int
    diffs: list[BackfillDiff]


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

            # Per-anime try/except: one bad MAL response or one embedding
            # regen failure mustn't abort the remaining catalog. The
            # rollback wipes uncommitted edge-fetch + reclassify writes
            # for THIS anime only; previous anime committed cleanly.
            try:
                fetched_any = False
                for media in anime.media:
                    if await _ensure_media_edges(db, scraper, media):
                        fetched_any = True

                diff = await reclassify_anime(db, anime, dry_run=dry_run)

                if diff is not None:
                    summary["anime_changed"] += 1
                    summary["media_reclassified"] += len(diff["reclassified"])
                    if diff["anchor_changed"]:
                        summary["anchor_changes"] += 1
                    summary["diffs"].append({
                        "anime_id": anime.id,
                        "anime_title": anime.title,
                        **diff,
                    })
                    logger.info(
                        "Backfiller %s: anime id=%d %r — %d media reclassified, "
                        "anchor_changed=%s, umbrella_drifted=%s",
                        "would change" if dry_run else "changing",
                        anime.id, anime.title,
                        len(diff["reclassified"]),
                        diff["anchor_changed"], diff["umbrella_drifted"],
                    )

                # Per-anime commit so lazily-fetched sidecar edges land
                # incrementally — a crash mid-run doesn't lose hours of
                # MAL pagination, and a follow-up dry-run inherits the
                # already-fetched sidecars instead of re-paying the rate-
                # limited round-trips. In dry_run mode this commits only
                # the sidecar fetches; reclassify never wrote.
                if fetched_any or (not dry_run and diff is not None):
                    await db.commit()
            except Exception:
                await db.rollback()
                logger.exception(
                    "Backfiller failed on anime id=%d %r — skipping",
                    anime.id, anime.title,
                )
                summary.setdefault("anime_failed", 0)
                summary["anime_failed"] += 1

    if summary["anime_changed"]:
        verb = "would change" if dry_run else "changed"
        logger.info(
            "Relation backfill: %d anime %s, %d media reclassified, %d anchor changes",
            summary["anime_changed"], verb, summary["media_reclassified"],
            summary["anchor_changes"],
        )

    return summary
