"""Admin "story complete" curation endpoints.

A manual flag (no detector): the admin searches the catalog via the existing
`/search/anime` endpoint, then marks/unmarks an anime as narratively complete.
Mounted under `/admin` by the parent router; router-level admin dep.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_roles
from app.models.users import RoleType
from app.schemas import admin_schema
from app.services import completion_service

require_admin = require_roles(RoleType.Admin)

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get(
    "/finished-anime",
    response_model=list[admin_schema.FinishedAnimeItem],
)
async def list_finished_anime(db: AsyncSession = Depends(get_db)):
    """Anime currently marked story-complete, newest mark first."""
    return await completion_service.list_finished(db)


@router.post("/finished-anime/{anime_uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def mark_finished_anime(
    anime_uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Mark an anime as story-complete (idempotent)."""
    await completion_service.mark_finished(db, anime_uuid, current_user.id)


@router.delete("/finished-anime/{anime_uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def unmark_finished_anime(anime_uuid: UUID, db: AsyncSession = Depends(get_db)):
    """Remove the story-complete flag."""
    await completion_service.unmark_finished(db, anime_uuid)
