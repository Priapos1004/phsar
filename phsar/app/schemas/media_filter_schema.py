from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.config import settings
from app.models.media import AgeRating, MediaType, OriginalSource, RelationType
from app.models.ratings import WatchStatus

# A search query, stripped where it enters (route params and the search token):
# padding would otherwise become part of the title-match pattern. Capped because
# description search tests every word of it against every media's text.
SearchQuery = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


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
    AIRED = "aired"
    TITLE = "title"
    RANDOM = "random"
    YOUR_RATING = "your_rating"
    ANNOUNCED = "announced"


class SortDir(str, Enum):
    ASC = "asc"
    DESC = "desc"


class SortValueFields(BaseModel):
    """What a search result's sort orders it by, on both grains' results — each set only
    under that sort (`filter_service.sort_values`)."""
    score_top_percent: int | None = None
    sort_season: str | None = None
    announced_at: datetime | None = None
    announced_type: MediaType | None = None
    your_rating: float | None = None


class MatchMode(str, Enum):
    """Whether a row needs one of the selected values or every one of them."""
    ANY = "any"
    ALL = "all"


class GenreGroup(BaseModel):
    """Any or all of `include` (`mode`), and not any or not all of `exclude`
    (`exclude_mode`): "without Drama & Comedy" under `all` drops only a row carrying both."""
    model_config = ConfigDict(extra="forbid")
    mode: MatchMode = MatchMode.ALL
    include: list[str] = Field(default_factory=list, max_length=settings.MAX_ITEMS)
    exclude_mode: MatchMode = MatchMode.ANY
    exclude: list[str] = Field(default_factory=list, max_length=settings.MAX_ITEMS)

    @model_validator(mode="after")
    def _names_a_genre(self) -> "GenreGroup":
        # An empty group would match every row, so under `any` it would void its siblings.
        if not (self.include or self.exclude):
            raise ValueError("a genre group needs a genre to include or exclude")
        return self


# This many groups covers what a search asks for; an expression needing more is one whose
# rewrite into groups blew up, and the sheet has no room to show it either.
MAX_GENRE_GROUPS = 3


class GenreFilter(BaseModel):
    """Genre groups joined by `mode`: any of them, or every one.

    One level of groups is complete — any boolean expression over genres rewrites as an
    `any` of `all` groups, its negated genres under `exclude` — so the sheet never nests.
    `any` is the default as the reading people expect of alternatives; `all` stays for
    "one from each family" — (Shounen or Seinen) and (Fantasy or Sci-Fi) — which as
    alternatives takes a group per combination, past the cap."""
    model_config = ConfigDict(extra="forbid")
    mode: MatchMode = MatchMode.ANY
    groups: list[GenreGroup] = Field(min_length=1, max_length=MAX_GENRE_GROUPS)


class RatedState(str, Enum):
    """How far the caller has got with a row. An anime's state comes from its media's
    ratings (`rating_service._rated_state`, docs/features/ratings.md); a media's is its
    own rating's watch status, so each grain takes its own subset below."""
    NONE = "none"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    DROPPED = "dropped"
    MAIN = "main"
    ALL = "all"
    COMPLETED = "completed"


ANIME_RATED_STATES = frozenset({
    RatedState.NONE, RatedState.IN_PROGRESS, RatedState.ON_HOLD, RatedState.DROPPED, RatedState.MAIN, RatedState.ALL,
})
MEDIA_RATED_STATES = frozenset({RatedState.NONE, *(RatedState(status.value) for status in WatchStatus)})


class MediaSearchFilters(BaseModel):
    relation_type: list[RelationType] | None = None
    media_type: list[MediaType] | None = None
    age_rating: list[AgeRating] | None = None
    airing_status: list[str] | None = None
    anime_season: list[str] | None = None
    studio_name: list[str] | None = None
    original_source: list[OriginalSource] | None = None
    genres: GenreFilter | None = None

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
    studio_mode: MatchMode = MatchMode.ANY


class CatalogueSearchFilters(MediaSearchFilters):
    """The filters only the catalogue searches take, beyond the `MediaSearchFilters`
    every filtered search shares."""
    upcoming_main: bool = False
    # The caller's own: a union of states, and listed or not (None filters nothing).
    rated: list[RatedState] | None = None
    watchlisted: bool | None = None


class ExtendedMediaSearchFilters(CatalogueSearchFilters):
    query: SearchQuery = ""
    search_type: SearchType = SearchType.TITLE
    view_type: ViewType = ViewType.ANIME
    # None = the endpoints' own defaults (relevance; each key's own direction).
    sort: SortKey | None = None
    sort_dir: SortDir | None = None

    @model_validator(mode="before")
    @classmethod
    def _fold_flat_genres(cls, data: Any) -> Any:
        """A search token never expires, so a shared link may carry the flat
        `genre_name` + `genre_mode` pair: it reads as one group. Left to `extra`, the pair
        would be ignored and the link would lose its genre filter without a word. Here and
        not on the search filters, so a carousel's strict params still reject the pair."""
        if not isinstance(data, dict) or not ({"genre_name", "genre_mode"} & data.keys()):
            return data
        data = dict(data)
        names, mode = data.pop("genre_name", None), data.pop("genre_mode", None)
        if names and not data.get("genres"):
            data["genres"] = {"groups": [{"mode": mode or MatchMode.ALL, "include": names}]}
        return data

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
