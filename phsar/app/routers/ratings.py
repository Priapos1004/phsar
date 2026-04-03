from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_roles
from app.models.users import RoleType
from app.schemas import rating_schema
from app.services import rating_service

router = APIRouter(prefix="/ratings", tags=["ratings"])

# Restricted users are read-only guests — they cannot create, modify, or view ratings
_rating_roles = require_roles([RoleType.User, RoleType.Admin])


@router.put("/media/{media_uuid}", response_model=rating_schema.RatingOut)
async def upsert_rating(
    media_uuid: UUID,
    data: rating_schema.RatingCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_rating_roles),
):
    """Create or update a rating for a media. Idempotent — always succeeds."""
    return await rating_service.upsert_rating(db, current_user.id, media_uuid, data)


@router.get("/media/{media_uuid}", response_model=rating_schema.RatingOut)
async def get_rating_for_media(
    media_uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_rating_roles),
):
    return await rating_service.get_rating_for_media(db, current_user.id, media_uuid)


@router.get("", response_model=list[rating_schema.RatingOut])
async def get_user_ratings(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_rating_roles),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    return await rating_service.get_user_ratings(db, current_user.id, limit, offset)


@router.delete("/{rating_uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rating(
    rating_uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_rating_roles),
):
    await rating_service.delete_rating(db, current_user.id, rating_uuid)


@router.put("/bulk", response_model=list[rating_schema.RatingOut])
async def bulk_upsert_ratings(
    data: rating_schema.RatingBulkCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(_rating_roles),
):
    """Create or update ratings for multiple media at once."""
    return await rating_service.bulk_upsert_ratings(db, current_user.id, data)
