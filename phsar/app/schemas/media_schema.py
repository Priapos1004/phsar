from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.models.media import MediaType, RelationType


class MediaBase(BaseModel):
    mal_id: int
    mal_url: str
    title: str
    name_eng: Optional[str]
    name_jap: Optional[str]
    other_names: list[str] = []
    media_type: MediaType
    relation_type: RelationType
    age_rating: Optional[str]
    description: Optional[str]
    original_source: Optional[str]
    cover_image: Optional[str]
    score: Optional[float]
    scored_by: int
    episodes: Optional[int]
    anime_season_name: Optional[str]
    anime_season_year: Optional[int]
    airing_status: str
    aired_from: Optional[datetime]
    aired_to: Optional[datetime]
    duration: Optional[str]
    duration_seconds: Optional[int]

class MediaCreate(MediaBase):
    anime_id: int

class MediaUnconnected(MediaBase):
    genres: list[str]
    studio: list[str]

class MediaConnected(MediaUnconnected):
    anime_uuid: UUID
    anime_title: str
    anime_name_eng: Optional[str]
    anime_name_jap: Optional[str]
    anime_other_names: list[str] = []
    uuid: UUID
    total_watch_time: Optional[int]
    age_rating_numeric: Optional[int]


class MediaSibling(BaseModel):
    """Lightweight media representation for the related media carousel."""
    uuid: UUID
    title: str
    name_eng: Optional[str]
    name_jap: Optional[str]
    cover_image: Optional[str]
    media_type: MediaType
    relation_type: RelationType
    episodes: Optional[int]
    airing_status: str
    anime_season_name: Optional[str]
    anime_season_year: Optional[int]


class MediaDetail(MediaConnected):
    """Full media detail with sibling media from the same anime."""
    sibling_media: list[MediaSibling] = []
