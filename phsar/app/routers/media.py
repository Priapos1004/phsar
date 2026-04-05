from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.schemas.media_schema import MediaDetail
from app.services.media_search_service import get_media_detail

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/{media_uuid}", response_model=MediaDetail)
async def media_detail(
    media_uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await get_media_detail(db, media_uuid)
