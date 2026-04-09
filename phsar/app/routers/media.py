from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.schemas.anime_schema import AnimeDetail
from app.schemas.media_schema import MediaDetail
from app.services.anime_search_service import get_anime_detail
from app.services.media_search_service import get_media_detail

router = APIRouter(prefix="/media", tags=["media"])


# Anime detail must be defined before /{media_uuid} so FastAPI matches
# the static "anime" segment instead of trying to parse it as a UUID.
@router.get("/anime/{anime_uuid}", response_model=AnimeDetail)
async def anime_detail(
    anime_uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await get_anime_detail(db, anime_uuid)


@router.get("/{media_uuid}", response_model=MediaDetail)
async def media_detail(
    media_uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await get_media_detail(db, media_uuid)
