from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeMeta

from app.daos.base_dao import BaseDAO

T = TypeVar("T", bound=DeclarativeMeta)

class MalIdDAO(BaseDAO[T], Generic[T]):
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
        result = await db.execute(select(self.model.mal_id))
        return result.scalars().all()
