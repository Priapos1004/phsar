from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.base_dao import BaseDAO
from app.models.users import RoleType, Users


class UserDAO(BaseDAO[Users]):
    def __init__(self):
        super().__init__(Users)

    async def get_by_username(self, db: AsyncSession, username: str) -> Users | None:
        return await self.get_by_field(db, username=username)

    async def count_non_restricted(self, db: AsyncSession) -> int:
        """Users eligible for watchlists/custom lists (admin Overview aggregate).
        Restricted (guest) users are barred from the tag system, so they're the
        wrong denominator for a list-adoption average."""
        result = await db.execute(
            select(func.count()).select_from(Users).where(Users.role != RoleType.RestrictedUser)
        )
        return result.scalar_one()

    async def update_password_hash(
        self, db: AsyncSession, user_id: int, old_hash: str, new_hash: str
    ) -> bool:
        """Conditionally update password hash (race-safe). Returns True if updated."""
        stmt = (
            update(Users)
            .where(Users.id == user_id, Users.hashed_password == old_hash)
            .values(hashed_password=new_hash)
        )
        result = await db.execute(stmt)
        return getattr(result, "rowcount", 0) == 1
