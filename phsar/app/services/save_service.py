import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.split_candidate_dao import SplitCandidateDAO
from app.models.anime import Anime
from app.models.anime_freshness import AnimeFreshness
from app.schemas.search_schema import SearchResultDB
from app.services.anime_search_service import anime_title_texts
from app.services.anime_service import create_anime_from_media
from app.services.media_service import (
    media_unconnected_from_info,
    persist_media_with_links,
)
from app.services.merge_detection_service import (
    detect_merge_candidates,
    find_cross_anime_relation_pairs,
)
from app.services.progress_reporter import ProgressReporter
from app.services.relation_classifier import outgoing_edges
from app.services.spoiler_service import refresh_spoiler_cache_for_anime_ids
from app.services.vector_embedding_service import create_anime_embedding

logger = logging.getLogger(__name__)
split_candidate_dao = SplitCandidateDAO()

async def save_search_results(
    db: AsyncSession,
    search_results: list[SearchResultDB],
    progress: ProgressReporter | None = None,
):
    logger.debug(f"DB session: {id(db)}")
    saved_media_count = 0
    new_anime_ids: list[int] = []
    for result in search_results:
        if not result.unconnected_media_list:
            continue  # Nothing to save if no media in result

        # Pick the first media item to create Anime from
        anime_as_media_in = result.unconnected_media_list[0]
        anime = await create_anime_from_media(db, anime_as_media_in)
        # Every catalog row born with its freshness sidecar so the nightly
        # sweep's LEFT JOIN + COALESCE stays defensive belt-and-braces.
        # last_checked_at=None is honest: nothing has *checked* this row
        # from MAL yet — the row IS the check.
        anime.freshness = AnimeFreshness(last_checked_at=None, stable_check_count=0)
        new_anime_ids.append(anime.id)
        logger.info(f"Created Anime: {anime.title} (ID: {anime.id})")

        # Create anime-level vector embeddings
        await create_anime_embedding(
            db,
            anime_id=anime.id,
            title_texts=anime_title_texts(anime),
            description_text=anime.description or "",
        )
        logger.info(f"Created embedding for Anime: {anime.title} (ID: {anime.id})")

        # Create all Media attached to that Anime
        for media_in in result.unconnected_media_list:
            media_obj = await persist_media_with_links(
                db, media_in, anime_id=anime.id, last_checked_at=None,
                relation_edges=outgoing_edges(result.edges, media_in.mal_id),
            )
            logger.info(f"Created Media: {media_obj.title} (ID: {media_obj.id})")

            saved_media_count += 1
            if progress is not None:
                await progress.update(items_done=saved_media_count)

        # If the third pass found disjoint substance-passing chains in
        # this graph (BNHA→Vigilante, Toaru Index→Railgun shape), queue
        # a SplitCandidate for admin review. The new Anime row lands as
        # usual — split execution is opt-in via the admin UI so the
        # easier-to-merge-than-split invariant holds.
        if result.disjoint_franchises:
            inserted = await split_candidate_dao.upsert_pending(
                db, anime_id=anime.id,
                clusters=result.disjoint_franchises,
                detected_by="scrape",
            )
            if inserted:
                logger.info(
                    "Flagged SplitCandidate (scrape): anime_id=%d %r, %d clusters",
                    anime.id, anime.title, len(result.disjoint_franchises),
                )

    # Detect potential duplicate anime against the existing catalog before
    # the final commit. Same-tx so detection rolls back with the save if
    # something goes wrong; either both land or neither. relation_link pairs
    # come from the sidecars written above in this transaction.
    if new_anime_ids:
        cross_link_pairs = await find_cross_anime_relation_pairs(
            db, scope_anime_ids=new_anime_ids,
        )
        await detect_merge_candidates(db, new_anime_ids, cross_link_pairs)

    await db.commit()

    if new_anime_ids:
        # Existing users' spoiler caches need a recompute against the new
        # media set; otherwise spoiler_level=hide filters the new animes out
        # until the next backend restart triggers backfill_spoiler_visibility.
        # Scoped to the anime created this call (this path only creates new
        # anime; attach-to-existing is a separate function).
        await refresh_spoiler_cache_for_anime_ids(db, new_anime_ids)


async def attach_search_result_to_anime(
    db: AsyncSession,
    parent_anime: Anime,
    related_anime_graph: dict[int, dict],
    all_info: dict[int, dict],
    edges: list[tuple[int, int, str]] | None = None,
    saved_sink: list[dict] | None = None,
) -> int:
    """Attach probe-discovered media as Media rows under an existing parent.
    Skips mal_ids already attached to the parent (the BFS seed is one of
    them). Returns count of newly-saved Media rows. `edges` is the per-
    anime BFS edge list; outgoing slices are persisted to each new
    media's MediaRelationEdges sidecar.

    `saved_sink`, when provided, gets one `{"media_uuid", "title"}` dict
    appended per newly-saved media — captured here (inside the caller's
    savepoint, before commit) so the sweep can report exactly which media
    the relations probe attached. Same out-param pattern as the
    dispatcher's `diff_sink`; the `int` return stays for count-only callers.
    """
    edges = edges or []
    existing_parent_mal_ids = {m.mal_id for m in parent_anime.media}
    saved_count = 0
    now = datetime.now(timezone.utc)
    for mal_id, relation_info in related_anime_graph.items():
        if mal_id in existing_parent_mal_ids:
            continue
        media_in = media_unconnected_from_info(
            all_info[mal_id], relation_type=relation_info.get("relation_type"),
        )
        media_obj = await persist_media_with_links(
            db, media_in, anime_id=parent_anime.id, last_checked_at=now,
            relation_edges=outgoing_edges(edges, mal_id),
        )
        if saved_sink is not None:
            # name_eng / name_jap so the detail page can render the attached
            # media in the admin's settings name language (resolveTitle falls
            # back to the romaji title when these are null).
            saved_sink.append({
                "media_uuid": str(media_obj.uuid),
                "title": media_obj.title,
                "name_eng": media_obj.name_eng,
                "name_jap": media_obj.name_jap,
            })
        saved_count += 1
    return saved_count
