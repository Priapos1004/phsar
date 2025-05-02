from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.daos.media_dao import MediaDAO
from app.schemas.media_filter_schema import MediaSearchFilters, SearchType
from app.schemas.media_schema import MediaConnected
from app.schemas.search_schema import SearchResultDB
from app.services.media_search_service import search_media_by_query
from app.services.search_service import handle_search_mal_api_results
from app.services.unwanted_media_service import create_unwanted_media

router = APIRouter(prefix="/search", tags=["search"])

media_dao = MediaDAO()

@router.get("/mal", response_model=list[SearchResultDB])
async def search_mal(query: str, db: AsyncSession = Depends(get_db)):
    results = await handle_search_mal_api_results(query=query, db=db)
    return results

@router.get("/media", response_model=list[MediaConnected])
async def search_media(
    query: str = Query(default="", description="The search query string (e.g., anime title)."),
    search_type: SearchType = Query(default=SearchType.TITLE, description="The way to search by: title or description."),
    relation_type: Optional[list[str]] = Query(default=None),
    media_type: Optional[list[str]] = Query(default=None),
    fsk: Optional[list[str]] = Query(default=None),
    airing_status: Optional[list[str]] = Query(default=None),
    anime_season: Optional[list[str]] = Query(default=None),
    genre_name: Optional[list[str]] = Query(default=None),
    studio_name: Optional[list[str]] = Query(default=None),
    score_min: Optional[float] = None,
    score_max: Optional[float] = None,
    scored_by_min: Optional[int] = None,
    episodes_min: Optional[int] = None,
    episodes_max: Optional[int] = None,
    duration_per_episode_min: Optional[int] = None,
    duration_per_episode_max: Optional[int] = None,
    total_watch_time_min: Optional[int] = None,
    total_watch_time_max: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    filters = MediaSearchFilters(
        relation_type=relation_type,
        media_type=media_type,
        fsk=fsk,
        airing_status=airing_status,
        anime_season=anime_season,
        genre_name=genre_name,
        studio_name=studio_name,
        score_min=score_min,
        score_max=score_max,
        scored_by_min=scored_by_min,
        episodes_min=episodes_min,
        episodes_max=episodes_max,
        duration_per_episode_min=duration_per_episode_min,
        duration_per_episode_max=duration_per_episode_max,
        total_watch_time_min=total_watch_time_min,
        total_watch_time_max=total_watch_time_max,
    )

    return await search_media_by_query(
        db=db,
        query=query,
        filters=filters,
        search_type=search_type,
    )
