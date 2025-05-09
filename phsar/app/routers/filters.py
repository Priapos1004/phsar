from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.schemas.media_filter_schema import MediaFilterValues
from app.services.filter_service import fetch_filter_values

router = APIRouter(prefix="/filters", tags=["filters"])

@router.get("/", response_model=MediaFilterValues)
async def get_filter_values(
    current_user = Depends(get_current_user), # Any role can access this endpoint
    db: AsyncSession = Depends(get_db)
):
    filters = await fetch_filter_values(db)
    return filters
