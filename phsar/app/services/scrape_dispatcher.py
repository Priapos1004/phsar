"""Dispatchers that run inside the JobWorker.

The user_scrape dispatcher fetches the chosen anime + its relations from MAL
and persists them. Progress updates come from a ProgressReporter that opens
its own short-lived session per write, so the navbar bell can poll progress
without waiting for the dispatcher's main transaction to commit.

The update_sweep dispatcher refreshes existing catalog rows: tier-select due
anime, re-fetch each child media via /anime/{id}/full, diff the volatile
fields, and advance the per-anime stability counter. Per-anime commit
boundary so a crash mid-sweep preserves the already-refreshed rows.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.daos.anime_dao import AnimeDAO
from app.exceptions import AnimeNotFoundError
from app.models.anime import Anime
from app.models.anime_freshness import AnimeFreshness
from app.models.job import Job
from app.models.media import Media
from app.models.media_freshness import MediaFreshness
from app.services.jikan_scraper import (
    AIRING_STATUS_CURRENTLY_AIRING,
    JikanScraper,
    parse_mal_datetime,
)
from app.services.progress_reporter import ProgressReporter
from app.services.save_service import save_search_results
from app.services.search_service import handle_search_mal_api_results

logger = logging.getLogger(__name__)

# Counter ceiling — tiered selection only checks `stable < 3`, but capping
# the value keeps the integer bounded and avoids accumulating noise across
# years of sweeps.
_STABLE_COUNT_CAP = 99


async def user_scrape_dispatcher(session: AsyncSession, job: Job) -> dict:
    """BFS everything matching the query and save all results.

    payload: {"query": str}. The 3-candidate search is for query imprecision,
    not user choice — connected candidates dedupe through the shared visited
    set in search_title; unconnected ones each become their own anime row.
    """
    payload = job.payload or {}
    query = payload.get("query")
    if not query:
        raise ValueError(f"user_scrape payload must include query, got {payload!r}")

    progress = ProgressReporter(job.id)

    await progress.update(stage="Fetching", force=True)
    results = await handle_search_mal_api_results(db=session, query=query, progress=progress)
    # search_title raises AnimeNotFoundError when MAL returns zero hits, but
    # if every hit was filtered as Music/PV/CM/Hentai it returns successfully
    # with an empty list — caller still has nothing to save.
    if not results:
        raise AnimeNotFoundError(query)

    media_count = sum(len(r.unconnected_media_list) for r in results)
    await progress.update(stage="Saving", items_total=media_count, items_done=0, force=True)
    await save_search_results(session, results, progress=progress)
    # "Done" while the row is still status='running' is brief — the worker
    # flips to succeeded immediately after this dispatcher returns. Showing
    # it gives the user a clean terminal label instead of a stuck "Saving".
    await progress.update(stage="Done", items_done=media_count, force=True)

    return {
        "anime_count": len(results),
        "media_count": media_count,
    }


async def update_sweep_dispatcher(session: AsyncSession, job: Job) -> dict:
    """Refresh due anime from MAL. Per-anime commit so a crash leaves
    earlier successes durable; per-anime try/except so a single bad
    payload doesn't abort the whole sweep."""
    progress = ProgressReporter(job.id)
    await progress.update(stage="Selecting", force=True)

    anime_list = await AnimeDAO().select_due_for_sweep(
        session, limit=settings.JOBS_SWEEP_MAX_PER_RUN,
    )
    total = len(anime_list)
    await progress.update(
        stage="Refreshing", items_total=total, items_done=0, force=True,
    )

    refreshed = 0
    changed_anime = 0
    async with JikanScraper() as scraper:
        for anime in anime_list:
            try:
                anime_changed = await _refresh_one_anime(session, anime, scraper)
                await session.commit()
            except Exception:
                # One bad anime (404, malformed payload, asyncpg blip) must
                # not abort the whole sweep. The row keeps its old
                # last_checked_at so the next sweep retries it naturally.
                await session.rollback()
                logger.exception(
                    "Sweep failed to refresh anime %s (%s); skipping",
                    anime.id, anime.title,
                )
            else:
                if anime_changed:
                    changed_anime += 1
                refreshed += 1
            await progress.update(items_done=refreshed)

    await progress.update(stage="Done", items_done=refreshed, force=True)
    return {"anime_refreshed": refreshed, "anime_changed": changed_anime}


async def _refresh_one_anime(
    session: AsyncSession, anime: Anime, scraper: JikanScraper,
) -> bool:
    now = datetime.now(timezone.utc)
    anime_changed = False

    for media in anime.media:
        payload = scraper.extract_information(await scraper.refresh_anime(media.mal_id))
        if _apply_media_diff(media, payload):
            anime_changed = True
        if media.freshness is None:
            # Defensive: save_service from 7b creates the sidecar on
            # insert and the migration backfilled existing rows, but a
            # legacy/test row could still be missing one.
            media.freshness = MediaFreshness(last_checked_at=now)
        else:
            media.freshness.last_checked_at = now

    is_currently_airing = any(
        m.airing_status == AIRING_STATUS_CURRENTLY_AIRING for m in anime.media
    )

    if anime.freshness is None:
        anime.freshness = AnimeFreshness(
            last_checked_at=now,
            stable_check_count=0,
        )
    else:
        anime.freshness.last_checked_at = now
        if is_currently_airing or anime_changed:
            anime.freshness.stable_check_count = 0
        else:
            anime.freshness.stable_check_count = min(
                (anime.freshness.stable_check_count or 0) + 1, _STABLE_COUNT_CAP,
            )

    return anime_changed


def _apply_media_diff(media: Media, payload: dict) -> bool:
    """Compare payload against media for the volatile fields and mutate
    in place. Returns True if anything actually changed."""
    changed = False

    new_score = payload.get("score")
    if media.score != new_score:
        media.score = new_score
        changed = True

    # extract_information coerces missing scored_by to 0 already.
    new_scored_by = payload.get("scored_by") or 0
    if media.scored_by != new_scored_by:
        media.scored_by = new_scored_by
        changed = True

    new_episodes = payload.get("episodes")
    if media.episodes != new_episodes:
        if media.episodes is None and new_episodes is not None:
            # We don't auto-bump ratings.episodes_watched: a user with
            # the show on their watchlist may have only watched part.
            # Surface in logs so an admin can investigate scope of the
            # backfill manually.
            logger.info(
                "Episode count revealed for media %s ('%s'): %d",
                media.id, media.title, new_episodes,
            )
        media.episodes = new_episodes
        changed = True

    new_airing_status = payload.get("airing_status")
    # airing_status is NOT NULL — refuse to clobber with a missing value.
    if new_airing_status is not None and media.airing_status != new_airing_status:
        media.airing_status = new_airing_status
        changed = True

    new_aired_to = parse_mal_datetime(payload.get("aired_to"))
    if media.aired_to != new_aired_to:
        media.aired_to = new_aired_to
        changed = True

    return changed
