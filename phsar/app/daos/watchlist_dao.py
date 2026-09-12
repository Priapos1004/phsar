from datetime import datetime
from uuid import UUID

from sqlalchemy import case, delete, func, select, update
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
from app.models.anime import Anime
from app.models.media import MAIN_STORY_RELATIONS, SEASON_ORDER, Media
from app.models.ratings import Ratings, WatchStatus
from app.models.tag import Tag
from app.models.watchlist import Watchlist
from app.services.relation_classifier import (
    AIRING_STATUS_CURRENTLY_AIRING,
    AIRING_STATUS_NOT_YET_AIRED,
)

# Sortable season key: `year * 10 + rank`, so (2026, Fall) > (2026, Summer) and
# (2027, Winter) > both with one integer comparison. The SQL twin of
# `filter_service.chronological_media_key`'s first two components; the frontend builds
# the same key for "next season" and compares, which keeps the season arithmetic in
# one place instead of passing a moving cutoff down into SQL.
#
# No `else_`: every SeasonType has a WHEN, and `check_season_parts_both_or_none` makes
# a year without a season unstorable, so no fallback is reachable. Defaulting to NULL
# rather than a rank of 0 is still the better shape for a season added to the enum
# later — it drops out of the MIN instead of sorting ahead of Winter. Unreachable
# today, so no test separates the two.
#
# Spelled as explicit WHEN comparisons rather than `case(mapping, value=...)`: the
# shorthand binds its keys untyped, and asyncpg refuses `seasontype = varchar`. Same
# form as `search_filters._score_weight_case`, for the same reason.
_SEASON_KEY = Media.anime_season_year * 10 + case(
    *[(Media.anime_season_name == season, rank) for season, rank in SEASON_ORDER.items()],
)


def _franchise_signals(anime_id_scope, user_id: int):
    """Per-anime "is new content coming?" signals over the WHOLE franchise, as a
    subquery to LEFT JOIN on `anime_id`.

    This is the one thing the watchlist page cannot answer from the user's own
    entries: whether the anime has main-story content airing now or announced soon
    that the user did NOT watchlist. Starting a franchise with an unlisted sequel
    already airing means catching up and then waiting, which is what the readiness
    filter exists to avoid.

    The scopes are deliberate:

    - **Main story only** (`MAIN_STORY_RELATIONS`) — an upcoming OVA, movie or recap
      is not a season you wait for, so it must not park the whole franchise.
    - **Airing ignores media the user dropped.** If they bailed on the season that is
      airing, they are not waiting for it. `IS DISTINCT FROM` rather than `!=` so an
      unrated media (NULL) still counts as blocking. The upcoming half needs no such
      guard: a not-yet-aired media can never carry a rating (`CannotRateUnairedError`).

    Scoped to the anime ids the user actually watchlisted, for the reason spelled out
    in `media_projections._name_agg` — grouped once over a bounded set, not correlated
    per row and not over the whole catalogue.
    """
    return (
        select(
            Media.anime_id.label("anime_id"),
            func.bool_or(
                (Media.airing_status == AIRING_STATUS_CURRENTLY_AIRING)
                & Ratings.watch_status.is_distinct_from(WatchStatus.dropped)
            ).label("franchise_airing"),
            func.min(_SEASON_KEY)
            .filter(Media.airing_status == AIRING_STATUS_NOT_YET_AIRED)
            .label("franchise_upcoming_key"),
        )
        .select_from(Media)
        .outerjoin(Ratings, (Ratings.media_id == Media.id) & (Ratings.user_id == user_id))
        .where(
            Media.anime_id.in_(anime_id_scope),
            Media.relation_type.in_(MAIN_STORY_RELATIONS),
        )
        .group_by(Media.anime_id)
        .subquery()
    )


