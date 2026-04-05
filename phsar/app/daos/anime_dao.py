from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_mal_id_dao import MalIdDAO
from app.models.anime import Anime
from app.models.media import Media
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio


class AnimeDAO(MalIdDAO[Anime]):
    def __init__(self):
        super().__init__(Anime)

    async def get_with_media_by_id(self, db: AsyncSession, anime_id: int) -> Anime | None:
        """Fetch an anime with all its media entries, each with genres and studios eagerly loaded."""
        stmt = (
            select(Anime)
            .filter(Anime.id == anime_id)
            .options(
                selectinload(Anime.media)
                .selectinload(Media.media_genre)
                .selectinload(MediaGenre.genre),
                selectinload(Anime.media)
                .selectinload(Media.media_studio)
                .selectinload(MediaStudio.studio),
            )
        )
        result = await db.execute(stmt)
        return result.scalars().first()
