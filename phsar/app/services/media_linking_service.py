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
    if not genres:
        return
    logger.debug(f"DB session: {id(db)}")

    all_genres = await genre_dao.get_all_by_field(db, "name", genres)
    genre_by_name = {g.name: g for g in all_genres}

    for genre_name in genres:
        genre = genre_by_name.get(genre_name)
        if genre:
            db.add(MediaGenre(genre_id=genre.id, media_id=media_id))
    await db.flush()


async def link_studios_to_media(db: AsyncSession, media_id: int, studios: list[str]):
    if not studios:
        return
    logger.debug(f"DB session: {id(db)}")

    existing = await studio_dao.get_all_by_field(db, "name", studios)
    studio_by_name = {s.name: s for s in existing}

    for name in studios:
        if name not in studio_by_name:
            studio = Studio(name=name)
            db.add(studio)
            studio_by_name[name] = studio
    # Flush to assign IDs to newly created studios before linking
    await db.flush()

    for studio_name in studios:
        db.add(MediaStudio(studio_id=studio_by_name[studio_name].id, media_id=media_id))
    await db.flush()
