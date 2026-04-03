import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import BaseDAO
from app.models.media import Media
from app.models.ratings import Ratings

logger = logging.getLogger(__name__)


class RatingDAO(BaseDAO[Ratings]):
    def __init__(self):
        super().__init__(Ratings)

    def _eager_load_options(self):
        return [
            selectinload(Ratings.media).selectinload(Media.anime),
            selectinload(Ratings.rating_search),
        ]

    async def get_by_uuid_and_user(self, db: AsyncSession, uuid: UUID, user_id: int) -> Ratings | None:
        stmt = (
            select(self.model)
            .filter_by(uuid=uuid, user_id=user_id)
            .options(*self._eager_load_options())
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_by_user_and_media(self, db: AsyncSession, user_id: int, media_id: int) -> Ratings | None:
        result = await db.execute(
            select(self.model).filter_by(user_id=user_id, media_id=media_id)
        )
        return result.scalars().first()

    async def get_by_media_uuid_and_user(self, db: AsyncSession, media_uuid: UUID, user_id: int) -> Ratings | None:
        stmt = (
            select(self.model)
            .join(Media)
            .where(Media.uuid == media_uuid, self.model.user_id == user_id)
            .options(*self._eager_load_options())
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_all_by_user(
        self, db: AsyncSession, user_id: int, limit: int = 50, offset: int = 0
    ) -> list[Ratings]:
        stmt = (
            select(self.model)
            .filter_by(user_id=user_id)
            .options(*self._eager_load_options())
            .order_by(self.model.modified_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return result.scalars().all()
