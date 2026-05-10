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

import asyncio
import logging
import math
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.daos.anime_dao import AnimeDAO
from app.daos.media_dao import MediaDAO
from app.daos.media_unwanted_dao import MediaUnwantedDAO
from app.exceptions import AnimeNotFoundError
from app.models.anime import Anime
from app.models.anime_freshness import AnimeFreshness
from app.models.job import Job
from app.models.media import Media, RelationType
from app.models.media_freshness import MediaFreshness
from app.services.jikan_scraper import (
    AIRING_STATUS_CURRENTLY_AIRING,
    JikanScraper,
    parse_mal_datetime,
)
from app.services.progress_reporter import ProgressReporter
from app.services.save_service import attach_search_result_to_anime, save_search_results
from app.services.search_service import handle_search_mal_api_results
from app.services.spoiler_service import refresh_spoiler_cache_for_all_users
from app.services.unwanted_media_service import create_unwanted_media

logger = logging.getLogger(__name__)

# Counter ceiling — tiered selection only checks `stable < 3`, but capping
# the value keeps the integer bounded and avoids accumulating noise across
# years of sweeps.
_STABLE_COUNT_CAP = 99

# Stability threshold for the (score, scored_by) pair, expressed as the
# absolute change in the weighted score `score * log10(scored_by + 1)`.
# Without this, a single new vote on a million-vote anime (One Piece etc.)
# would reset the counter every night and the show would never stabilize.
# 0.05 is calibrated so a +0.01 score shift at >100k votes counts as a
# real change, while pure vote-count drift on popular anime is treated as
# noise. See compound-doc / commit message for the magnitude analysis.
_SCORE_STABILITY_THRESHOLD = 0.05


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
    """Two commits per anime: step 1 (field-diff + MediaFreshness) is
    always durable; step 2 (probe + AnimeFreshness) only commits on
    success. A probe failure leaves AnimeFreshness untouched so the
    tier query re-selects on the next sweep — without that split, a
    transient MAL outage during BFS would silently lose the
    announcement window for 7+ days."""
    progress = ProgressReporter(job.id)
    await progress.update(stage="Selecting", force=True)

    anime_list = await AnimeDAO().select_due_for_sweep(
        session, limit=settings.JOBS_SWEEP_MAX_PER_RUN,
    )
    total = len(anime_list)
    await progress.update(
        stage="Refreshing", items_total=total, items_done=0, force=True,
    )

    media_ids, anime_ids, unwanted_ids = await asyncio.gather(
        MediaDAO().get_all_mal_ids(session),
        AnimeDAO().get_all_mal_ids(session),
        MediaUnwantedDAO().get_all_mal_ids(session),
    )
    exclusions: set[int] = set(media_ids) | set(anime_ids) | set(unwanted_ids)

    refreshed = 0
    changed_anime = 0
    probe_succeeded = 0
    probe_failed = 0
    sweep_added_media = False
    async with JikanScraper() as scraper:
        for anime in anime_list:
            step1 = await _try_step1_refresh(session, anime, scraper)
            if step1 is None:
                await progress.update(items_done=refreshed)
                continue
            anime_changed, raw_payloads, is_currently_airing = step1

            if _qualifies_for_relations_probe(anime, is_currently_airing):
                await progress.update(stage="Probing relations")
                probe_added = await _try_step2_probe(
                    session, anime, raw_payloads, exclusions, scraper,
                )
                if probe_added is None:
                    probe_failed += 1
                    await progress.update(items_done=refreshed)
                    continue
                if probe_added:
                    sweep_added_media = True
                probe_succeeded += 1

            _advance_anime_freshness(anime, anime_changed, is_currently_airing)
            await session.commit()
            refreshed += 1
            if anime_changed:
                changed_anime += 1
            await progress.update(items_done=refreshed)

    if sweep_added_media:
        # Per-batch recomputes inside the probe loop would multiply the
        # per-user spoiler-cache cost by anime-count.
        await refresh_spoiler_cache_for_all_users(session)

    await progress.update(stage="Done", items_done=refreshed, force=True)
    return {
        "anime_refreshed": refreshed,
        "anime_changed": changed_anime,
        "probe_succeeded": probe_succeeded,
        "probe_failed": probe_failed,
    }


async def _try_step1_refresh(
    session: AsyncSession, anime: Anime, scraper: JikanScraper,
) -> tuple[bool, dict[int, dict], bool] | None:
    """Step 1 wrapper: refresh + commit, or rollback + None on failure.
    Always commits durably so a worker crash later in the sweep can't
    take the field-diff work down with it, and a single bad MAL response
    fails *that* anime only without aborting the loop."""
    try:
        result = await _refresh_one_anime(session, anime, scraper)
        await session.commit()
        return result
    except Exception:
        await session.rollback()
        logger.exception(
            "Sweep failed to refresh anime %s (%s); skipping",
            anime.id, anime.title,
        )
        return None


async def _try_step2_probe(
    session: AsyncSession,
    anime: Anime,
    raw_payloads: dict[int, dict],
    exclusions: set[int],
    scraper: JikanScraper,
) -> bool | None:
    """Step 2 wrapper: relations probe + return whether new media landed,
    or None on failure (rolls back, leaves AnimeFreshness untouched so
    the next sweep retries this anime cleanly)."""
    try:
        return await _probe_relations_for_anime(
            session, anime, raw_payloads, exclusions, scraper,
        )
    except Exception:
        await session.rollback()
        logger.exception(
            "Relations probe failed for anime %s (%s); field-diff "
            "preserved, AnimeFreshness left unchanged so next sweep retries",
            anime.id, anime.title,
        )
        return None


