import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.media_unwanted_dao import MediaUnwantedDAO
from app.models.media_unwanted import MediaUnwanted

logger = logging.getLogger(__name__)

media_unwanted_dao = MediaUnwantedDAO()

async def create_unwanted_media(db: AsyncSession, unwanted_media: set[tuple[int, str, str]]) -> None:
    logger.debug(f"DB session: {id(db)}")
    inserted = 0
    for mal_id, title, reason in unwanted_media:
        existing = await media_unwanted_dao.get_by_mal_id(db, mal_id)
        if existing:
            logger.info(f"Unwanted media with mal_id={mal_id} already exists (title={title}, reason={reason}). Skipping.")
            continue
        
        unwanted_media_obj = MediaUnwanted(
            mal_id=mal_id,
            title=title,
            reason=reason
        )
        await media_unwanted_dao.create(db, unwanted_media_obj)
        inserted += 1

    logger.info(f"Finished inserting {inserted} unwanted media items.")
