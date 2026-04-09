from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import BaseDAO
from app.models.registration_token import RegistrationToken


class RegistrationTokenDAO(BaseDAO[RegistrationToken]):
    def __init__(self):
        super().__init__(RegistrationToken)

    async def get_by_token(self, db: AsyncSession, token: str) -> RegistrationToken | None:
        return await self.get_by_field(db, token=token)

    async def get_by_uuid(self, db: AsyncSession, uuid: str) -> RegistrationToken | None:
        return await self.get_by_field(db, uuid=uuid)

    async def get_by_uuid_with_users(self, db: AsyncSession, uuid: str) -> RegistrationToken | None:
        result = await db.execute(
            select(RegistrationToken)
            .options(
                selectinload(RegistrationToken.created_by),
                selectinload(RegistrationToken.used_for_user),
            )
            .filter_by(uuid=uuid)
        )
        return result.scalars().first()

    async def get_all_with_users(self, db: AsyncSession) -> list[RegistrationToken]:
        result = await db.execute(
            select(RegistrationToken)
            .options(
                selectinload(RegistrationToken.created_by),
                selectinload(RegistrationToken.used_for_user),
            )
            .order_by(RegistrationToken.created_at.desc())
        )
        return list(result.scalars().all())
