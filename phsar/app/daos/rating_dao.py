import logging
from uuid import UUID

from sqlalchemy import delete, func, select
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
from app.daos.search_filters import SEMANTIC_MARGIN, literal_matches, match_passes
from app.models.anime import Anime
from app.models.media import MAIN_STORY_RELATIONS, Media
from app.models.rating_search import RatingSearch
from app.models.ratings import Ratings, WatchStatus
from app.schemas.rating_schema import RatingAttributes
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


def _note_distance(query_embedding):
    return RatingSearch.note_embedding.cosine_distance(query_embedding)


def note_cutoff(query_embedding, user_id: int):
    """The largest distance a semantic note hit may have: the mean distance to the
    query over the caller's own notes, less the margin — relative for description's
    reason (docs/features/search.md). Its explicit FROM keeps it uncorrelated, as
    `description_cutoff`'s does."""
    mean = (
        select(func.avg(_note_distance(query_embedding)))
        .select_from(RatingSearch)
        .join(Ratings, Ratings.id == RatingSearch.rating_id)
        .where(Ratings.user_id == user_id)
        .scalar_subquery()
    )
    return mean - SEMANTIC_MARGIN


def note_passes(stmt, query: str, query_embedding, user_id: int, *, having: bool = False) -> list:
    """Notes search through `match_passes`, over the note alone — the text its
    embedding encodes. `stmt` already outer-joins the caller's ratings by `rating_of`,
    and `rating_search` is 1:1 with a rating, so no media row fans out. The anime grain
    takes its media's nearest note, not description's average; why is in
    docs/features/search.md."""
    return match_passes(
        stmt.outerjoin(RatingSearch, RatingSearch.rating_id == Ratings.id),
        literal_matches(query, Ratings.note),
        _note_distance(query_embedding),
        note_cutoff(query_embedding, user_id),
        having=having, aggregate=func.min,
    )


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
        whose rating is being deleted."""
        if not media_ids:
            return []
        stmt = select(self.model.media_id).where(
            self.model.user_id == user_id, self.model.media_id.in_(media_ids)
        )
        return list((await db.execute(stmt)).scalars().all())

    async def notes_by_rated_media_id(
        self, db: AsyncSession, user_id: int, media_ids: list[int]
    ) -> dict[int, str | None]:
        """Which of the given media the user has rated, each with the rating's note — the
        media search's `is_rated` and, in notes mode, its quote."""
        if not media_ids:
            return {}
        stmt = select(self.model.media_id, self.model.note).where(
            self.model.user_id == user_id, self.model.media_id.in_(media_ids)
        )
        return dict((await db.execute(stmt)).tuples().all())

    async def best_note_by_anime_id(
        self, db: AsyncSession, user_id: int, query: str, anime_ids: list[int],
    ) -> dict[int, str]:
        """The caller's note that best matches `query` per anime, for the notes search's
        hits. Ordered as `note_passes` ranks: strict literal, then typo-tolerant literal,
        then nearest. Which pass admitted the hit is not known here, so an anime admitted
        semantically quotes a typo-literal note when it has one."""
        if not anime_ids:
            return {}
        stmt = (
            select(Media.anime_id, self.model.note)
            .select_from(Media)
            .join(self.model, rating_of(user_id))
            .outerjoin(RatingSearch, RatingSearch.rating_id == self.model.id)
            .where(self.model.note.is_not(None), Media.anime_id.in_(anime_ids))
            .order_by(
                *(literal.desc() for literal in literal_matches(query, self.model.note)),
                _note_distance(await generate_query_embedding(query)),
            )
        )
        best: dict[int, str] = {}
        for anime_id, note in (await db.execute(stmt)).all():
            best.setdefault(anime_id, note)
        return best

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
