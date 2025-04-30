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
    fsk: Optional[str]
    description: Optional[str]
    original_source: Optional[str]
    cover_image: Optional[str]
    score: Optional[float]
    scored_by: Optional[int]
    episodes: Optional[int]
    anime_season: Optional[str]
    airing_status: str
    aired_from: Optional[datetime]
    aired_to: Optional[datetime]
    duration: Optional[str]

class MediaCreate(MediaBase):
    anime_id: int

class MediaUnconnected(MediaBase):
    genres: list[str]
    studio: list[str]

class MediaConnected(MediaUnconnected):
    anime_id: int
    anime_title: str

class MediaOut(MediaBase):
    id: int
    uuid: UUID
    anime_id: int

    class Config:
        orm_mode = True
