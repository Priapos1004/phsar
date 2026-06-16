from sqlalchemy import delete, distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.base_dao import BaseDAO
from app.models.studio import Studio


class StudioDAO(BaseDAO[Studio]):
    def __init__(self):
        super().__init__(Studio)

    async def delete_orphaned(self, db: AsyncSession) -> int:
        """Delete Studio rows no longer linked to any media. The relaxed
        sweep drift policy applies studio removals (DELETE on MediaStudio),
        which can strand a Studio whose last media link was just dropped —
        e.g. a corrected MAL typo. Returns the number of rows removed.
        Genres deliberately have no equivalent: they're a curated seed
        taxonomy, so an unused genre is a valid filter option, not pollution."""
        stmt = delete(Studio).where(~Studio.media_studio.any())
        result = await db.execute(stmt)
        return result.rowcount or 0

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
