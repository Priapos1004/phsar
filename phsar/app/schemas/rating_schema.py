from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.ratings import (
    AnimationQuality,
    CharacterDepth,
    DialogueQuality,
    EndingQuality,
    EndingType,
    FanService,
    Originality,
    Pace,
    StoryQuality,
    ThreeDAnimation,
    WatchedFormat,
    WatchStatus,
)
from app.schemas.media_filter_schema import MediaSearchFilters
from app.schemas.media_schema import MediaConnected


class RatingAttributes(BaseModel):
    """Shared optional rating attribute fields used across all rating schemas."""
    pace: Optional[Pace] = None
    animation_quality: Optional[AnimationQuality] = None
    has_3d_animation: Optional[ThreeDAnimation] = None
    watched_format: Optional[WatchedFormat] = None
    fan_service: Optional[FanService] = None
    dialogue_quality: Optional[DialogueQuality] = None
    character_depth: Optional[CharacterDepth] = None
    ending_type: Optional[EndingType] = None
    ending_quality: Optional[EndingQuality] = None
    story_quality: Optional[StoryQuality] = None
    originality: Optional[Originality] = None


class RatingBase(RatingAttributes):
    """Shared core rating fields and validators for create schemas."""
    rating: float
    watch_status: WatchStatus = WatchStatus.completed
    episodes_watched: Optional[int] = None
    note: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def rating_in_range(cls, v: float) -> float:
        if not 0 <= v <= 10:
            raise ValueError("Rating must be between 0 and 10")
        return v

    @field_validator("episodes_watched")
    @classmethod
    def episodes_watched_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Episodes watched must be non-negative")
        return v

    @field_validator("note")
    @classmethod
    def note_max_length(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 1000:
            raise ValueError("Note must be at most 1000 characters")
        return v


class RatingCreate(RatingBase):
    pass


class RatingOut(RatingAttributes):
    uuid: UUID
    rating: float
    watch_status: WatchStatus
    watched_count: int
    episodes_watched: Optional[int]
    note: Optional[str]
    media_uuid: UUID
    media_title: str
    media_cover_image: Optional[str]
    anime_uuid: UUID
    anime_title: str
    created_at: datetime
    modified_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RatingScoreItem(RatingAttributes):
    """Compact projection of one of a user's ratings. Two consumers, one query:

    1. The rating-consistency helper (RatingCard) — fetches the whole set once and
       does nearest-score selection + tiebreak client-side, so this ships the
       comparison inputs (anime_uuid to exclude/dedupe by anime, genres/studios/age
       for the tiebreak) alongside the 11 attribute fields (inherited).
    2. The /ratings page (list + statistics) — groups by anime client-side and
       derives every chart from this one fetch, so this also ships the anime cover,
       the MAL score/vote-count (You-vs-MAL alignment), watch-time + season-year
       (watch-time stats), and created_at (the ratings-over-time timeline).

    All fields are columns on rows already eager-loaded by
    RatingDAO.get_all_for_score_items (media → anime + genres + studios), so no
    extra query cost. watched_count/episodes_watched stay out by design (they'd
    need the per-media watch-event count batch this query deliberately skips)."""

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
    rating: float
    watch_status: WatchStatus
    age_rating_numeric: Optional[int]
    genres: list[str] = []
    studios: list[str] = []
    # MAL score + vote count power the You-vs-MAL alignment scatter (point weight =
    # log10(scored_by + 1), the shared confidence weight). mal_score is None when
    # MAL has no score; scored_by is never None (0 when no votes).
    mal_score: Optional[float]
    scored_by: int
    # Watch-time stats: episodes is the catalog total; total_watch_time is seconds
    # (episodes × duration_seconds). anime_season_name + _year feed the season filter
    # (and the by-year breakdown); both are null together (catalog constraint).
    episodes: Optional[int]
    total_watch_time: Optional[int]
    anime_season_name: Optional[str]
    anime_season_year: Optional[int]
    # Per-media relation type (main / alternative_version / side_story / …) → the
    # anime card's "X main · Y side" breakdown.
    relation_type: str
    # created_at drives the ratings-over-time timeline; modified_at is the final
    # deterministic tiebreak when two ratings are equally close in score and tie on
    # attributes/genre/studio/age.
    created_at: datetime
    modified_at: datetime


class _BulkMediaUuids(BaseModel):
    """Shared base for bulk operations: validates the media_uuids list."""
    media_uuids: list[UUID]

    @field_validator("media_uuids")
    @classmethod
    def validate_media_uuids(cls, v: list[UUID]) -> list[UUID]:
        if len(v) > 50:
            raise ValueError("Cannot bulk-operate on more than 50 media at once")
        if not v:
            raise ValueError("At least one media UUID is required")
        return v


class RatingBulkCreate(RatingBase, _BulkMediaUuids):
    # Note is attached to the last main media; earlier media get note cleared
    note: Optional[str] = None


class RatingBulkDelete(_BulkMediaUuids):
    pass


class RatingSearchFilters(MediaSearchFilters):
    """Extends media filters with rating-specific filters for searching within a user's ratings."""
    user_rating_min: Optional[float] = None
    user_rating_max: Optional[float] = None
    watch_status: Optional[list[WatchStatus]] = None
    pace: Optional[list[Pace]] = None
    animation_quality: Optional[list[AnimationQuality]] = None
    has_3d_animation: Optional[list[ThreeDAnimation]] = None
    watched_format: Optional[list[WatchedFormat]] = None
    fan_service: Optional[list[FanService]] = None
    dialogue_quality: Optional[list[DialogueQuality]] = None
    character_depth: Optional[list[CharacterDepth]] = None
    ending_type: Optional[list[EndingType]] = None
    ending_quality: Optional[list[EndingQuality]] = None
    story_quality: Optional[list[StoryQuality]] = None
    originality: Optional[list[Originality]] = None


class SpoilerVisibility(BaseModel):
    """Media UUIDs that are visible (not spoiler-protected) for the current user."""
    visible_media_uuids: list[UUID]


class RatedMediaResult(MediaConnected, RatingAttributes):
    """Media search result enriched with the user's rating data.
    Inherits media fields from MediaConnected and enum fields from RatingAttributes."""
    rating_uuid: UUID
    user_rating: float
    watch_status: WatchStatus
    watched_count: int
    episodes_watched: Optional[int] = None
    note: Optional[str] = None
    rating_created_at: datetime
    rating_modified_at: datetime
