import logging
from uuid import UUID

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import BaseDAO
from app.daos.search_filters import apply_media_filters, apply_vector_ordering
from app.models.anime import Anime
from app.models.media import Media
from app.models.media_genre import MediaGenre
from app.models.media_search import MediaSearch
from app.models.media_studio import MediaStudio
from app.models.rating_search import RatingSearch
from app.models.ratings import Ratings
from app.schemas.media_filter_schema import SearchType
from app.schemas.rating_schema import RatingAttributes, RatingSearchFilters
from app.services.vector_embedding_service import generate_embedding

logger = logging.getLogger(__name__)

# Used to apply rating enum filters dynamically (avoids 11 repetitive if-blocks).
# Derived from the schema; the assertion below ensures they stay in sync with the ORM model.
_RATING_ATTR_FIELDS = list(RatingAttributes.model_fields.keys())
for _f in _RATING_ATTR_FIELDS:
    assert hasattr(Ratings, _f), f"RatingAttributes field '{_f}' missing from Ratings model"


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
        stmt = (
            select(self.model)
            .filter_by(user_id=user_id, media_id=media_id)
            .options(selectinload(Ratings.rating_search))
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_by_user_and_media_ids(
        self, db: AsyncSession, user_id: int, media_ids: list[int]
    ) -> list[Ratings]:
        if not media_ids:
            return []
        stmt = (
            select(self.model)
            .where(self.model.user_id == user_id, self.model.media_id.in_(media_ids))
            .options(selectinload(Ratings.rating_search))
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def bulk_delete_by_user_and_media_ids(
        self, db: AsyncSession, user_id: int, media_ids: list[int]
    ) -> int:
        """Single-statement bulk delete. DB-level ON DELETE CASCADE handles rating_search rows."""
        if not media_ids:
            return 0
        stmt = (
            delete(self.model)
            .where(self.model.user_id == user_id, self.model.media_id.in_(media_ids))
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    async def get_by_media_uuid_and_user(self, db: AsyncSession, media_uuid: UUID, user_id: int) -> Ratings | None:
        stmt = (
            select(self.model)
            .join(Media)
            .where(Media.uuid == media_uuid, self.model.user_id == user_id)
            .options(*self._eager_load_options())
        )
        result = await db.execute(stmt)
        return result.scalars().first()

    async def get_by_uuids_and_user(
        self, db: AsyncSession, uuids: list[UUID], user_id: int
    ) -> list[Ratings]:
        stmt = (
            select(self.model)
            .where(self.model.uuid.in_(uuids), self.model.user_id == user_id)
            .options(*self._eager_load_options())
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    async def get_by_user_and_anime_uuid(
        self, db: AsyncSession, user_id: int, anime_uuid: UUID
    ) -> list[Ratings]:
        stmt = (
            select(self.model)
            .join(Media, self.model.media_id == Media.id)
            .join(Anime, Media.anime_id == Anime.id)
            .where(Anime.uuid == anime_uuid, self.model.user_id == user_id)
            .options(*self._eager_load_options())
        )
        result = await db.execute(stmt)
        return result.scalars().all()

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

    async def search_ratings_with_filters(
        self,
        db: AsyncSession,
        user_id: int,
        query: str,
        filters: RatingSearchFilters,
        search_type: SearchType,
        limit: int = 50,
    ) -> list[Ratings]:
        stmt = (
            select(self.model)
            .join(Media, self.model.media_id == Media.id)
            .where(self.model.user_id == user_id)
        )

        if query:
            if search_type in (SearchType.TITLE, SearchType.DESCRIPTION):
                stmt = stmt.join(MediaSearch, MediaSearch.media_id == Media.id)
            elif search_type == SearchType.RATING_NOTES:
                stmt = stmt.join(RatingSearch, RatingSearch.rating_id == self.model.id)

        stmt = apply_media_filters(stmt, filters)

        conditions = []
        if filters.user_rating_min is not None:
            conditions.append(self.model.rating >= filters.user_rating_min)
        if filters.user_rating_max is not None:
            conditions.append(self.model.rating <= filters.user_rating_max)
        if filters.dropped is not None:
            conditions.append(self.model.dropped == filters.dropped)
        for field_name in _RATING_ATTR_FIELDS:
            values = getattr(filters, field_name, None)
            if values:
                conditions.append(getattr(self.model, field_name).in_(values))
        if conditions:
            stmt = stmt.where(and_(*conditions))

        stmt = stmt.options(
            selectinload(self.model.media).selectinload(Media.anime),
            selectinload(self.model.media).selectinload(Media.media_genre).selectinload(MediaGenre.genre),
            selectinload(self.model.media).selectinload(Media.media_studio).selectinload(MediaStudio.studio),
        )

        if query:
            query_embedding = await generate_embedding(query)
            stmt = apply_vector_ordering(
                stmt, search_type, query_embedding,
                extra_columns={SearchType.RATING_NOTES: RatingSearch.note_embedding},
            )
        else:
            stmt = stmt.order_by(self.model.modified_at.desc())

        stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()
