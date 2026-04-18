from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_user_or_admin
from app.exceptions import InvalidSearchTypeError
from app.models.media import MediaType, RelationType
from app.models.ratings import (
    AnimationQuality,
    CharacterDepth,
    DialogueQuality,
    EndingQuality,
    EndingType,
    FanService,
    Originality,
    Pace,
    StoryQuality,
    ThreeDAnimation,
    WatchedFormat,
)
from app.models.user_settings import SpoilerLevel
from app.schemas.anime_schema import AnimeSearchResult
from app.schemas.media_filter_schema import MediaSearchFilters, SearchType
from app.schemas.media_schema import MediaConnected
from app.schemas.rating_schema import RatedMediaResult, RatingSearchFilters
from app.schemas.search_schema import SearchResultDB
from app.services.anime_search_service import search_anime_by_query
from app.services.media_search_service import search_media_by_query
from app.services.rating_service import search_user_ratings
from app.services.search_service import handle_search_mal_api_results
from app.services.spoiler_service import get_visible_media_ids
from app.services.user_settings_service import get_settings

router = APIRouter(prefix="/search", tags=["search"])


def get_media_filters(
    relation_type: Optional[list[RelationType]] = Query(default=None),
    media_type: Optional[list[MediaType]] = Query(default=None),
    age_rating: Optional[list[str]] = Query(default=None),
    airing_status: Optional[list[str]] = Query(default=None),
    anime_season: Optional[list[str]] = Query(default=None),
    genre_name: Optional[list[str]] = Query(default=None),
    studio_name: Optional[list[str]] = Query(default=None),
    score_min: Optional[float] = None,
    score_max: Optional[float] = None,
    scored_by_min: Optional[int] = None,
    scored_by_max: Optional[int] = None,
    episodes_min: Optional[int] = None,
    episodes_max: Optional[int] = None,
    duration_per_episode_min: Optional[int] = None,
    duration_per_episode_max: Optional[int] = None,
    total_watch_time_min: Optional[int] = None,
    total_watch_time_max: Optional[int] = None,
) -> MediaSearchFilters:
    return MediaSearchFilters(
        relation_type=relation_type,
        media_type=media_type,
        age_rating=age_rating,
        airing_status=airing_status,
        anime_season=anime_season,
        genre_name=genre_name,
        studio_name=studio_name,
        score_min=score_min,
        score_max=score_max,
        scored_by_min=scored_by_min,
        scored_by_max=scored_by_max,
        episodes_min=episodes_min,
        episodes_max=episodes_max,
        duration_per_episode_min=duration_per_episode_min,
        duration_per_episode_max=duration_per_episode_max,
        total_watch_time_min=total_watch_time_min,
        total_watch_time_max=total_watch_time_max,
    )


def get_rating_filters(
    media_filters: MediaSearchFilters = Depends(get_media_filters),
    user_rating_min: Optional[float] = None,
    user_rating_max: Optional[float] = None,
    dropped: Optional[bool] = None,
    pace: Optional[list[Pace]] = Query(default=None),
    animation_quality: Optional[list[AnimationQuality]] = Query(default=None),
    has_3d_animation: Optional[list[ThreeDAnimation]] = Query(default=None),
    watched_format: Optional[list[WatchedFormat]] = Query(default=None),
    fan_service: Optional[list[FanService]] = Query(default=None),
    dialogue_quality: Optional[list[DialogueQuality]] = Query(default=None),
    character_depth: Optional[list[CharacterDepth]] = Query(default=None),
    ending_type: Optional[list[EndingType]] = Query(default=None),
    ending_quality: Optional[list[EndingQuality]] = Query(default=None),
    story_quality: Optional[list[StoryQuality]] = Query(default=None),
    originality: Optional[list[Originality]] = Query(default=None),
) -> RatingSearchFilters:
    return RatingSearchFilters(
        **media_filters.model_dump(),
        user_rating_min=user_rating_min,
        user_rating_max=user_rating_max,
        dropped=dropped,
        pace=pace,
        animation_quality=animation_quality,
        has_3d_animation=has_3d_animation,
        watched_format=watched_format,
        fan_service=fan_service,
        dialogue_quality=dialogue_quality,
        character_depth=character_depth,
        ending_type=ending_type,
        ending_quality=ending_quality,
        story_quality=story_quality,
        originality=originality,
    )


@router.get("/anime", response_model=list[AnimeSearchResult])
async def search_anime(
    query: str = Query(default="", description="Search query string."),
    search_type: SearchType = Query(default=SearchType.TITLE, description="Search by title or description."),
    filters: MediaSearchFilters = Depends(get_media_filters),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if search_type == SearchType.RATING_NOTES:
        raise InvalidSearchTypeError(search_type.value)

    return await search_anime_by_query(
        db=db,
        query=query,
        filters=filters,
        search_type=search_type,
    )


@router.get("/mal", response_model=list[SearchResultDB])
async def search_mal(
    query: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    return await handle_search_mal_api_results(query=query, db=db)


@router.get("/media", response_model=list[MediaConnected])
async def search_media(
    query: str = Query(default="", description="The search query string (e.g., anime title)."),
    search_type: SearchType = Query(default=SearchType.TITLE, description="The way to search by: title or description."),
    filters: MediaSearchFilters = Depends(get_media_filters),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if search_type == SearchType.RATING_NOTES:
        raise InvalidSearchTypeError(search_type.value)

    # Hide mode: only show media within the spoiler frontier
    visible_media_ids = None
    settings = await get_settings(db, current_user.id)
    if settings.spoiler_level == SpoilerLevel.hide:
        visible_media_ids = await get_visible_media_ids(db, current_user.id)

    return await search_media_by_query(
        db=db,
        query=query,
        filters=filters,
        search_type=search_type,
        visible_media_ids=visible_media_ids,
    )


@router.get("/ratings", response_model=list[RatedMediaResult])
async def search_ratings(
    query: str = Query(default="", description="Search query (matched against selected search type)."),
    search_type: SearchType = Query(default=SearchType.TITLE, description="What to search: title, description, or rating_notes."),
    filters: RatingSearchFilters = Depends(get_rating_filters),
    limit: int = Query(default=50, ge=1, le=200),
    current_user=Depends(require_user_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Search within the current user's ratings. Supports all media filters
    plus rating-specific filters (enums, user rating range, dropped status)."""
    return await search_user_ratings(
        db=db,
        user_id=current_user.id,
        query=query,
        filters=filters,
        search_type=search_type,
        limit=limit,
    )
