from typing import Optional

from pydantic import BaseModel


class MediaSearchFilters(BaseModel):
    relation_type: Optional[list[str]] = None
    media_type: Optional[list[str]] = None
    fsk: Optional[list[str]] = None
    airing_status: Optional[list[str]] = None
    anime_season: Optional[list[str]] = None
    genre_name: Optional[list[str]] = None
    studio_name: Optional[list[str]] = None

    score_min: Optional[float] = None
    score_max: Optional[float] = None
    scored_by_min: Optional[int] = None
    episodes_min: Optional[int] = None
    episodes_max: Optional[int] = None
