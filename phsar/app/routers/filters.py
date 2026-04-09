from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, verify_url_token
from app.schemas.auth_schema import TokenPayload
from app.schemas.media_filter_schema import (
    ExtendedMediaSearchFilters,
    MediaFilterValues,
    ViewType,
)
from app.services.filter_service import fetch_filter_values
from app.services.token_service import generate_search_token

router = APIRouter(prefix="/filters", tags=["filters"])

@router.get("/options", response_model=MediaFilterValues)
async def get_filter_values(
    view_type: ViewType = Query(default=ViewType.ANIME),
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await fetch_filter_values(db, view_type=view_type)

@router.post("/create-token", response_model=TokenPayload)
async def create_search_token(
    filters: ExtendedMediaSearchFilters,
    current_user = Depends(get_current_user),
):
    return generate_search_token(filters)

@router.post("/verify-token", response_model=ExtendedMediaSearchFilters)
async def verify_search_token(
    payload: TokenPayload,
    current_user = Depends(get_current_user),
):
    decoded = verify_url_token(payload.token)
    decoded.pop("ver", None)
    return ExtendedMediaSearchFilters(**decoded)
