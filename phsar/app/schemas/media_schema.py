from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.media import MediaType, RelationType


class MediaBase(BaseModel):
    mal_id: int
    mal_url: str
    title: str
    name_eng: str | None
    name_jap: str | None
    other_names: list[str] = []
    media_type: MediaType
    relation_type: RelationType
    age_rating: str | None
    description: str | None
    original_source: str | None
    cover_image: str | None
    score: float | None
    scored_by: int
    episodes: int | None
    anime_season_name: str | None
    anime_season_year: int | None
    airing_status: str
    aired_from: datetime | None
    aired_to: datetime | None
    duration: str | None
    duration_seconds: int | None

class MediaCreate(MediaBase):
    anime_id: int

class MediaUnconnected(MediaBase):
    genres: list[str]
    studio: list[str]

class MediaConnected(MediaUnconnected):
    anime_uuid: UUID
    anime_title: str
    anime_name_eng: str | None
    anime_name_jap: str | None
    anime_other_names: list[str] = []
    uuid: UUID
    total_watch_time: int | None
    age_rating_numeric: int | None


class MediaSibling(BaseModel):
    """Lightweight media representation for the related media carousel."""
    uuid: UUID
    title: str
    name_eng: str | None
    name_jap: str | None
    cover_image: str | None
    media_type: MediaType
    relation_type: RelationType
    episodes: int | None
    airing_status: str
    anime_season_name: str | None
    anime_season_year: int | None


class MediaDetail(MediaConnected):
    """Full media detail with sibling media from the same anime."""
    # "Top N%" rank of this media's confidence-weighted MAL score among all
    # scored media in the catalog (None when unscored). Detail-only.
    score_top_percent: int | None = None
    sibling_media: list[MediaSibling] = []
    # Insertion index for the "you are here" marker in the chronological
    # sibling order — 0 means the current media precedes every sibling,
    # len(sibling_media) means it follows them all. Required: 0 is a real
    # position, so a default would mask a missing field.
    current_position: int
