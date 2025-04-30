import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.search_schema import SearchResultDB
from app.services.anime_service import create_anime_from_media
from app.services.media_linking_service import (link_genres_to_media,
                                                link_studios_to_media)
from app.services.media_service import create_media
from app.services.vector_embedding_service import create_media_embedding

logger = logging.getLogger(__name__)

async def save_search_results(db: AsyncSession, search_results: list[SearchResultDB]):
    logger.debug(f"DB session: {id(db)}")
    for result in search_results:
        if not result.unconnected_media_list:
            continue  # Nothing to save if no media in result

        # Pick the first media item to create Anime from
        anime_as_media_in = result.unconnected_media_list[0]
        anime = await create_anime_from_media(db, anime_as_media_in)
        logger.info(f"Created Anime: {anime.title} (ID: {anime.id})")

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
                texts=[
                    media_in.title,
                    media_in.name_eng,
                    media_in.name_jap,
                    *media_in.other_names,
                ]
            )
            logger.info(f"Created embedding for Media: {media_obj.title} (ID: {media_obj.id})")

    await db.commit()  # Single commit at the end!
