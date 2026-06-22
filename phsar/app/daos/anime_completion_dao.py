"""DAO for AnimeCompletion — the admin "story complete" flag.

Row-presence is the flag (see the model). `mark` is idempotent (no-op if already
marked); `unmark` deletes. The admin list eager-loads the anime + the marking admin
so the service can render the Completion-tab list.
"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import BaseDAO
from app.models.anime_completion import AnimeCompletion


class AnimeCompletionDAO(BaseDAO[AnimeCompletion]):
    def __init__(self):
        super().__init__(AnimeCompletion)

    async def get_by_anime_id(self, db: AsyncSession, anime_id: int) -> AnimeCompletion | None:
        stmt = select(AnimeCompletion).where(AnimeCompletion.anime_id == anime_id)
        return (await db.execute(stmt)).scalars().first()

    async def list_with_anime(self, db: AsyncSession) -> list[AnimeCompletion]:
        """All marked rows, newest first, with the anime (cover/title) + the marking
        admin eager-loaded for the Completion tab list. Frontend re-sorts client-side."""
        stmt = (
            select(AnimeCompletion)
            .options(
                selectinload(AnimeCompletion.anime),
                selectinload(AnimeCompletion.marked_by),
            )
            .order_by(AnimeCompletion.created_at.desc())
        )
        return list((await db.execute(stmt)).scalars().all())

    async def mark(self, db: AsyncSession, anime_id: int, user_id: int) -> None:
        """Idempotent: insert a completion row unless one already exists."""
        if await self.get_by_anime_id(db, anime_id) is None:
            await self.create(db, AnimeCompletion(anime_id=anime_id, marked_by_user_id=user_id))

    async def unmark(self, db: AsyncSession, anime_id: int) -> None:
        await db.execute(delete(AnimeCompletion).where(AnimeCompletion.anime_id == anime_id))
        await db.flush()
