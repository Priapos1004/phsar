import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

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
    resolve_cross_link_pairs,
)
from app.services.progress_reporter import ProgressReporter
from app.services.spoiler_service import refresh_spoiler_cache_for_all_users
from app.services.vector_embedding_service import create_anime_embedding

logger = logging.getLogger(__name__)

async def save_search_results(
    db: AsyncSession,
    search_results: list[SearchResultDB],
    progress: ProgressReporter | None = None,
):
    logger.debug(f"DB session: {id(db)}")
    saved_anything = False
    saved_media_count = 0
    new_anime_ids: list[int] = []
    cross_link_pairs: list[tuple[int, int]] = []
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
        saved_anything = True
        new_anime_ids.append(anime.id)
        # Resolve graph cross-links to (this new anime, owning anime) pairs
        # for the relation_link detector. Resolution happens here, while we
        # have the just-created anime.id in scope.
        if result.cross_link_mal_ids:
            cross_link_pairs.extend(
                await resolve_cross_link_pairs(db, anime.id, result.cross_link_mal_ids)
            )
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
            )
            logger.info(f"Created Media: {media_obj.title} (ID: {media_obj.id})")

            saved_media_count += 1
            if progress is not None:
                await progress.update(items_done=saved_media_count)

    # Detect potential duplicate anime against the existing catalog before
    # the final commit. Same-tx so detection rolls back with the save if
    # something goes wrong; either both land or neither.
    if new_anime_ids or cross_link_pairs:
        await detect_merge_candidates(db, new_anime_ids, cross_link_pairs)

    await db.commit()  # Single commit at the end!

    if saved_anything:
        # Existing users' spoiler caches need a recompute against the new
        # media set; otherwise spoiler_level=hide filters the new animes out
        # until the next backend restart triggers backfill_spoiler_visibility.
        await refresh_spoiler_cache_for_all_users(db)


async def attach_search_result_to_anime(
    db: AsyncSession,
    parent_anime: Anime,
    related_anime_graph: dict[int, dict],
    all_info: dict[int, dict],
) -> int:
    """Attach probe-discovered media as Media rows under an existing parent.
    Skips mal_ids already attached to the parent (the BFS seed is one of
    them). Returns count of newly-saved Media rows."""
    existing_parent_mal_ids = {m.mal_id for m in parent_anime.media}
    saved_count = 0
    now = datetime.now(timezone.utc)
    for mal_id, relation_info in related_anime_graph.items():
        if mal_id in existing_parent_mal_ids:
            continue
        media_in = media_unconnected_from_info(
            all_info[mal_id], relation_type=relation_info.get("relation_type"),
        )
        await persist_media_with_links(
            db, media_in, anime_id=parent_anime.id, last_checked_at=now,
        )
        saved_count += 1
    return saved_count
