import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.genre_dao import GenreDAO
from app.daos.studio_dao import StudioDAO
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.studio import Studio

logger = logging.getLogger(__name__)

genre_dao = GenreDAO()
studio_dao = StudioDAO()

async def link_genres_to_media(db: AsyncSession, media_id: int, genres: list[str]):
    logger.debug(f"DB session: {id(db)}")
    for genre_name in genres:
        genre = await genre_dao.get_by_field(db, name=genre_name)
        if genre:
            db.add(MediaGenre(genre_id=genre.id, media_id=media_id))
    await db.flush()

async def link_studios_to_media(db: AsyncSession, media_id: int, studios: list[str]):
    logger.debug(f"DB session: {id(db)}")
    for studio_name in studios:
        studio = await studio_dao.get_by_field(db, name=studio_name)
        if not studio:
            studio = Studio(name=studio_name)
            await studio_dao.create(db, studio)
        db.add(MediaStudio(studio_id=studio.id, media_id=media_id))
    await db.flush()
