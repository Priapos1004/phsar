
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_user_or_admin
from app.exceptions import InvalidRatedStateError
from app.models.media import AgeRating, MediaType, OriginalSource, RelationType
from app.models.user_settings import SpoilerLevel
from app.models.users import Users
from app.schemas.anime_schema import AnimeSearchResult
from app.schemas.media_filter_schema import (
    ANIME_RATED_STATES,
    MEDIA_RATED_STATES,
    CatalogueSearchFilters,
    MatchMode,
    MediaSearchFilters,
    RatedState,
    SearchQuery,
    SearchType,
    SortDir,
    SortKey,
)
from app.schemas.media_schema import MediaSearchResult
from app.schemas.search_schema import SearchResultDB
from app.services.anime_search_service import search_anime_by_query
from app.services.media_search_service import search_media_by_query
from app.services.search_service import handle_search_mal_api_results
from app.services.spoiler_service import get_visible_media_ids
from app.services.user_settings_service import get_settings

router = APIRouter(prefix="/search", tags=["search"])

SearchLimit = Annotated[int, Query(ge=1, le=1000, description="How many results to return.")]
SortDirParam = Annotated[SortDir | None, Query(
    description="Direction; by default `title` and `release` ascend and the rest descend. "
    "Ignored with `relevance`.",
)]


def _check_rated_grain(filters: CatalogueSearchFilters, allowed: frozenset[RatedState]) -> None:
    if filters.rated and (foreign := [s.value for s in filters.rated if s not in allowed]):
        raise InvalidRatedStateError(foreign)


async def get_sort(
    sort: SortKey = Query(
        default=SortKey.RELEVANCE,
        description="Result order. `relevance` is the query's own match order, and `top_rated` "
        "without a query. Any other sort orders the same matching rows. `your_rating` is your "
        "rating of a media, or the mean over an anime's rated media; unrated last.",
    ),
    current_user: Users = Depends(get_current_user),
) -> SortKey:
    # Your ratings gate like the endpoints that read them (rules/backend.md, Roles).
    if sort == SortKey.YOUR_RATING:
        await require_user_or_admin(current_user)
    return sort


async def get_search_type(
    search_type: SearchType = Query(
        default=SearchType.TITLE,
        description="What the query matches.",
    ),
    current_user: Users = Depends(get_current_user),
) -> SearchType:
    # Gated on the mode, not the query, as `watchlisted=false` is on the filter alone.
    if search_type == SearchType.RATING_NOTES:
        await require_user_or_admin(current_user)
    return search_type


def get_media_filters(
    relation_type: list[RelationType] | None = Query(default=None),
    media_type: list[MediaType] | None = Query(default=None),
    age_rating: list[AgeRating] | None = Query(default=None),
    airing_status: list[str] | None = Query(default=None),
    anime_season: list[str] | None = Query(default=None),
    genre_name: list[str] | None = Query(default=None),
    studio_name: list[str] | None = Query(default=None),
    original_source: list[OriginalSource] | None = Query(default=None),
    score_min: float | None = None,
    score_max: float | None = None,
    scored_by_min: int | None = None,
    scored_by_max: int | None = None,
    episodes_min: int | None = None,
    episodes_max: int | None = None,
    duration_per_episode_min: int | None = None,
    duration_per_episode_max: int | None = None,
    total_watch_time_min: int | None = None,
    total_watch_time_max: int | None = None,
    top_percent: int | None = Query(
        default=None, ge=1, le=100,
        description="Keep the rows whose \"Top N%\" badge reads this percentage or better.",
    ),
    genre_mode: MatchMode = Query(
        default=MatchMode.ALL, description="Whether a row needs every selected genre or one of them.",
    ),
    studio_mode: MatchMode = Query(
        default=MatchMode.ANY, description="Whether a row needs one of the selected studios or every one.",
    ),
) -> MediaSearchFilters:
    return MediaSearchFilters(
        relation_type=relation_type,
        media_type=media_type,
        age_rating=age_rating,
        airing_status=airing_status,
        anime_season=anime_season,
        genre_name=genre_name,
        studio_name=studio_name,
        original_source=original_source,
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
        top_percent=top_percent,
        genre_mode=genre_mode,
        studio_mode=studio_mode,
    )


async def get_catalogue_filters(
    media_filters: MediaSearchFilters = Depends(get_media_filters),
    upcoming_main: bool = Query(
        default=False,
        description="Keep the anime that have aired content and an announced main-story entry; "
        "at the media grain, those announced main-story entries.",
    ),
    rated: list[RatedState] | None = Query(
        default=None,
        description="Keep the rows in any of these states of your ratings. Anime: `none`, "
        "`in_progress`, `on_hold`, `dropped`, `main`, `all`. Media: `none`, or your rating's watch status.",
    ),
    watchlisted: bool | None = Query(
        default=None, description="Keep the rows on your watchlist, or the rows off it; an anime is on it "
        "when any of its media is.",
    ),
    current_user: Users = Depends(get_current_user),
) -> CatalogueSearchFilters:
    if rated or watchlisted is not None:
        await require_user_or_admin(current_user)
    return CatalogueSearchFilters(
        **media_filters.model_dump(), upcoming_main=upcoming_main, rated=rated, watchlisted=watchlisted,
    )


@router.get("/anime", response_model=list[AnimeSearchResult])
async def search_anime(
    query: Annotated[SearchQuery, Query(description="Search query string.")] = "",
    search_type: SearchType = Depends(get_search_type),
    sort: SortKey = Depends(get_sort),
    sort_dir: SortDirParam = None,
    limit: SearchLimit = 50,
    filters: CatalogueSearchFilters = Depends(get_catalogue_filters),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _check_rated_grain(filters, ANIME_RATED_STATES)

    settings = await get_settings(db, current_user.id)
    return await search_anime_by_query(
        db=db,
        query=query,
        filters=filters,
        search_type=search_type,
        sort=sort,
        sort_dir=sort_dir,
        name_language=settings.name_language,
        limit=limit,
        user_id=current_user.id,
    )


@router.get("/mal", response_model=list[SearchResultDB])
async def search_mal(
    query: SearchQuery,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    # The route returns the legacy result-list shape unchanged; the new
    # attach_actions field is dispatcher-only (system jobs decide whether
    # to auto-attach; the public search route never does).
    result = await handle_search_mal_api_results(query=query, db=db)
    return result.search_result_db_list


@router.get("/media", response_model=list[MediaSearchResult])
async def search_media(
    query: Annotated[SearchQuery, Query(description="The search query string (e.g., anime title).")] = "",
    search_type: SearchType = Depends(get_search_type),
    sort: SortKey = Depends(get_sort),
    sort_dir: SortDirParam = None,
    limit: SearchLimit = 50,
    filters: CatalogueSearchFilters = Depends(get_catalogue_filters),
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _check_rated_grain(filters, MEDIA_RATED_STATES)

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
        user_id=current_user.id,
        sort=sort,
        sort_dir=sort_dir,
        name_language=settings.name_language,
        limit=limit,
        visible_media_ids=visible_media_ids,
    )
