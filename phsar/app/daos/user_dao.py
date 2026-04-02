from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.base_dao import BaseDAO
from app.models.users import Users


class UserDAO(BaseDAO[Users]):
    def __init__(self):
        super().__init__(Users)

    async def get_by_username(self, db: AsyncSession, username: str) -> Users | None:
        return await self.get_by_field(db, username=username)

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
