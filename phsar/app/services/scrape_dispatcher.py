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
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.daos.anime_dao import AnimeDAO
from app.daos.genre_dao import GenreDAO
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
from app.models.media_genre import MediaGenre
from app.models.media_relation_edges import MediaRelationEdges
from app.schemas.search_schema import AttachToExistingAction
from app.services.anime_relation_service import (
    reclassify_anime,
    umbrella_diff_to_log_entry,
)
from app.services.jikan_scraper import (
    AIRING_STATUS_CURRENTLY_AIRING,
    JikanScraper,
    parse_mal_datetime,
    parse_relation_edges,
)
from app.services.merge_detection_service import (
    detect_merge_candidates,
    find_cross_anime_relation_pairs,
)
from app.services.progress_reporter import ProgressReporter
from app.services.relation_classifier import classify_and_stamp
from app.services.save_service import attach_search_result_to_anime, save_search_results
from app.services.search_service import handle_search_mal_api_results
from app.services.spoiler_service import refresh_spoiler_cache_for_all_users
from app.services.unwanted_media_service import create_unwanted_media
from app.services.vector_embedding_service import regenerate_media_embedding

logger = logging.getLogger(__name__)

# Counter ceiling — tiered selection only checks `stable < 3`, but capping
# the value keeps the integer bounded and avoids accumulating noise across
# years of sweeps.
_STABLE_COUNT_CAP = 99


class RefreshResult(NamedTuple):
    volatile_changed: bool  # gates stability-counter reset
    raw_payloads: dict[int, dict]
    is_currently_airing: bool
    metadata_changed_count: int  # media rows with non-volatile field drift
    # Full ReclassifyDiff (or None if nothing drifted) — bool umbrella-
    # drift is derivable from this, so the NamedTuple doesn't carry both.
    umbrella_diff: dict | None
    genre_drifts: list[dict]  # per-media DriftReports (genre); empty if no drift
    studio_drifts: list[dict]  # per-media DriftReports (studio); empty if no drift
    # Per-media diff entries already annotated with anime context so the
    # dispatcher just extends its log — no post-hoc mutation needed.
    media_changes: list[dict]