class WatchlistDAO(BaseDAO[Watchlist]):
    def __init__(self):
        super().__init__(Watchlist)

    def _eager_load_options(self):
        return [
            selectinload(Watchlist.media).selectinload(Media.anime),
            selectinload(Watchlist.tag),
        ]

    # --- Entry lookups ---

    async def get_by_uuid_and_user(self, db: AsyncSession, uuid: UUID, user_id: int) -> Watchlist | None:
        stmt = (
            select(Watchlist)
            .filter_by(uuid=uuid, user_id=user_id)
            .options(*self._eager_load_options())
        )
        return (await db.execute(stmt)).scalars().first()

    async def get_by_user_and_media(self, db: AsyncSession, user_id: int, media_id: int) -> Watchlist | None:
        """Lightweight upsert lookup (no eager load — the caller mutates or re-fetches)."""
        return await self.get_by_field(db, user_id=user_id, media_id=media_id)

    async def get_by_user_and_media_ids(
        self, db: AsyncSession, user_id: int, media_ids: list[int]
    ) -> list[Watchlist]:
        """Lightweight batch upsert lookup (no eager load)."""
        if not media_ids:
            return []
        stmt = select(Watchlist).where(
            Watchlist.user_id == user_id, Watchlist.media_id.in_(media_ids)
        )
        return (await db.execute(stmt)).scalars().all()

    async def get_by_media_uuid_and_user(self, db: AsyncSession, media_uuid: UUID, user_id: int) -> Watchlist | None:
        stmt = (
            select(Watchlist)
            .join(Media)
            .where(Media.uuid == media_uuid, Watchlist.user_id == user_id)
            .options(*self._eager_load_options())
        )
        return (await db.execute(stmt)).scalars().first()

    async def get_by_uuids_and_user(
        self, db: AsyncSession, uuids: list[UUID], user_id: int
    ) -> list[Watchlist]:
        if not uuids:
            return []
        stmt = (
            select(Watchlist)
            .where(Watchlist.uuid.in_(uuids), Watchlist.user_id == user_id)
            .options(*self._eager_load_options())
        )
        return (await db.execute(stmt)).scalars().all()

    async def get_by_user_and_anime_uuid(
        self, db: AsyncSession, user_id: int, anime_uuid: UUID
    ) -> list[Watchlist]:
        stmt = (
            select(Watchlist)
            .join(Media, Watchlist.media_id == Media.id)
            .join(Anime, Media.anime_id == Anime.id)
            .where(Anime.uuid == anime_uuid, Watchlist.user_id == user_id)
            .options(*self._eager_load_options())
        )
        return (await db.execute(stmt)).scalars().all()

    async def get_all_for_items(self, db: AsyncSession, user_id: int) -> list[Row]:
        """All of a user's watchlist entries as a FLAT projection of scalars —
        `Row`s, not ORM objects — backing the overview page's one-fetch list +
        grid + Statistics subtab. Ordered modified_at desc
        (`ix_watchlist_user_modified` covers the WHERE + ORDER BY on the driving
        table).

        Flat rather than `selectinload`ed: see `daos/media_projections` for why
        these two endpoints project instead of eager-loading.

        Every column is labelled to its `WatchlistItem` field name, which is what
        lets the service build the DTO straight off `Row._mapping` — so this
        projection IS the field list, and a rename here is a rename of the DTO
        contract. (`Tag.uuid`/`Tag.name` collide with Media's and Anime's too, so
        they carry `tag_*` labels for the same reason.)

        The readiness columns are the media's own `airing_status`, the caller's
        `watch_status` on it, and the `_franchise_signals` pair — the only values
        here that read media OUTSIDE the user's watchlist.
        """
        media_scope = select(Watchlist.media_id).where(Watchlist.user_id == user_id)
        anime_scope = select(Media.anime_id).where(Media.id.in_(media_scope))
        genres = media_genre_names(media_scope)
        studios = media_studio_names(media_scope)
        franchise = _franchise_signals(anime_scope, user_id)
        stmt = (
            select(
                Watchlist.uuid,
                Watchlist.priority,
                Watchlist.note,
                Watchlist.created_at,
                Watchlist.modified_at,
                Tag.uuid.label("tag_uuid"),
                Tag.name.label("tag_name"),
                Tag.color.label("tag_color"),
                *media_identity_columns(),
                Media.relation_type,
                Media.anime_season_name,
                Media.anime_season_year,
                Media.airing_status,
                Media.mal_id,
                # The canonical hybrid, not raw episodes x duration.
                Media.total_watch_time.label("total_watch_time"),
                # NULL when the user has never rated this media. The readiness filter
                # reads it to tell a rewatch from fresh content; `unique_user_media_rating`
                # makes the join 0-or-1, so it can't fan the row set out.
                Ratings.watch_status.label("watch_status"),
                *anime_identity_columns(),
                genres.c.genres,
                studios.c.studios,
                # COALESCE for the LEFT JOIN miss — an anime whose only watchlisted
                # media is side content has no main story, so no franchise row.
                # Absent evidence of upcoming content, nothing blocks.
                func.coalesce(franchise.c.franchise_airing, False).label("franchise_airing"),
                franchise.c.franchise_upcoming_key,
            )
            .join(Tag, Tag.id == Watchlist.tag_id)
            .join(Media, Media.id == Watchlist.media_id)
            .join(Anime, Anime.id == Media.anime_id)
            .outerjoin(Ratings, (Ratings.media_id == Media.id) & (Ratings.user_id == user_id))
            .outerjoin(genres, genres.c.media_id == Media.id)
            .outerjoin(studios, studios.c.media_id == Media.id)
            .outerjoin(franchise, franchise.c.anime_id == Media.anime_id)
            .where(Watchlist.user_id == user_id)
            .order_by(*recency_order(Watchlist))
        )
        return (await db.execute(stmt)).all()

    # --- All-users aggregates (admin Overview; no per-user breakdown) ---

    async def count_total(self, db: AsyncSession) -> int:
        """Total watchlist entries (media) across all users."""
        return (await db.execute(select(func.count(Watchlist.id)))).scalar_one()

    async def count_distinct_anime(self, db: AsyncSession) -> int:
        """Distinct anime represented on any user's watchlist."""
        stmt = select(func.count(func.distinct(Media.anime_id))).select_from(Watchlist).join(
            Media, Watchlist.media_id == Media.id
        )
        return (await db.execute(stmt)).scalar_one()

    async def count_distinct_users(self, db: AsyncSession) -> int:
        """Users with at least one watchlist entry."""
        return (
            await db.execute(select(func.count(func.distinct(Watchlist.user_id))))
        ).scalar_one()

    async def count_modified_since(self, db: AsyncSession, cutoff: datetime) -> int:
        """Watchlist entries added OR updated since `cutoff` — the 7d
        "watchlist modifications" activity counter. `modified_at` (server
        `onupdate=now()`) covers both an add (sets created_at + modified_at)
        and a priority/tag/note edit (bumps modified_at only)."""
        return (
            await db.execute(
                select(func.count(Watchlist.id)).where(Watchlist.modified_at >= cutoff)
            )
        ).scalar_one()

    async def get_watchlisted_media_tags(self, db: AsyncSession, user_id: int) -> list:
        """(media_uuid, anime_uuid, tag_uuid, tag_name, tag_color) for every entry on the
        user's watchlist — the icon-state set (mirrors spoiler-visibility), carrying the tag
        so the bookmark renders in the tag's color, and the anime_uuid so the frontend can
        aggregate an anime's distinct tag colors (solid, or a gradient when it spans tags).
        Projection, no ORM rows."""
        stmt = (
            select(Media.uuid, Anime.uuid, Tag.uuid, Tag.name, Tag.color)
            .join(Watchlist, Watchlist.media_id == Media.id)
            .join(Tag, Tag.id == Watchlist.tag_id)
            .join(Anime, Anime.id == Media.anime_id)
            .where(Watchlist.user_id == user_id)
        )
        return (await db.execute(stmt)).all()

    async def bulk_delete_by_user_and_media_ids(
        self, db: AsyncSession, user_id: int, media_ids: list[int]
    ) -> int:
        """Single-statement bulk delete. Returns rows deleted."""
        if not media_ids:
            return 0
        stmt = delete(Watchlist).where(
            Watchlist.user_id == user_id, Watchlist.media_id.in_(media_ids)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    # --- Tag-scoped operations (back the Tags tab counts + delete/empty guards) ---

    async def counts_by_tag(self, db: AsyncSession, user_id: int) -> dict[int, tuple[int, int]]:
        """Per-tag {tag_id: (media_count, distinct_anime_count)} for the user.

        media_count drives the Tags-tab entry badge; anime_count drives the
        removal-count guard (tag-scoped removals warn in anime terms)."""
        result = await db.execute(
            select(
                Watchlist.tag_id,
                func.count().label("media_count"),
                func.count(func.distinct(Media.anime_id)).label("anime_count"),
            )
            .join(Media, Media.id == Watchlist.media_id)
            .where(Watchlist.user_id == user_id)
            .group_by(Watchlist.tag_id)
        )
        return {row.tag_id: (row.media_count, row.anime_count) for row in result.all()}

    async def counts_for_tag(
        self, db: AsyncSession, user_id: int, tag_id: int
    ) -> tuple[int, int]:
        """(media_count, distinct_anime_count) for a single tag — scoped variant of
        counts_by_tag for when only one tag's counts are needed (e.g. after an edit)."""
        result = await db.execute(
            select(
                func.count(),
                func.count(func.distinct(Media.anime_id)),
            )
            .select_from(Watchlist)
            .join(Media, Media.id == Watchlist.media_id)
            .where(Watchlist.user_id == user_id, Watchlist.tag_id == tag_id)
        )
        media_count, anime_count = result.one()
        return media_count, anime_count

    async def reassign_tag(
        self, db: AsyncSession, user_id: int, from_tag_id: int, to_tag_id: int
    ) -> int:
        """Move all of a tag's entries to another tag. Safe against the
        unique(user_id, media_id) constraint: a media has exactly one entry, so
        changing its tag_id can never collide. Returns rows moved."""
        result = await db.execute(
            update(Watchlist)
            .where(Watchlist.user_id == user_id, Watchlist.tag_id == from_tag_id)
            .values(tag_id=to_tag_id)
        )
        await db.flush()
        return result.rowcount

    async def delete_all_by_user_and_tag_id(
        self, db: AsyncSession, user_id: int, tag_id: int
    ) -> int:
        """Delete every watchlist entry under a tag. Returns rows deleted."""
        result = await db.execute(
            delete(Watchlist).where(
                Watchlist.user_id == user_id, Watchlist.tag_id == tag_id
            )
        )
        await db.flush()
        return result.rowcount
