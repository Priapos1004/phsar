from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import BaseDAO
from app.models.anime import Anime
from app.models.media import Media
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.tag import Tag
from app.models.watchlist import Watchlist


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

    async def get_all_for_items(self, db: AsyncSession, user_id: int) -> list[Watchlist]:
        """All of a user's watchlist entries with media → anime + tag eager-loaded,
        for the overview page's one-fetch list + grid. Ordered modified_at desc.
        Also eager-loads genres + studios (only here, not the shared loader used by the
        lookup methods) so the Statistics subtab derives top genres/studios off the same
        fetch — mirrors RatingDAO.get_all_for_score_items."""
        stmt = (
            select(Watchlist)
            .filter_by(user_id=user_id)
            .options(
                *self._eager_load_options(),  # media→anime + tag (shared with the lookups)
                selectinload(Watchlist.media).selectinload(Media.media_genre).selectinload(MediaGenre.genre),
                selectinload(Watchlist.media).selectinload(Media.media_studio).selectinload(MediaStudio.studio),
            )
            .order_by(Watchlist.modified_at.desc())
        )
        return (await db.execute(stmt)).scalars().all()

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
