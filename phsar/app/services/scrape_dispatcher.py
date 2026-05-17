"""user_scrape + update_sweep dispatchers (the catalog-mutation pair).

The user_scrape dispatcher fetches the chosen anime + its relations from MAL
and persists them. Progress updates come from a ProgressReporter that opens
its own short-lived session per write, so the navbar bell can poll progress
without waiting for the dispatcher's main transaction to commit.

The update_sweep dispatcher refreshes existing catalog rows: tier-select due
anime, re-fetch each child media via /anime/{id}/full, diff the volatile
fields, and advance the per-anime stability counter. Per-anime commit
boundary so a crash mid-sweep preserves the already-refreshed rows.

The seasonal_sweep dispatcher lives in its own module
(seasonal_sweep_dispatcher.py) — it doesn't touch any of this file's
helpers and is purely a discovery pass that hands off to user_scrape.
"""

import logging
import math
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.daos.anime_dao import AnimeDAO
from app.daos.media_dao import MediaDAO
from app.daos.media_unwanted_dao import MediaUnwantedDAO
from app.exceptions import (
    AnimeFilteredOutError,
    AnimeNotFoundError,
    MainMediaNotFoundError,
)
from app.models.anime import Anime
from app.models.anime_freshness import AnimeFreshness
from app.models.job import Job
from app.models.media import Media, RelationType
from app.models.media_freshness import MediaFreshness
from app.models.media_relation_edges import MediaRelationEdges
from app.schemas.search_schema import AttachToExistingAction
from app.services.jikan_scraper import (
    AIRING_STATUS_CURRENTLY_AIRING,
    JikanScraper,
    parse_mal_datetime,
    parse_relation_edges,
)
from app.services.progress_reporter import ProgressReporter
from app.services.relation_classifier import classify_and_stamp
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

    payload: {"query": str, "mal_id": int | None}. The 3-candidate search
    is for query imprecision, not user choice — connected candidates dedupe
    through the shared visited set in search_title; unconnected ones each
    become their own anime row. When `mal_id` is set (seasonal sweep
    children), the BFS skips the fuzzy q= lookup and seeds from that id
    directly so unrelated top-3 matches don't slip into the catalog.
    """
    payload = job.payload or {}
    query = payload.get("query")
    seed_mal_id = payload.get("mal_id")
    if not query and seed_mal_id is None:
        raise ValueError(
            f"user_scrape payload must include query or mal_id, got {payload!r}",
        )

    progress = ProgressReporter(job.id)

    await progress.update(stage="Fetching", force=True)
    extended = await handle_search_mal_api_results(
        db=session, query=query, progress=progress, seed_mal_id=seed_mal_id,
    )
    results = extended.search_result_db_list
    attach_actions = extended.attach_actions

    # Two parallel write paths:
    #  - save_search_results: graphs WITH a main story → new Anime rows
    #  - attach_actions: orphan-side-story graphs whose single cross-link
    #    resolves to an existing Anime → new Media rows attached under
    #    that parent (same primitive the 7c freshness probe uses)
    media_count = sum(len(r.unconnected_media_list) for r in results)
    if results:
        await progress.update(
            stage="Saving", items_total=media_count, items_done=0, force=True,
        )
        await save_search_results(session, results, progress=progress)

    attached_count = 0
    if attach_actions:
        await progress.update(stage="Attaching", force=True)
        attached_count = await _route_attach_actions(session, attach_actions)

    if not results and not attached_count:
        # Empty BFS result + no attach happened. Three distinct causes
        # worth surfacing — the cron path's error_message is the only
        # post-mortem record (system jobs don't appear in the bell), so
        # distinguishing them saves the next admin from wondering
        # whether MAL is broken, dropping a PV, or returning a
        # malformed graph.
        if seed_mal_id is not None:
            unwanted = await MediaUnwantedDAO().get_by_mal_id(session, seed_mal_id)
            if unwanted is not None:
                raise AnimeFilteredOutError(unwanted.title, unwanted.reason)
            # Seed found but graph had no main story AND no attachable
            # single cross-link — typically a multi-parent ambiguity or
            # a fully-orphaned side-story the BFS couldn't anchor.
            raise MainMediaNotFoundError([(query or f"mal_id={seed_mal_id}", "?")])
        # Reached only when seed_mal_id is None (handled above).
        # `query` is guaranteed truthy here — the dispatcher entry-check
        # raises ValueError when both are missing.
        raise AnimeNotFoundError(query)

    # "Done" while the row is still status='running' is brief — the worker
    # flips to succeeded immediately after this dispatcher returns. Showing
    # it gives the user a clean terminal label instead of a stuck "Saving".
    await progress.update(stage="Done", items_done=media_count, force=True)

    return {
        "anime_count": len(results),
        "media_count": media_count,
        "attached_count": attached_count,
    }


async def _route_attach_actions(
    session: AsyncSession, attach_actions: list[AttachToExistingAction],
) -> int:
    """Look up each attach action's parent Anime via Media.mal_id and
    call `attach_search_result_to_anime` to materialize the orphan
    graph's media under that parent. Returns total Media rows attached.

    The lookup goes through Media.mal_id because the cross-link signal
    carries the *media* mal_id (any media in the parent franchise; not
    necessarily the parent anime's primary mal_id)."""
    anime_dao = AnimeDAO()
    attached_total = 0
    for action in attach_actions:
        parent = await anime_dao.get_by_media_mal_id_with_media(
            session, action.target_mal_id,
        )
        if parent is None:
            # Race: cross-link mal_id was in catalog at BFS time but
            # disappeared before we got here (merge candidate completed,
            # delete, etc.). Log and skip; next sweep will re-evaluate.
            logger.warning(
                "Attach target mal_id=%s no longer in catalog; skipping",
                action.target_mal_id,
            )
            continue
        attached_total += await attach_search_result_to_anime(
            session, parent, action.related_anime_graph, action.all_info,
            edges=action.edges,
        )
    return attached_total


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

    # AsyncSession is not concurrency-safe; all three queries share `session`.
    media_ids = await MediaDAO().get_all_mal_ids(session)
    anime_ids = await AnimeDAO().get_all_mal_ids(session)
    unwanted_ids = await MediaUnwantedDAO().get_all_mal_ids(session)
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

    cache_recompute_failed = False
    if sweep_added_media:
        # Per-batch recomputes inside the probe loop would multiply the
        # per-user spoiler-cache cost by anime-count.
        # The per-anime catalog work already committed by this point, so a
        # cache failure here shouldn't mark the whole sweep failed in the bell
        # — surface it as a soft warning on the success summary instead.
        try:
            await refresh_spoiler_cache_for_all_users(session)
        except Exception:
            logger.exception("Spoiler cache recompute failed after sweep")
            cache_recompute_failed = True

    await progress.update(stage="Done", items_done=refreshed, force=True)
    return {
        "anime_refreshed": refreshed,
        "anime_changed": changed_anime,
        "probe_succeeded": probe_succeeded,
        "probe_failed": probe_failed,
        "cache_recompute_failed": cache_recompute_failed,
    }


async def _try_step1_refresh(
    session: AsyncSession, anime: Anime, scraper: JikanScraper,
) -> tuple[bool, dict[int, dict], bool] | None:
    """Step 1 wrapper: refresh + commit, or rollback + None on failure.
    Always commits durably so a worker crash later in the sweep can't
    take the field-diff work down with it, and a single bad MAL response
    fails *that* anime only without aborting the loop.

    Uses SAVEPOINT (`begin_nested`) instead of session-level rollback —
    `session.rollback()` would expire every eager-loaded instance the
    outer `select_due_for_sweep` query preloaded, and the next anime's
    `media` / `relation_edges` access would then trip `lazy="raise"`
    and abort the whole sweep. Identifiers captured pre-savepoint so
    the logger never touches an attribute the rollback path might have
    expired (same MissingGreenlet trap that hit relation_backfiller).
    """
    anime_id_for_log = anime.id
    anime_title_for_log = anime.title
    try:
        async with session.begin_nested():
            result = await _refresh_one_anime(session, anime, scraper)
        await session.commit()
        return result
    except Exception:
        logger.exception(
            "Sweep failed to refresh anime %s (%s); skipping",
            anime_id_for_log, anime_title_for_log,
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
    or None on failure (savepoint-rolls-back, leaves AnimeFreshness
    untouched so the next sweep retries this anime cleanly). Outer
    transaction stays alive — caller commits step2 writes alongside
    `_advance_anime_freshness` once both succeed.

    See `_try_step1_refresh` for the savepoint + pre-capture rationale.
    """
    anime_id_for_log = anime.id
    anime_title_for_log = anime.title
    try:
        async with session.begin_nested():
            return await _probe_relations_for_anime(
                session, anime, raw_payloads, exclusions, scraper,
            )
    except Exception:
        logger.exception(
            "Relations probe failed for anime %s (%s); field-diff "
            "preserved, AnimeFreshness left unchanged so next sweep retries",
            anime_id_for_log, anime_title_for_log,
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

        # `/anime/{id}/full` bundles the relations block; refresh the
        # sidecar so bridge edges land for pre-v0.14.1 rows scraped
        # under the dangling-edge filter, and so MAL adding a new
        # sequel/alt-version flows into the catalog over the nightly
        # sweep instead of needing a manual re-scrape. Not counted as
        # anime_changed — edge churn is structural metadata, not the
        # volatile canonical fields the stable counter tracks.
        fresh_edges: list[list[int | str]] = [
            [t, r] for t, r in parse_relation_edges(raw.get("relations") or [])
        ]
        if media.relation_edges is None:
            media.relation_edges = MediaRelationEdges(
                edges=fresh_edges, last_fetched_at=now,
            )
        elif (
            media.relation_edges.edges != fresh_edges
            or media.relation_edges.last_fetched_at is None
        ):
            # Stamp + write only when something actually changed, or
            # when the timestamp is missing (defensive — backfiller +
            # migration should have stamped everything, but a sidecar
            # created without the stamp shouldn't keep escaping the
            # gate). Steady-state empty-relations rows whose edges
            # echo back unchanged skip the UPDATE entirely.
            media.relation_edges.edges = fresh_edges
            media.relation_edges.last_fetched_at = now

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

        for graph, edges, _cross_links in relations_list:
            # Probe path doesn't pass through search_mal_api, so stamp
            # relation_type here before attach reads it.
            classify_and_stamp(graph, edges, all_info)
            saved_count = await attach_search_result_to_anime(
                session, anime, graph, all_info, edges=edges,
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
    # Skip when MAL omitted the field on a populated row — mirrors the
    # scored_by guard above. extract_information returns None when the
    # /full response leaves episodes off (observed transient behavior);
    # writing that back would silently null a populated count and reset
    # stability. Allow None → value (the reveal direction) and
    # value → value (legitimate updates).
    if new_episodes is not None and media.episodes != new_episodes:
        if media.episodes is None:
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
