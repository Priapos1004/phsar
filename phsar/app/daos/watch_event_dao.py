from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.base_dao import BaseDAO
from app.models.watch_event import WatchEvent


class WatchEventDAO(BaseDAO[WatchEvent]):
    def __init__(self):
        super().__init__(WatchEvent)

    async def exists_for_user_media(self, db: AsyncSession, user_id: int, media_id: int) -> bool:
        """Whether the user has any logged watch event for this media — gates the
        'log the first completion only if no history yet' rule so a delete-then-re-rate
        doesn't mint a duplicate first event."""
        stmt = select(WatchEvent.id).where(
            WatchEvent.user_id == user_id, WatchEvent.media_id == media_id
        ).limit(1)
        result = await db.execute(stmt)
        return result.first() is not None

    async def create_event(self, db: AsyncSession, user_id: int, media_id: int) -> WatchEvent:
        """Append one watch event (server_default stamps watched_at = now())."""
        return await self.create(db, WatchEvent(user_id=user_id, media_id=media_id))

    async def delete_for_user_media(self, db: AsyncSession, user_id: int, media_ids: list[int]) -> int:
        """Delete all watch history for the given media (opt-in cascade on rating delete)."""
        if not media_ids:
            return 0
        stmt = delete(WatchEvent).where(
            WatchEvent.user_id == user_id, WatchEvent.media_id.in_(media_ids)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    async def counts_for_user_media_ids(
        self, db: AsyncSession, user_id: int, media_ids: list[int]
    ) -> dict[int, int]:
        """Batch watched_count (= number of events) per media for one user. Media with no
        events are absent from the map; callers default those to 0. Single grouped query —
        avoids N+1 when shaping a list of ratings."""
        if not media_ids:
            return {}
        stmt = (
            select(WatchEvent.media_id, func.count())
            .where(WatchEvent.user_id == user_id, WatchEvent.media_id.in_(media_ids))
            .group_by(WatchEvent.media_id)
        )
        result = await db.execute(stmt)
        return {media_id: count for media_id, count in result.all()}
