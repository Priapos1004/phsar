from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.base_dao import BaseDAO
from app.models.tag import Tag


class TagDAO(BaseDAO[Tag]):
    def __init__(self):
        super().__init__(Tag)

    async def get_default_for_user(self, db: AsyncSession, user_id: int) -> Tag | None:
        # is_default is NOT NULL, so `= true` equals `IS true`.
        return await self.get_by_field(db, user_id=user_id, is_default=True)