# Diff classification for the genre/studio drift detector. Pure-addition
# of *known* tags is the only branch that auto-applies — every other
# kind surfaces to result_summary so admins can review without the
# sweep silently rewriting M2M tables on noise (or worse, on a MAL bug).
_DRIFT_ADDITIONS_APPLIED = "additions_applied"
_DRIFT_ADDITIONS_UNKNOWN = "additions_unknown"  # genre only — unknown tag in our table
_DRIFT_REMOVAL_OR_REPLACEMENT = "removal_or_replacement"
_DRIFT_ANY_CHANGE = "any_change"  # studio bucket — every change just logs

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
    anime_with_dynamic_changes = 0
    anime_with_static_changes = 0
    media_with_dynamic_changes = 0
    media_with_static_changes = 0
    umbrella_reclassed = 0
    probe_succeeded = 0
    probe_failed = 0
    sweep_added_media = False
    # Track which existing anime had new media attached so we can re-run
    # merge detection on them at sweep end — a tier-3 anime whose probe
    # pulled in a new sibling franchise (Vigilante-shape) may now bridge
    # to a third anime in the catalog via relation_link, and the save-time
    # detector never sees it because the attach path bypasses
    # save_search_results.
    probe_attached_anime_ids: list[int] = []
    # Step 1 rewrites MediaRelationEdges from the /full payload, so a
    # refresh alone (no new media) can surface a fresh relation_link
    # signal. Broader scope than probe-attached.
    sidecar_touched_anime_ids: list[int] = []
    # v2 result_summary: every changed media row + every umbrella drift,
    # carrying old → new for each touched field. The detail page renders
    # off this; the Jobs Log row counts off `counters` below.
    media_changes_log: list[dict] = []
    anime_umbrella_changes_log: list[dict] = []
    async with JikanScraper() as scraper:
        for anime in anime_list:
            step1 = await _try_step1_refresh(session, anime, scraper)
            if step1 is None:
                await progress.update(items_done=refreshed)
                continue
            sidecar_touched_anime_ids.append(anime.id)

            if _qualifies_for_relations_probe(anime, step1.is_currently_airing):
                await progress.update(stage="Probing relations")
                probe_added = await _try_step2_probe(
                    session, anime, step1.raw_payloads, exclusions, scraper,
                )
                if probe_added is None:
                    probe_failed += 1
                    await progress.update(items_done=refreshed)
                    continue
                if probe_added:
                    sweep_added_media = True
                    probe_attached_anime_ids.append(anime.id)
                probe_succeeded += 1

            _advance_anime_freshness(
                anime, step1.volatile_changed, step1.is_currently_airing,
            )
            await session.commit()
            refreshed += 1
            anime_had_dynamic = False
            anime_had_static = False
            for entry in step1.media_changes:
                media_changes_log.append(entry)
                if entry["dynamic"]:
                    media_with_dynamic_changes += 1
                    anime_had_dynamic = True
                if entry["static"]:
                    media_with_static_changes += 1
                    anime_had_static = True
            if anime_had_dynamic:
                anime_with_dynamic_changes += 1
            if anime_had_static:
                anime_with_static_changes += 1
            if step1.umbrella_diff and step1.umbrella_diff["umbrella_drifted"]:
                umbrella_reclassed += 1
                anime_umbrella_changes_log.append(
                    umbrella_diff_to_log_entry(anime, step1.umbrella_diff),
                )
            await progress.update(items_done=refreshed)

    # Re-run merge detection at sweep end: title_studio/title_desc against
    # probe-attached anime (mirrors save-time detection that the attach
    # path bypasses), plus relation_link from sidecars across the broader
    # sidecar-touched scope. Coalesced into one call so the spoiler refresh
    # + merge detection share the maintenance window. Per-anime catalog
    # work has already committed, so a detection failure shouldn't fail
    # the whole sweep — soft-warn into result_summary.
    merge_detect_failed = False
    cross_link_pairs: list[tuple[int, int]] = []
    if sidecar_touched_anime_ids:
        try:
            cross_link_pairs = await find_cross_anime_relation_pairs(
                session, scope_anime_ids=sidecar_touched_anime_ids,
            )
        except Exception:
            logger.exception("Post-sweep cross-link query failed")
            merge_detect_failed = True
    if probe_attached_anime_ids or cross_link_pairs:
        try:
            await detect_merge_candidates(
                session,
                new_anime_ids=probe_attached_anime_ids,
                cross_link_pairs=cross_link_pairs,
            )
            await session.commit()
        except Exception:
            logger.exception("Post-sweep merge detection failed")
            merge_detect_failed = True
            await session.rollback()

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
        "counters": {
            "anime_refreshed": refreshed,
            "anime_with_dynamic_changes": anime_with_dynamic_changes,
            "anime_with_static_changes": anime_with_static_changes,
            "media_with_dynamic_changes": media_with_dynamic_changes,
            "media_with_static_changes": media_with_static_changes,
            "umbrella_reclassed": umbrella_reclassed,
            "probe_succeeded": probe_succeeded,
            "probe_failed": probe_failed,
            "probe_attached_anime_count": len(probe_attached_anime_ids),
        },
        "media_changes": media_changes_log,
        "anime_umbrella_changes": anime_umbrella_changes_log,
        "merge_detect_failed": merge_detect_failed,
        "cache_recompute_failed": cache_recompute_failed,
    }


