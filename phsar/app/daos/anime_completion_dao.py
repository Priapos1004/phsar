"""DAO for AnimeCompletion — the admin "story complete" flag.

Row-presence is the flag (see the model). `mark` is idempotent (no-op if already
marked); `unmark` deletes. The admin list eager-loads the anime + the marking admin
so the service can render the Completion-tab list.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.daos.base_dao import BaseDAO
from app.models.anime_completion import AnimeCompletion


class AnimeCompletionDAO(BaseDAO[AnimeCompletion]):
    def __init__(self):
        super().__init__(AnimeCompletion)

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
        """Idempotent insert. ON CONFLICT DO NOTHING on the unique anime_id makes it robust
        under concurrent marks (a check-then-insert could still race to an IntegrityError).
        Mirrors the merge/split candidate upsert DAOs — SQLAlchemy applies the model's
        Python-side uuid default for the omitted column."""
        stmt = (
            pg_insert(AnimeCompletion)
            .values(anime_id=anime_id, marked_by_user_id=user_id)
            .on_conflict_do_nothing(index_elements=["anime_id"])
        )
        await db.execute(stmt)
        await db.flush()

    async def unmark(self, db: AsyncSession, anime_id: int) -> None:
        await self.delete_all_by_field(db, "anime_id", [anime_id])
