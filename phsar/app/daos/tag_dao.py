from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.base_dao import BaseDAO
from app.models.tag import Tag


class TagDAO(BaseDAO[Tag]):
    def __init__(self):
        super().__init__(Tag)

    async def get_default_for_user(self, db: AsyncSession, user_id: int) -> Tag | None:
        # is_default is NOT NULL, so `= true` equals `IS true`.
        return await self.get_by_field(db, user_id=user_id, is_default=True)

    async def get_by_uuid_and_user(self, db: AsyncSession, uuid: UUID, user_id: int) -> Tag | None:
        return await self.get_by_field(db, uuid=uuid, user_id=user_id)

    async def get_by_name_and_user(self, db: AsyncSession, name: str, user_id: int) -> Tag | None:
        return await self.get_by_field(db, name=name, user_id=user_id)

    async def get_all_by_user(self, db: AsyncSession, user_id: int) -> list[Tag]:
        """All of a user's tags, default tag first, then alphabetical by name."""
        result = await db.execute(
            select(Tag)
            .where(Tag.user_id == user_id)
            .order_by(Tag.is_default.desc(), Tag.name.asc())
        )
        return result.scalars().all()

    async def count_by_user(self, db: AsyncSession, user_id: int) -> int:
        result = await db.execute(
            select(func.count()).select_from(Tag).where(Tag.user_id == user_id)
        )
        return result.scalar_one()
