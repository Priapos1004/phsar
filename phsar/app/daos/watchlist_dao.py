from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.base_dao import BaseDAO
from app.models.media import Media
from app.models.watchlist import Watchlist


class WatchlistDAO(BaseDAO[Watchlist]):
    def __init__(self):
        super().__init__(Watchlist)

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
