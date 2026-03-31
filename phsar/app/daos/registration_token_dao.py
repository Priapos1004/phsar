from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.base_dao import BaseDAO
from app.models.registration_token import RegistrationToken


class RegistrationTokenDAO(BaseDAO[RegistrationToken]):
    def __init__(self):
        super().__init__(RegistrationToken)

    async def get_by_token(self, db: AsyncSession, token: str) -> RegistrationToken | None:
        return await self.get_by_field(db, token=token)
