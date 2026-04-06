from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class AnimeBase(BaseModel):
    title: str
    name_eng: Optional[str]
    name_jap: Optional[str]
    other_names: list[str] = []
    description: Optional[str]
    cover_image: Optional[str]

class AnimeCreate(AnimeBase):
    pass

class AnimeOut(AnimeBase):
    id: int
    uuid: UUID

    class Config:
        orm_mode = True


# --- Anime search result schemas ---

class RelationTypeSummary(BaseModel):
    relation_type: str
    count: int

class MediaTypeSummary(BaseModel):
    media_type: str
    count: int

class AnimeSearchResult(BaseModel):
    """Aggregated anime search result for the search card."""
    uuid: UUID
    title: str
    name_eng: Optional[str] = None
    name_jap: Optional[str] = None
    cover_image: Optional[str] = None
    # Aggregated fields
    avg_score: Optional[float] = None
    avg_scored_by: int = 0
    total_episodes: Optional[int] = None
    total_watch_time: Optional[int] = None
    media_count: int = 0
    # Breakdown badges
    relation_types: list[RelationTypeSummary] = []
    media_types: list[MediaTypeSummary] = []
    # Genres (strict majority) and studios (any)
    genres: list[str] = []
    studios: list[str] = []
    # Season range
    season_start: Optional[str] = None
    season_end: Optional[str] = None
    # Airing status
    airing_status: str = "Finished Airing"
    has_upcoming: bool = False
    # Age rating (max across media)
    age_rating_numeric: Optional[int] = None


# --- Anime detail schemas ---

class AnimeMediaItem(BaseModel):
    """Media item within an anime detail view."""
    uuid: UUID
    title: str
    name_eng: Optional[str] = None
    cover_image: Optional[str] = None
    media_type: str
    relation_type: str
    score: Optional[float] = None
    scored_by: int = 0
    episodes: Optional[int] = None
    airing_status: str
    anime_season_name: Optional[str] = None
    anime_season_year: Optional[int] = None
    total_watch_time: Optional[int] = None
    age_rating_numeric: Optional[int] = None
    genres: list[str] = []
    studios: list[str] = []

class AnimeDetail(BaseModel):
    """Full anime detail with all media and aggregated metadata."""
    uuid: UUID
    title: str
    name_eng: Optional[str] = None
    name_jap: Optional[str] = None
    other_names: list[str] = []
    description: Optional[str] = None
    cover_image: Optional[str] = None
    # Aggregated metadata
    avg_score: Optional[float] = None
    avg_scored_by: int = 0
    total_episodes: Optional[int] = None
    total_watch_time: Optional[int] = None
    age_rating_numeric: Optional[int] = None
    # Breakdown badges
    relation_types: list[RelationTypeSummary] = []
    media_types: list[MediaTypeSummary] = []
    genres: list[str] = []
    studios: list[str] = []
    airing_status: str = "Finished Airing"
    has_upcoming: bool = False
    season_start: Optional[str] = None
    season_end: Optional[str] = None
    # All media in this anime
    media: list[AnimeMediaItem] = []
