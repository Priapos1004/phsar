from datetime import datetime
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
from app.schemas.common_schema import BulkMediaUuids
from app.schemas.media_filter_schema import MediaSearchFilters
from app.schemas.media_schema import MediaConnected


class RatingAttributes(BaseModel):
    """Shared optional rating attribute fields used across all rating schemas."""
    pace: Pace | None = None
    animation_quality: AnimationQuality | None = None
    has_3d_animation: ThreeDAnimation | None = None
    watched_format: WatchedFormat | None = None
    fan_service: FanService | None = None
    dialogue_quality: DialogueQuality | None = None
    character_depth: CharacterDepth | None = None
    ending_type: EndingType | None = None
    ending_quality: EndingQuality | None = None
    story_quality: StoryQuality | None = None
    originality: Originality | None = None


class RatingBase(RatingAttributes):
    """Shared core rating fields and validators for create schemas.

    Deliberately does NOT carry watch_status / episodes_watched: those are per-media
    watch state, part of the single-rating contract (RatingCreate) only. Bulk rating
    (RatingBulkCreate) is a whole-anime 'I finished this' action pinned to completed /
    full-run in the service, so exposing them on the bulk payload would advertise inputs
    the endpoint ignores."""
    rating: float
    note: str | None = None

    @field_validator("rating")
    @classmethod
    def rating_in_range(cls, v: float) -> float:
        if not 0 <= v <= 10:
            raise ValueError("Rating must be between 0 and 10")
        return v

    @field_validator("note")
    @classmethod
    def note_max_length(cls, v: str | None) -> str | None:
        if v is not None and len(v) > 1000:
            raise ValueError("Note must be at most 1000 characters")
        return v


class RatingCreate(RatingBase):
    # Per-media watch state — single-rating only (bulk pins completed / full-run itself).
    watch_status: WatchStatus = WatchStatus.completed
    episodes_watched: int | None = None

    @field_validator("episodes_watched")
    @classmethod
    def episodes_watched_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("Episodes watched must be non-negative")
        return v


class RatingOut(RatingAttributes):
    uuid: UUID
    rating: float
    watch_status: WatchStatus
    watched_count: int
    episodes_watched: int | None
    note: str | None
    media_uuid: UUID
    media_title: str
    media_cover_image: str | None
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

    Every field is a scalar, which is what lets
    RatingDAO.get_all_for_score_items fetch the whole set as one flat projection
    (genres/studios as aggregated arrays) with no ORM hydration. Keep it that
    way: a field needing a relationship traversal would reintroduce the
    per-collection round trips. watched_count stays out by design (it needs the
    per-media watch-event count batch this query deliberately skips);
    episodes_watched is on
    the rating row itself, so it ships freely and powers the actual-watched-time
    stats alongside the per-episode duration_seconds."""

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
    rating: float
    watch_status: WatchStatus
    episodes_watched: int | None
    age_rating_numeric: int | None
    genres: list[str] = []
    studios: list[str] = []
    # MAL score + vote count power the You-vs-MAL alignment scatter (point weight =
    # log10(scored_by + 1), the shared confidence weight). mal_score is None when
    # MAL has no score; scored_by is never None (0 when no votes).
    mal_score: float | None
    scored_by: int
    # Watch-time stats: episodes is the catalog total, duration_seconds the per-episode
    # runtime. Actual watched time = episodes_watched × duration_seconds (credited for
    # every status, so on-hold/dropped partials count). duration_seconds is carried
    # directly instead of the full-series total_watch_time so the stat still works for a
    # currently-airing show with no episode total (One Piece). anime_season_name + _year
    # feed the season filter (and the by-year breakdown); both are null together.
    episodes: int | None
    duration_seconds: int | None
    anime_season_name: str | None
    anime_season_year: int | None
    # Per-media relation type (main / alternative_version / side_story / …) → the
    # anime card's "X main · Y side" breakdown.
    relation_type: str
    # created_at drives the ratings-over-time timeline; modified_at is the final
    # deterministic tiebreak when two ratings are equally close in score and tie on
    # attributes/genre/studio/age.
    created_at: datetime
    modified_at: datetime


class RatingBulkCreate(RatingBase, BulkMediaUuids):
    # Note is attached to the last main media; earlier media get note cleared
    note: str | None = None


class RatingBulkDelete(BulkMediaUuids):
    pass


class RatingSearchFilters(MediaSearchFilters):
    """Extends media filters with rating-specific filters for searching within a user's ratings."""
    user_rating_min: float | None = None
    user_rating_max: float | None = None
    watch_status: list[WatchStatus] | None = None
    pace: list[Pace] | None = None
    animation_quality: list[AnimationQuality] | None = None
    has_3d_animation: list[ThreeDAnimation] | None = None
    watched_format: list[WatchedFormat] | None = None
    fan_service: list[FanService] | None = None
    dialogue_quality: list[DialogueQuality] | None = None
    character_depth: list[CharacterDepth] | None = None
    ending_type: list[EndingType] | None = None
    ending_quality: list[EndingQuality] | None = None
    story_quality: list[StoryQuality] | None = None
    originality: list[Originality] | None = None


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
    episodes_watched: int | None = None
    note: str | None = None
    rating_created_at: datetime
    rating_modified_at: datetime
