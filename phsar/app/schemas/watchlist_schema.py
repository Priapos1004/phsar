from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.common_schema import BulkMediaUuids


class WatchlistBase(BaseModel):
    """Shared core watchlist fields. priority + tag are non-optional (the UI defaults
    priority to 3 and preselects the default tag), so a value is always stored."""
    priority: int = 3
    note: str | None = None
    tag_uuid: UUID

    @field_validator("priority")
    @classmethod
    def priority_in_range(cls, v: int) -> int:
        if not 1 <= v <= 3:
            raise ValueError("Priority must be between 1 (high) and 3 (low)")
        return v

    @field_validator("note")
    @classmethod
    def note_max_length(cls, v: str | None) -> str | None:
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
    note: str | None
    tag: TagMini
    media_uuid: UUID
    media_title: str
    media_cover_image: str | None
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
    media_name_eng: str | None
    media_name_jap: str | None
    anime_title: str
    anime_name_eng: str | None
    anime_name_jap: str | None
    media_cover_image: str | None
    anime_cover_image: str | None
    priority: int
    note: str | None
    tag_uuid: UUID
    tag_name: str
    tag_color: str
    relation_type: str
    anime_season_name: str | None
    anime_season_year: int | None
    mal_id: int
    # Per-media genres + studios (eager-loaded by get_all_for_items) so the Statistics
    # subtab can tally top genres/studios client-side off this one fetch.
    genres: list[str]
    studios: list[str]
    # For the Statistics "queued time" figure: full runtime = episodes × duration_seconds
    # (watchlist media are unwatched, so it's the time queued up, not watched).
    episodes: int | None
    duration_seconds: int | None
    created_at: datetime
    modified_at: datetime


class WatchlistBulkCreate(WatchlistBase, BulkMediaUuids):
    """Bulk add/update. Priority + list apply to every selected media; the note goes on
    the chronologically-first main media only — the mirror of RatingBulkCreate, which
    places its note on the last main."""
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
