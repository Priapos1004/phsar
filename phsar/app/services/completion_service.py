"""Admin operations for the anime "story complete" flag.

Manual curation (no detection): an admin marks/unmarks an anime as
narratively concluded. The marked list reuses the shared `summarize_anime`
card projection so it renders like the merge/split admin cards.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.anime_completion_dao import AnimeCompletionDAO
from app.daos.anime_dao import AnimeDAO
from app.exceptions import AnimeNotFoundByUuidError
from app.schemas.admin_schema import FinishedAnimeItem

completion_dao = AnimeCompletionDAO()
anime_dao = AnimeDAO()


async def list_finished(db: AsyncSession) -> list[FinishedAnimeItem]:
    rows = await completion_dao.list_with_anime(db)
    return [
        FinishedAnimeItem(
            uuid=str(r.anime.uuid),
            title=r.anime.title,
            name_eng=r.anime.name_eng,
            name_jap=r.anime.name_jap,
            cover_image=r.anime.cover_image,
            marked_by_username=r.marked_by.username if r.marked_by else None,
            marked_at=r.created_at,
        )
        for r in rows
    ]


async def mark_finished(db: AsyncSession, anime_uuid: UUID, user_id: int) -> None:
    anime = await anime_dao.get_by_field(db, uuid=anime_uuid)
    if not anime:
        raise AnimeNotFoundByUuidError(str(anime_uuid))
    await completion_dao.mark(db, anime.id, user_id)
    await db.commit()


async def unmark_finished(db: AsyncSession, anime_uuid: UUID) -> None:
    anime = await anime_dao.get_by_field(db, uuid=anime_uuid)
    if not anime:
        raise AnimeNotFoundByUuidError(str(anime_uuid))
    await completion_dao.unmark(db, anime.id)
    await db.commit()
