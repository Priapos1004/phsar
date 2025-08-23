from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.base_dao import BaseDAO
from app.models.studio import Studio


class StudioDAO(BaseDAO[Studio]):
    def __init__(self):
        super().__init__(Studio)

    async def get_distinct_used_studios(self, db: AsyncSession) -> list[str]:
        """
        Retrieve distinct studio names that are actually linked to media via the media_studio relationship.
        """
        stmt = (
            select(distinct(Studio.name))
            .join(Studio.media_studio)
            .order_by(Studio.name)
        )
        result = await db.execute(stmt)
        distinct_genres = [row[0] for row in result.fetchall()]
        return distinct_genres
