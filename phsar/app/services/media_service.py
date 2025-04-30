import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.media_dao import MediaDAO
from app.exceptions import MalIdAlreadyExistsError
from app.models.media import Media
from app.schemas.media_schema import MediaUnconnected

logger = logging.getLogger(__name__)

media_dao = MediaDAO()

async def create_media(db: AsyncSession, media_in: MediaUnconnected, anime_id: int) -> Media:
    logger.debug(f"DB session: {id(db)}")
    # Check if media already exists in the database
    existing = await media_dao.get_by_mal_id(db, media_in.mal_id)
    if existing:
        raise MalIdAlreadyExistsError(media_in.mal_id, media_in.title)

    media_obj = Media(
        **media_in.model_dump(exclude={"genres", "studio"}),
        anime_id=anime_id
    )
    await media_dao.create(db, media_obj)
    return media_obj
