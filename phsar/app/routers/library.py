from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.daos.anime_dao import AnimeDAO
from app.schemas.anime_schema import AnimeRecentItem

router = APIRouter(prefix="/library", tags=["library"])
anime_dao = AnimeDAO()


@router.get("/recent", response_model=list[AnimeRecentItem])
async def recent_additions(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Most-recently added anime, newest first. Used by /library/add to
    show what's been added so the user can see their scrapes landing."""
    return await anime_dao.list_recent(db, limit=limit)
