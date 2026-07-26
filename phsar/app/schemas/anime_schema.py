from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AnimeRecentItem(BaseModel):
    """Lightweight anime card for the /library/add 'recent additions' panel.

    Carries the localized-title fields so the frontend can apply the user's
    name_language preference without an extra fetch.
    """
    model_config = ConfigDict(from_attributes=True)

    uuid: UUID
    title: str
    name_eng: str | None = None
    name_jap: str | None = None
    cover_image: str | None = None
    created_at: datetime


class AnimeBase(BaseModel):
    title: str
    name_eng: str | None
    name_jap: str | None
    other_names: list[str] = []
    description: str | None
    cover_image: str | None

class AnimeCreate(AnimeBase):
    pass

class AnimeOut(AnimeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    uuid: UUID


# --- Anime search result schemas ---

class RelationTypeSummary(BaseModel):
    relation_type: str
    count: int

class MediaTypeSummary(BaseModel):
    media_type: str
    count: int

class AnimeAggregatedBase(BaseModel):
    """Shared aggregated fields for anime search results and detail views."""
    uuid: UUID
    title: str
    name_eng: str | None = None
    name_jap: str | None = None
    cover_image: str | None = None
    # Aggregated fields
    avg_score: float | None = None
    avg_scored_by: int = 0
    total_episodes: int | None = None
    total_watch_time: int | None = None
    media_count: int = 0
    # Breakdown badges
    relation_types: list[RelationTypeSummary] = []
    media_types: list[MediaTypeSummary] = []
    # Genres (strict majority) and studios (any)
    genres: list[str] = []
    studios: list[str] = []
    # Season range
    season_start: str | None = None
    season_end: str | None = None
    # Airing status
    airing_status: str = "Finished Airing"
    has_upcoming: bool = False
    # Age rating (max across media)
    age_rating_numeric: int | None = None
    # Admin-set story-complete flag (presence of an anime_completion row)
    is_finished: bool = False


class AnimeSearchResult(AnimeAggregatedBase):
    """Aggregated anime search result for the search card."""
    pass


# --- Anime detail schemas ---

class AnimeMediaItem(BaseModel):
    """Media item within an anime detail view."""
    uuid: UUID
    title: str
    name_eng: str | None = None
    name_jap: str | None = None
    cover_image: str | None = None
    media_type: str
    relation_type: str
    score: float | None = None
    scored_by: int = 0
    episodes: int | None = None
    airing_status: str
    anime_season_name: str | None = None
    anime_season_year: int | None = None
    total_watch_time: int | None = None
    age_rating_numeric: int | None = None
    genres: list[str] = []
    studios: list[str] = []

class AnimeDetail(AnimeAggregatedBase):
    """Full anime detail with all media and aggregated metadata."""
    other_names: list[str] = []
    description: str | None = None
    # "Top N%" rank of this anime's confidence-weighted MAL score among all
    # scored anime in the catalog (None when unscored). Detail-only — not on
    # the search cards.
    score_top_percent: int | None = None
    # All media in this anime
    media: list[AnimeMediaItem] = []
