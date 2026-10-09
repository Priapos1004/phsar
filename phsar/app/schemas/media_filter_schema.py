from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models.media import AgeRating, MediaType, OriginalSource, RelationType

# A search query, stripped where it enters (route params and the search token):
# padding would otherwise become part of the title-match pattern.
SearchQuery = Annotated[str, StringConstraints(strip_whitespace=True)]


class SearchType(str, Enum):
    TITLE = "title"
    DESCRIPTION = "description"
    RATING_NOTES = "rating_notes"


class ViewType(str, Enum):
    ANIME = "anime"
    MEDIA = "media"


class SortKey(str, Enum):
    RELEVANCE = "relevance"
    TOP_RATED = "top_rated"
    SCORE = "score"
    POPULARITY = "popularity"
    ADDED = "added"
    RELEASE = "release"
    TITLE = "title"
    RANDOM = "random"


class SortDir(str, Enum):
    ASC = "asc"
    DESC = "desc"


class MatchMode(str, Enum):
    """Whether a row needs one of the selected values or every one of them."""
    ANY = "any"
    ALL = "all"


class MediaSearchFilters(BaseModel):
    relation_type: list[RelationType] | None = None
    media_type: list[MediaType] | None = None
    age_rating: list[AgeRating] | None = None
    airing_status: list[str] | None = None
    anime_season: list[str] | None = None
    genre_name: list[str] | None = None
    studio_name: list[str] | None = None
    original_source: list[OriginalSource] | None = None

    score_min: float | None = None
    score_max: float | None = None
    scored_by_min: int | None = None
    scored_by_max: int | None = None
    episodes_min: int | None = None
    episodes_max: int | None = None
    duration_per_episode_min: int | None = None
    duration_per_episode_max: int | None = None
    total_watch_time_min: int | None = None
    total_watch_time_max: int | None = None

    top_percent: int | None = Field(default=None, ge=1, le=100)
    genre_mode: MatchMode = MatchMode.ALL
    studio_mode: MatchMode = MatchMode.ANY


class CatalogueSearchFilters(MediaSearchFilters):
    """The filters only the catalogue searches take, beyond the `MediaSearchFilters`
    every filtered search shares."""
    upcoming_main: bool = False


class ExtendedMediaSearchFilters(CatalogueSearchFilters):
    query: SearchQuery = ""
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
    original_source: list[str]

    # Numerical limits
    score_min: float | None
    score_max: float | None
    scored_by_min: int | None
    scored_by_max: int | None
    episodes_min: int | None
    episodes_max: int | None
    duration_per_episode_min: int | None
    duration_per_episode_max: int | None
    total_watch_time_min: int | None
    total_watch_time_max: int | None
