import logging
from uuid import UUID

from sqlalchemy import and_, delete, func, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import BaseDAO, recency_order
from app.daos.media_projections import (
    anime_identity_columns,
    media_genre_names,
    media_identity_columns,
    media_studio_names,
)
from app.daos.search_filters import (
    apply_media_filters,
    description_passes,
    fetch_search_results,
    title_match_passes,
    title_match_score,
)
from app.models.anime import Anime
from app.models.media import MAIN_STORY_RELATIONS, Media
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.rating_search import RatingSearch
from app.models.ratings import Ratings, WatchStatus
from app.schemas.media_filter_schema import SearchType
from app.schemas.rating_schema import RatingAttributes, RatingSearchFilters
from app.services.vector_embedding_service import generate_query_embedding

logger = logging.getLogger(__name__)

# Used to apply rating enum filters dynamically (avoids 11 repetitive if-blocks).
# Derived from the schema; the assertion below ensures they stay in sync with the ORM model.
_RATING_ATTR_FIELDS = list(RatingAttributes.model_fields.keys())
for _f in _RATING_ATTR_FIELDS:
    assert hasattr(Ratings, _f), f"RatingAttributes field '{_f}' missing from Ratings model"


def rating_of(user_id: int):
    """Join condition from each `Media` row to `user_id`'s rating of it.
    `unique_user_media_rating` makes it 0-or-1, so as an outer join it never fans a
    media row set out and every aggregate over those rows stays a per-media one."""
    return (Ratings.media_id == Media.id) & (Ratings.user_id == user_id)


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
        return list(result.scalars().all())

    async def get_rated_media_ids(
        self, db: AsyncSession, user_id: int, media_ids: list[int]
    ) -> list[int]:
        """Which of the given media the user actually has a rating for. Scalar projection
        (no ORM rows / embeddings) — scopes an opt-in watch-history wipe to the media
        whose rating is being deleted, and flags the caller's own hits in media search."""
        if not media_ids:
            return []
        stmt = select(self.model.media_id).where(
            self.model.user_id == user_id, self.model.media_id.in_(media_ids)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def get_anime_coverage(self, db: AsyncSession, user_id: int) -> list[Row]:
        """Per-anime counts behind the rated state and the coverage tier, for every
        anime the user has rated at least one media of. The counts, not the state —
        `rating_service` turns them into one.

        Scoped to the anime the user has actually rated — bounded by their library,
        not the catalogue — for the reason spelled out in
        `media_projections._name_agg`. That scope is also what keeps untouched anime
        out of the response, pinned by `test_untouched_anime_is_absent_from_the_response`.
        """
        rated_anime = select(Media.anime_id).join(Ratings, rating_of(user_id))
        rateable = Media.is_rateable
        main = rateable & Media.relation_type.in_(MAIN_STORY_RELATIONS)
        # NULL for an unrated media, and a NULL filter predicate excludes the row —
        # which is exactly the "not completed" reading we want.
        status = Ratings.watch_status
        completed = status == WatchStatus.completed
        stmt = (
            select(
                Anime.id.label("anime_id"),
                Anime.uuid.label("anime_uuid"),
                func.count().filter(rateable).label("n_all"),
                func.count().filter(rateable & completed).label("done_all"),
                func.count().filter(main).label("n_main"),
                func.count().filter(main & completed).label("done_main"),
                func.count().filter(main & (status == WatchStatus.dropped)).label("dropped_main"),
                func.count().filter(main & (status == WatchStatus.on_hold)).label("on_hold_main"),
            )
            .select_from(Media)
            .join(Anime, Anime.id == Media.anime_id)
            .outerjoin(Ratings, rating_of(user_id))
            .where(Media.anime_id.in_(rated_anime))
            .group_by(Anime.id)
        )
        return list((await db.execute(stmt)).all())

    async def get_watch_status_by_media_id(self, db: AsyncSession, user_id: int) -> dict[int, WatchStatus]:
        """Every media the user has rated, with the rating's watch status — a media's
        rated state in search."""
        stmt = select(Ratings.media_id, Ratings.watch_status).where(Ratings.user_id == user_id)
        return dict((await db.execute(stmt)).tuples().all())

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
        return list(result.scalars().all())

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
        return list(result.scalars().all())

    async def get_all_by_user(
        self, db: AsyncSession, user_id: int, limit: int = 50, offset: int = 0
    ) -> list[Ratings]:
        stmt = (
            select(self.model)
            .filter_by(user_id=user_id)
            .options(*self._eager_load_options())
            # Paginated, so the PK tiebreak is load-bearing — see recency_order.
            .order_by(*recency_order(self.model))
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_all_for_score_items(self, db: AsyncSession, user_id: int) -> list[Row]:
        """All of a user's ratings as a FLAT projection of scalars — `Row`s, not
        ORM objects — for `rating_service.get_rating_score_items`. No pagination:
        the consistency helper compares against the whole set to find the nearest
        scores client-side.

        Flat rather than `selectinload`ed: see `daos/media_projections` for why
        these two endpoints project instead of eager-loading.

        Every column is labelled to its `RatingScoreItem` field name, which is
        what lets the service build the DTO straight off `Row._mapping` — so this
        projection IS the field list, and a rename here is a rename of the DTO
        contract.

        `ix_ratings_user_modified` covers the `WHERE user_id ORDER BY
        modified_at DESC` on the driving table; `recency_order` supplies the
        required PK tiebreak.
        """
        media_scope = select(Ratings.media_id).where(Ratings.user_id == user_id)
        genres = media_genre_names(media_scope)
        studios = media_studio_names(media_scope)
        stmt = (
            select(
                Ratings.rating,
                Ratings.watch_status,
                Ratings.episodes_watched,
                Ratings.created_at,
                Ratings.modified_at,
                # Driven off the schema-derived list so a new attribute can't be
                # added to the DTO and forgotten here.
                *(getattr(Ratings, f) for f in _RATING_ATTR_FIELDS),
                *media_identity_columns(),
                Media.score.label("mal_score"),
                Media.scored_by,
                Media.episodes,
                Media.duration_seconds,
                Media.anime_season_name,
                Media.anime_season_year,
                Media.relation_type,
                Media.original_source,
                # Hybrid with a SQL expression — selects like a column.
                Media.age_rating_numeric.label("age_rating_numeric"),
                *anime_identity_columns(),
                genres.c.genres,
                studios.c.studios,
            )
            .join(Media, Media.id == Ratings.media_id)
            .join(Anime, Anime.id == Media.anime_id)
            .outerjoin(genres, genres.c.media_id == Media.id)
            .outerjoin(studios, studios.c.media_id == Media.id)
            .where(Ratings.user_id == user_id)
            .order_by(*recency_order(Ratings))
        )
        return list((await db.execute(stmt)).all())

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

        stmt = apply_media_filters(stmt, filters)

        conditions = []
        if filters.user_rating_min is not None:
            conditions.append(self.model.rating >= filters.user_rating_min)
        if filters.user_rating_max is not None:
            conditions.append(self.model.rating <= filters.user_rating_max)
        if filters.watch_status:
            conditions.append(self.model.watch_status.in_(filters.watch_status))
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
        ).limit(limit)

        if query and search_type == SearchType.TITLE:
            title_match = title_match_score(query, Media)
            passes = title_match_passes(stmt.order_by(title_match.desc(), *recency_order(self.model)), title_match)
        elif query and search_type == SearchType.DESCRIPTION:
            passes = description_passes(stmt, query, await generate_query_embedding(query))
        elif query and search_type == SearchType.RATING_NOTES:
            # A rating without a note has no embedding, so the inner join drops it.
            query_embedding = await generate_query_embedding(query)
            passes = [
                stmt.join(RatingSearch, RatingSearch.rating_id == self.model.id).order_by(
                    RatingSearch.note_embedding.cosine_distance(query_embedding),
                ),
            ]
        else:
            passes = [stmt.order_by(*recency_order(self.model))]

        return await fetch_search_results(db, *passes)
