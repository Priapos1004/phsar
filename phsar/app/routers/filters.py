from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, verify_url_token
from app.core.security import create_url_token
from app.schemas.auth_schema import TokenPayload
from app.schemas.media_filter_schema import (
    ExtendedMediaSearchFilters,
    MediaFilterValues,
)
from app.services.filter_service import fetch_filter_values

router = APIRouter(prefix="/filters", tags=["filters"])

@router.get("/options", response_model=MediaFilterValues)
async def get_filter_values(
    current_user = Depends(get_current_user), # Any role can access this endpoint
    db: AsyncSession = Depends(get_db)
):
    filters = await fetch_filter_values(db)
    return filters

@router.post("/create-token", response_model=TokenPayload)
async def create_search_token(
    filters: ExtendedMediaSearchFilters,
    current_user = Depends(get_current_user), # Any role can access this endpoint
):
    """
    Create a signed token for the given search filters.
    """
    token = create_url_token(filters.model_dump(exclude_unset=True))
    return TokenPayload(token=token)

@router.post("/verify-token", response_model=ExtendedMediaSearchFilters)
async def verify_search_token(
    payload: TokenPayload,
    current_user = Depends(get_current_user), # Any role can access this endpoint
):
    """
    Verify and decode a search token.
    """
    decoded = verify_url_token(payload.token)
    decoded.pop("ver", None)
    return ExtendedMediaSearchFilters(**decoded)
