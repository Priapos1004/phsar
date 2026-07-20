from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.common_schema import BulkMediaUuids


class WatchlistBase(BaseModel):
    """Shared core watchlist fields. priority + tag are non-optional (the UI defaults
    priority to 3 and preselects the default tag), so a value is always stored."""
    priority: int = 3
    note: Optional[str] = None
    tag_uuid: UUID

    @field_validator("priority")
    @classmethod
    def priority_in_range(cls, v: int) -> int:
        if not 1 <= v <= 3:
            raise ValueError("Priority must be between 1 (high) and 3 (low)")
        return v

    @field_validator("note")
    @classmethod
    def note_max_length(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 1000:
            raise ValueError("Note must be at most 1000 characters")
        return v


class WatchlistCreate(WatchlistBase):
    pass


class TagMini(BaseModel):
    """The tag shape embedded in a watchlist entry response."""
    uuid: UUID
    name: str
    color: str

    model_config = ConfigDict(from_attributes=True)


class WatchlistOut(BaseModel):
    uuid: UUID
    priority: int
    note: Optional[str]
    tag: TagMini
    media_uuid: UUID
    media_title: str
    media_cover_image: Optional[str]
    anime_uuid: UUID
    anime_title: str
    created_at: datetime
    modified_at: datetime


class WatchlistItem(BaseModel):
    """Wide projection for the /watchlist overview page (list + grid derived from one
    fetch). Every field is a column on rows already eager-loaded by
    WatchlistDAO.get_all_for_items (media → anime + tag), so no extra query cost."""
    uuid: UUID
    media_uuid: UUID
    anime_uuid: UUID
    media_title: str
    media_name_eng: Optional[str]
    media_name_jap: Optional[str]
    anime_title: str
    anime_name_eng: Optional[str]
    anime_name_jap: Optional[str]
    media_cover_image: Optional[str]
    anime_cover_image: Optional[str]
    priority: int
    note: Optional[str]
    tag_uuid: UUID
    tag_name: str
    tag_color: str
    relation_type: str
    anime_season_name: Optional[str]
    anime_season_year: Optional[int]
    mal_id: int
    created_at: datetime
    modified_at: datetime


class WatchlistBulkCreate(WatchlistBase, BulkMediaUuids):
    """Bulk add/update. The note applies to ALL selected media — deliberately unlike
    RatingBulkCreate (which places it on one main media)."""
    pass


class WatchlistBulkDelete(BulkMediaUuids):
    pass


class WatchlistMediaTag(BaseModel):
    """One watchlisted media + the tag it's under — carries the tag so the bookmark
    icon renders in the tag's color, and the anime_uuid so the frontend can aggregate
    an anime's distinct tag colors (a gradient when it spans multiple tags)."""
    media_uuid: UUID
    anime_uuid: UUID
    tag_uuid: UUID
    tag_name: str
    tag_color: str


class WatchlistMediaTags(BaseModel):
    """The icon-state set: every watchlisted media with its tag (mirrors the
    spoiler-visibility set, plus the tag for coloring)."""
    entries: list[WatchlistMediaTag]