async def _try_step1_refresh(
    session: AsyncSession, anime: Anime, scraper: JikanScraper,
) -> RefreshResult | None:
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
) -> RefreshResult:
    """AnimeFreshness is intentionally NOT touched here — the dispatcher
    advances it after a successful probe so a failed probe can leave
    last_checked_at unchanged and force re-selection next sweep.

    Two diff buckets:
    - volatile (score/scored_by/episodes/airing_status/aired_to) gates the
      per-anime stability counter (`volatile_changed`)
    - metadata (description/title/name_*/cover_image/age_rating/...) does
      NOT reset stability — a late-arriving English title shouldn't kick
      a settled tier-4 anime back to weekly polling — but does fire
      embedding regen + umbrella reclassification so search stays current.
    """
    now = datetime.now(timezone.utc)
    volatile_changed = False
    metadata_changed_count = 0
    raw_payloads: dict[int, dict] = {}
    genre_drifts: list[dict] = []
    studio_drifts: list[dict] = []
    media_changes: list[dict] = []

    for media in anime.media:
        raw = await scraper.refresh_anime(media.mal_id)
        raw_payloads[media.mal_id] = raw
        payload = scraper.extract_information(raw)
        dynamic: list[dict] = []
        static: list[dict] = []
        if _apply_media_diff(media, payload, diff_sink=dynamic):
            volatile_changed = True

        metadata_drift = await _apply_metadata_diff(
            session, media, payload, diff_sink=static,
        )
        if metadata_drift:
            metadata_changed_count += 1

        genre_drift = await _apply_genre_diff(session, media, payload)
        if genre_drift:
            genre_drifts.append(genre_drift)

        studio_drift = await _apply_studio_diff(media, payload)
        if studio_drift:
            studio_drifts.append(studio_drift)

        if dynamic or static or genre_drift or studio_drift:
            # Carry name_eng / name_jap alongside the romaji title so the
            # admin detail page can respect the viewer's name_language
            # setting (same convention as the rest of the UI) without a
            # round-trip back to /anime or /media.
            media_changes.append({
                "anime_id": anime.id,
                "anime_uuid": str(anime.uuid),
                "anime_title": anime.title,
                "anime_name_eng": anime.name_eng,
                "anime_name_jap": anime.name_jap,
                "media_id": media.id,
                "media_uuid": str(media.uuid),
                "media_mal_id": media.mal_id,
                "media_title": media.title,
                "media_name_eng": media.name_eng,
                "media_name_jap": media.name_jap,
                "media_relation_type": media.relation_type.value,
                "dynamic": dynamic,
                "static": static,
                "genre_drift": genre_drift,
                "studio_drift": studio_drift,
            })

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
        # volatile_changed — edge churn is structural metadata, not the
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

    # Umbrella reclassification after per-media diffs: if any anchor-
    # touching field shifted, rewrites the 7 umbrella fields + regenerates
    # AnimeSearch on its own. Cheap when nothing drifted — drift detection
    # is a few in-memory comparisons. Called inside step 1's savepoint so
    # an embedding-regen crash rolls back the per-media writes too.
    umbrella_diff = await reclassify_anime(session, anime)

    is_currently_airing = any(
        m.airing_status == AIRING_STATUS_CURRENTLY_AIRING for m in anime.media
    )
    return RefreshResult(
        volatile_changed=volatile_changed,
        raw_payloads=raw_payloads,
        is_currently_airing=is_currently_airing,
        metadata_changed_count=metadata_changed_count,
        umbrella_diff=umbrella_diff,
        genre_drifts=genre_drifts,
        studio_drifts=studio_drifts,
        media_changes=media_changes,
    )


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


# Fields whose change regenerates the MediaSearch embedding pair.
# `_compute_search_embeddings` mixes title into the description embedding,
# so a title-side change invalidates BOTH embeddings — same reason the
# anime-side reclassifier collapses these into a single regen trigger.
_EMBEDDING_TEXT_FIELDS = ("title", "name_eng", "name_jap", "other_names", "description")

# Fields refreshed but not part of any embedding — pure DB updates.
_METADATA_NONTEXT_FIELDS = ("cover_image", "age_rating", "original_source")


def _jsonable(value: object) -> object:
    """Coerce values into a JSONB-safe shape for the diff sink. Datetime
    is the one type the volatile-field bucket emits that Python's default
    json encoder rejects (the JSONB column's serializer goes through
    `json.dumps`). All other field types in result_summary are already
    primitive/list/dict."""
    if isinstance(value, datetime):
        return value.isoformat()
    return value


