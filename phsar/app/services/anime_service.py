import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.anime_dao import AnimeDAO
from app.exceptions import MalIdAlreadyExistsError
from app.models.anime import Anime
from app.schemas.media_schema import MediaUnconnected

logger = logging.getLogger(__name__)

anime_dao = AnimeDAO()

async def create_anime_from_media(db: AsyncSession, anime_as_media_in: MediaUnconnected) -> Anime:
    logger.debug(f"DB session: {id(db)}")
    # Check if anime already exists in the database
    existing = await anime_dao.get_by_mal_id(db, anime_as_media_in.mal_id)
    if existing:
        raise MalIdAlreadyExistsError(anime_as_media_in.mal_id, anime_as_media_in.title)

    # Create new Anime object based on MediaUnconnected info
    anime_obj = Anime(
        **anime_as_media_in.model_dump(
            include={
                "mal_id",
                "title",
                "name_eng",
                "name_jap",
                "other_names",
                "description",
                "cover_image",
            }
        )
    )

    await anime_dao.create(db, anime_obj)
    return anime_obj
