from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.base_dao import BaseDAO
from app.models.genre import Genre


class GenreDAO(BaseDAO[Genre]):
    def __init__(self):
        super().__init__(Genre)

    async def get_distinct_used_genres(self, db: AsyncSession) -> list[str]:
        """
        Retrieve distinct genre names that are actually linked to media via the media_genre relationship.
        """
        stmt = (
            select(distinct(Genre.name))
            .join(Genre.media_genre)
            .order_by(Genre.name)
        )
        result = await db.execute(stmt)
        distinct_genres = [row[0] for row in result.fetchall()]
        return distinct_genres
