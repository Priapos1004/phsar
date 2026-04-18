from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.base_dao import BaseDAO
from app.models.user_settings import UserSettings


class UserSettingsDAO(BaseDAO[UserSettings]):
    def __init__(self):
        super().__init__(UserSettings)

    async def get_by_user_id(self, db: AsyncSession, user_id: int) -> UserSettings | None:
        return await self.get_by_field(db, user_id=user_id)