async def _apply_metadata_diff(
    session: AsyncSession, media: Media, payload: dict,
    *, diff_sink: list[dict] | None = None,
) -> bool:
    """Refresh non-volatile fields (description, titles, cover, age rating,
    source) from MAL. Regenerates the media's MediaSearch embedding pair
    when any text-bearing field changed. Returns True when something
    landed so the dispatcher can count it.

    Stability counter is intentionally NOT touched — a late-arriving
    English title or a polished synopsis should refresh the row without
    kicking a settled anime back to weekly polling. See `_apply_media_diff`
    for the volatile bucket that *does* gate stability.

    Genre / studio drift is handled separately (next commit) so the M2M
    plumbing stays out of this simple-column path.

    `diff_sink` is the v2 result_summary capture: dispatcher passes a
    list to collect per-field {field, old, new} entries; production
    callers that don't care leave it None.
    """
    text_changed = False
    other_changed = False

    def _capture(field: str, old: object, new: object) -> None:
        if diff_sink is not None:
            diff_sink.append({"field": field, "old": _jsonable(old), "new": _jsonable(new)})

    for field in _EMBEDDING_TEXT_FIELDS:
        new_val = payload.get(field)
        if field == "other_names":
            # MAL doesn't return title_synonyms in a stable order, so
            # compare as a set — without this, a pure reorder would fire
            # the 50-100ms embedding regen on noise. Storage keeps the
            # latest order only when the set actually changed.
            current = list(getattr(media, field) or [])
            new_val = list(new_val or [])
            if set(current) != set(new_val):
                _capture(field, current, new_val)
                setattr(media, field, new_val)
                text_changed = True
            continue
        # Don't clobber a populated value with None — mirrors the volatile
        # bucket's "MAL response omitted the field" guard.
        if new_val is None:
            continue
        current = getattr(media, field)
        if current != new_val:
            _capture(field, current, new_val)
            setattr(media, field, new_val)
            text_changed = True

    for field in _METADATA_NONTEXT_FIELDS:
        new_val = payload.get(field)
        if new_val is None:
            continue
        current = getattr(media, field)
        if current != new_val:
            _capture(field, current, new_val)
            setattr(media, field, new_val)
            other_changed = True

    if text_changed:
        # Same DELETE-then-INSERT discipline as anime-side regen: a new
        # MediaSearch row replaces the old, encode runs before the DELETE
        # so an encode failure leaves the prior embedding intact.
        await regenerate_media_embedding(
            session,
            media.id,
            title_texts=[
                media.title,
                media.name_eng,
                media.name_jap,
                *(media.other_names or []),
            ],
            description_text=media.description or "",
        )

    return text_changed or other_changed


def _emit_drift_report(
    media: Media, field: str, kind: str, old: set[str], new: set[str],
    *, unknown_tags: list[str] | None = None,
) -> dict:
    """Build the plain-dict report (the sweep stashes it directly in
    `result_summary`'s JSONB — no Pydantic round-trip needed) and emit
    the matching WARNING log in one go. Centralized so the per-branch
    callers stay one line each and the log copy stays in sync with the
    report shape.

    `additions_applied` is intentionally not logged — it represents the
    auto-apply path that runs silently; the count surfaces via the
    per-media `media_changes` entry in result_summary v2.
    """
    report = {
        "field": field,
        "media_mal_id": media.mal_id,
        "media_title": media.title,
        "kind": kind,
        "old": sorted(old),
        "new": sorted(new),
        "unknown_tags": unknown_tags or [],
    }
    if kind == _DRIFT_ADDITIONS_UNKNOWN:
        logger.warning(
            "%s drift (unknown additions) on media %s (mal_id=%s): unknown=%s; "
            "skipping all additions until seeder is updated",
            field, media.title, media.mal_id, report["unknown_tags"],
        )
    elif kind in (_DRIFT_REMOVAL_OR_REPLACEMENT, _DRIFT_ANY_CHANGE):
        logger.warning(
            "%s drift on media %s (mal_id=%s): %s → %s",
            field, media.title, media.mal_id, report["old"], report["new"],
        )
    return report