async def _refresh_one_anime(
    session: AsyncSession, anime: Anime, scraper: JikanScraper,
) -> tuple[bool, dict[int, dict], bool]:
    """AnimeFreshness is intentionally NOT touched here — the dispatcher
    advances it after a successful probe so a failed probe can leave
    last_checked_at unchanged and force re-selection next sweep."""
    now = datetime.now(timezone.utc)
    anime_changed = False
    raw_payloads: dict[int, dict] = {}

    for media in anime.media:
        raw = await scraper.refresh_anime(media.mal_id)
        raw_payloads[media.mal_id] = raw
        payload = scraper.extract_information(raw)
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
    return anime_changed, raw_payloads, is_currently_airing


def _advance_anime_freshness(
    anime: Anime, anime_changed: bool, is_currently_airing: bool,
) -> None:
    """Skipping this call after a probe failure keeps the anime in tier
    3/4 for the next sweep — the tier query reads last_checked_at."""
    now = datetime.now(timezone.utc)
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


def _qualifies_for_relations_probe(anime: Anime, is_currently_airing: bool) -> bool:
    """Probe relations only on tier 3 + tier 4 anime. Tier 1 (currently
    airing) is re-checked daily so a sequel surfaces within a day
    anyway; tier 2 (stable_check_count < 3) is the brand-new-anime
    cohort where there's no announcement to discover."""
    if is_currently_airing:
        return False
    stable = anime.freshness.stable_check_count if anime.freshness else 0
    return (stable or 0) >= 3


async def _probe_relations_for_anime(
    session: AsyncSession,
    anime: Anime,
    raw_payloads: dict[int, dict],
    exclusions: set[int],
    scraper: JikanScraper,
) -> bool:
    """For each Main media on the parent anime, walk its MAL relation graph
    via `JikanScraper.search_title` seeded by the media's mal_id (skipping
    the title-fuzzy `q=` step that would otherwise pull in unrelated top-3
    matches). Newly-discovered media land on the existing parent anime via
    `attach_search_result_to_anime`. Disjoint sub-graphs (e.g. Vigilante
    branch off BNHA) get reached because each main media is seeded in its
    own BFS pass with fresh `visited_ids` — `is_main_story=False` nodes
    that wouldn't expand under the BNHA seed get to lead their own walk.

    `exclusions` is mutated in place: every newly-saved mal_id is added so
    later seeds in the same sweep skip re-saving it."""
    main_mal_ids = [m.mal_id for m in anime.media if m.relation_type == RelationType.Main]
    saved_anything = False
    for seed_mal_id in main_mal_ids:
        try:
            relations_list, all_info, unwanted_media = await scraper.search_title(
                title=None,
                excluded_mal_ids=exclusions,
                seed_mal_id=seed_mal_id,
                seed_payload=raw_payloads.get(seed_mal_id),
            )
        except AnimeNotFoundError:
            logger.warning(
                "Probe seed mal_id=%d for anime %s disappeared from MAL; skipping seed",
                seed_mal_id, anime.title,
            )
            continue

        if unwanted_media:
            # No inner try/except: a flush() failure here (IntegrityError,
            # connection drop) leaves the session in PendingRollbackError
            # state, and swallowing it would surface as a confusing
            # cascade in the next attach_search_result_to_anime call.
            # Let it propagate to the outer probe handler, which rolls
            # back step 2 only and leaves AnimeFreshness untouched so
            # the next sweep retries this anime cleanly.
            await create_unwanted_media(session, unwanted_media)
            # Mark unwanted mal_ids as excluded so the next main's BFS
            # skips them instead of re-fetching only to re-discard.
            for mal_id, _title, _reason in unwanted_media:
                exclusions.add(mal_id)

        for graph, _cross_links in relations_list:
            saved_count = await attach_search_result_to_anime(
                session, anime, graph, all_info,
            )
            if saved_count:
                saved_anything = True
            for mal_id in graph:
                exclusions.add(mal_id)

    return saved_anything


def _weighted_score(score: float | None, scored_by: int | None) -> float | None:
    """`score * log10(scored_by + 1)` — same formula used by the search
    ranking helpers (anime_dao / media_dao). Returns None when either
    side is missing so the caller can treat absent-vs-present as a
    structural change instead of comparing 0 to None."""
    if score is None or not scored_by:
        return None
    return score * math.log10(scored_by + 1)


def _apply_media_diff(media: Media, payload: dict) -> bool:
    """Compare payload against media for the volatile fields and mutate
    in place. Returns True if anything *meaningfully* changed (i.e.
    enough that the per-anime stability counter should reset)."""
    changed = False

    # +1 vote on a 5M-vote anime is meaningless drift — use the weighted
    # formula and only reset stability when the delta crosses
    # _SCORE_STABILITY_THRESHOLD. Skip the write entirely if scored_by is
    # falsy: extract_information coerces MAL's None to 0 for the not-null
    # insert column, so a 0 here means the refresh response omitted the
    # field, and overwriting a populated count would be silent data loss.
    new_score = payload.get("score")
    new_scored_by = payload.get("scored_by")
    if new_scored_by:
        old_weighted = _weighted_score(media.score, media.scored_by)
        new_weighted = _weighted_score(new_score, new_scored_by)
        media.score = new_score
        media.scored_by = new_scored_by
        if (old_weighted is None) != (new_weighted is None):
            # First votes coming in (score=None → 8.0, or scored_by 0 → N) is
            # a structural transition, not noise.
            changed = True
        elif old_weighted is not None and new_weighted is not None:
            if abs(new_weighted - old_weighted) >= _SCORE_STABILITY_THRESHOLD:
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
