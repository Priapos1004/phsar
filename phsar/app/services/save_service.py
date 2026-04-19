import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.users import Users
from app.schemas.search_schema import SearchResultDB
from app.services.anime_search_service import anime_title_texts
from app.services.anime_service import create_anime_from_media
from app.services.media_linking_service import (
    link_genres_to_media,
    link_studios_to_media,
)
from app.services.media_service import create_media
from app.services.spoiler_service import recompute_visibility_for_user
from app.services.vector_embedding_service import (
    create_anime_embedding,
    create_media_embedding,
)

logger = logging.getLogger(__name__)

async def save_search_results(db: AsyncSession, search_results: list[SearchResultDB]):
    logger.debug(f"DB session: {id(db)}")
    saved_anything = False
    for result in search_results:
        if not result.unconnected_media_list:
            continue  # Nothing to save if no media in result

        # Pick the first media item to create Anime from
        anime_as_media_in = result.unconnected_media_list[0]
        anime = await create_anime_from_media(db, anime_as_media_in)
        saved_anything = True
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
            media_obj = await create_media(db, media_in, anime_id=anime.id)
            logger.info(f"Created Media: {media_obj.title} (ID: {media_obj.id})")

            # Link genres
            await link_genres_to_media(db, media_id=media_obj.id, genres=media_in.genres)
            logger.info(f"Linked genres to Media: {media_obj.title} (ID: {media_obj.id})")

            # Link studios
            await link_studios_to_media(db, media_id=media_obj.id, studios=media_in.studio)
            logger.info(f"Linked studios to Media: {media_obj.title} (ID: {media_obj.id})")

            # Create vector embedding
            await create_media_embedding(
                db,
                media_id=media_obj.id,
                title_texts=[
                    media_in.title,
                    media_in.name_eng,
                    media_in.name_jap,
                    *media_in.other_names,
                ],
                description_text=media_in.description
            )
            logger.info(f"Created embedding for Media: {media_obj.title} (ID: {media_obj.id})")

    await db.commit()  # Single commit at the end!

    if saved_anything:
        await _refresh_spoiler_cache_for_all_users(db)


async def _refresh_spoiler_cache_for_all_users(db: AsyncSession) -> None:
    # Every existing user needs their spoiler cache recomputed against the new
    # media set; otherwise spoiler_level=hide filters the new animes out until
    # the next backend restart triggers backfill_spoiler_visibility.
    user_ids = (await db.execute(select(Users.id))).scalars().all()
    for user_id in user_ids:
        await recompute_visibility_for_user(db, user_id)
    await db.commit()
