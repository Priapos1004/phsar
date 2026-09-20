from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.base_dao import BaseDAO, T


class MalIdDAO(BaseDAO[T]):
    """
    DAO for models that have a 'mal_id' field.
    """

    async def get_by_mal_id(self, db: AsyncSession, mal_id: int) -> T | None:
        result = await db.execute(select(self.model).filter_by(mal_id=mal_id))
        return result.scalars().first()
    
    async def get_all_mal_ids(self, db: AsyncSession) -> list[int]:
        """
        Get all mal_id values currently stored in the database for this model.
        """
        # BaseModel has no mal_id. A mapped mixin could declare one, but that is
        # four model files and an `alembic check` run to delete one suppression.
        result = await db.execute(select(self.model.mal_id))  # type: ignore[attr-defined]
        return result.scalars().all()
