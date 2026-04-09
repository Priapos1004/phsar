from enum import Enum
from typing import Optional

from pydantic import BaseModel

from app.models.media import MediaType, RelationType


class SearchType(str, Enum):
    TITLE = "title"
    DESCRIPTION = "description"
    RATING_NOTES = "rating_notes"


class ViewType(str, Enum):
    ANIME = "anime"
    MEDIA = "media"


class MediaSearchFilters(BaseModel):
    relation_type: Optional[list[RelationType]] = None
    media_type: Optional[list[MediaType]] = None
    age_rating: Optional[list[str]] = None
    airing_status: Optional[list[str]] = None
    anime_season: Optional[list[str]] = None
    genre_name: Optional[list[str]] = None
    studio_name: Optional[list[str]] = None

    score_min: Optional[float] = None
    score_max: Optional[float] = None
    scored_by_min: Optional[int] = None
    scored_by_max: Optional[int] = None
    episodes_min: Optional[int] = None
    episodes_max: Optional[int] = None
    duration_per_episode_min: Optional[int] = None
    duration_per_episode_max: Optional[int] = None
    total_watch_time_min: Optional[int] = None
    total_watch_time_max: Optional[int] = None

class ExtendedMediaSearchFilters(MediaSearchFilters):
    query: str = ""
    search_type: SearchType = SearchType.TITLE
    view_type: ViewType = ViewType.ANIME

class MediaFilterValues(BaseModel):
    # Categorical fields
    relation_type: list[str]
    media_type: list[str]
    age_rating: list[str]
    airing_status: list[str]
    anime_season: list[str]
    genre_name: list[str]
    studio_name: list[str]

    # Numerical limits
    score_min: Optional[float]
    score_max: Optional[float]
    scored_by_min: Optional[int]
    scored_by_max: Optional[int]
    episodes_min: Optional[int]
    episodes_max: Optional[int]
    duration_per_episode_min: Optional[int]
    duration_per_episode_max: Optional[int]
    total_watch_time_min: Optional[int]
    total_watch_time_max: Optional[int]
