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
    dropped: bool = False
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
    dropped: bool
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
    dropped: Optional[bool] = None
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


class RatedMediaResult(MediaConnected, RatingAttributes):
    """Media search result enriched with the user's rating data.
    Inherits media fields from MediaConnected and enum fields from RatingAttributes."""
    rating_uuid: UUID
    user_rating: float
    dropped: bool
    episodes_watched: Optional[int] = None
    note: Optional[str] = None
    rating_created_at: datetime
    rating_modified_at: datetime