async def _apply_genre_diff(
    session: AsyncSession, media: Media, payload: dict,
) -> dict | None:
    """Detect genre drift between the catalog row and MAL's latest tags.

    Genre rule (matches user agreement):
    - Pure-addition of tags already in our `genre` table → silently
      append the M2M rows. The seeded set is what we believe the genre
      universe is; new known tags are routine MAL backfills (themes
      retroactively applied to old shows are common).
    - Pure-addition that includes an unknown tag → log, do NOT apply
      ANY of them. All-or-nothing: half-applying would mean the next
      admin "what genres did we silently add?" question can't be
      answered from logs alone.
    - Removal or replacement → log, do NOT apply. Genre/theme removals
      from MAL are rare enough to warrant human review.
    """
    current = {mg.genre.name for mg in media.media_genre}
    new = set(payload.get("genres") or [])
    if current == new:
        return None

    removed = current - new
    added = new - current

    if removed:
        return _emit_drift_report(
            media, "genres", _DRIFT_REMOVAL_OR_REPLACEMENT, current, new,
        )

    known = {
        g.name: g for g in await GenreDAO().get_all_by_field(session, "name", list(added))
    }
    unknown = sorted(added - set(known))
    if unknown:
        return _emit_drift_report(
            media, "genres", _DRIFT_ADDITIONS_UNKNOWN, current, new,
            unknown_tags=unknown,
        )

    for name in added:
        session.add(MediaGenre(media_id=media.id, genre_id=known[name].id))
    await session.flush()
    return _emit_drift_report(
        media, "genres", _DRIFT_ADDITIONS_APPLIED, current, new,
    )


async def _apply_studio_diff(media: Media, payload: dict) -> dict | None:
    """Studio drift always logs and never auto-applies — legitimate
    studio additions exist (co-production credits surface after airing,
    outsourced animation studios appear in end credits) but are rare
    enough that surfacing every change for admin review is preferable
    to silently rewriting the M2M on a possible MAL data bug.
    """
    current = {ms.studio.name for ms in media.media_studio}
    new = set(payload.get("studio") or [])
    if current == new:
        return None
    return _emit_drift_report(media, "studios", _DRIFT_ANY_CHANGE, current, new)


def _apply_media_diff(
    media: Media, payload: dict, *, diff_sink: list[dict] | None = None,
) -> bool:
    """Compare payload against media for the volatile fields and mutate
    in place. Returns True if anything *meaningfully* changed (i.e.
    enough that the per-anime stability counter should reset).

    `diff_sink` is the v2 result_summary capture: dispatcher passes a
    list to collect {field, old, new} entries for every WRITE (not just
    stability-resetting ones — admins inspecting the detail page want
    to see microscopic score deltas too). The bool return still gates
    the stability counter.
    """
    changed = False

    def _capture(field: str, old: object, new: object) -> None:
        if diff_sink is not None:
            diff_sink.append({"field": field, "old": _jsonable(old), "new": _jsonable(new)})

    # +1 vote on a 5M-vote anime is meaningless drift — use the weighted
    # formula and only reset stability when the delta crosses
    # _SCORE_STABILITY_THRESHOLD. Skip the write entirely if scored_by is
    # falsy: extract_information coerces MAL's None to 0 for the not-null
    # insert column, so a 0 here means the refresh response omitted the
    # field, and overwriting a populated count would be silent data loss.
    new_score = payload.get("score")
    new_scored_by = payload.get("scored_by")
    if new_scored_by:
        old_score = media.score
        old_scored_by = media.scored_by
        old_weighted = _weighted_score(old_score, old_scored_by)
        new_weighted = _weighted_score(new_score, new_scored_by)
        if old_score != new_score:
            _capture("score", old_score, new_score)
        if old_scored_by != new_scored_by:
            _capture("scored_by", old_scored_by, new_scored_by)
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
        _capture("episodes", media.episodes, new_episodes)
        media.episodes = new_episodes
        changed = True

    new_airing_status = payload.get("airing_status")
    # airing_status is NOT NULL — refuse to clobber with a missing value.
    if new_airing_status is not None and media.airing_status != new_airing_status:
        _capture("airing_status", media.airing_status, new_airing_status)
        media.airing_status = new_airing_status
        changed = True

    new_aired_to = parse_mal_datetime(payload.get("aired_to"))
    if media.aired_to != new_aired_to:
        _capture("aired_to", media.aired_to, new_aired_to)
        media.aired_to = new_aired_to
        changed = True

    return changed
