import enum

from sqlalchemy import (
    CheckConstraint,
    Column,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Pace(str, enum.Enum):
    slow = "slow"
    normal = "normal"
    fast = "fast"

class AnimationQuality(str, enum.Enum):
    bad = "bad"
    normal = "normal"
    good = "good"
    very_good = "very_good"

class ThreeDAnimation(str, enum.Enum):
    # Frequency/extent scale mirroring FanService (none/rare/medium/heavy) so the two
    # "amount of X" attributes share buckets. v0.14.13 renamed partial→medium, full→heavy
    # and added rare (the "occasional bursts" case, e.g. Overlord S3's last 2 eps).
    none = "none"
    rare = "rare"
    medium = "medium"
    heavy = "heavy"

class WatchedFormat(str, enum.Enum):
    sub = "sub"
    dub = "dub"
    both = "both"

class FanService(str, enum.Enum):
    none = "none"
    rare = "rare"
    medium = "medium"
    heavy = "heavy"

class DialogueQuality(str, enum.Enum):
    flat = "flat"
    normal = "normal"
    deep = "deep"

class CharacterDepth(str, enum.Enum):
    flat = "flat"
    normal = "normal"
    complex = "complex"

class EndingType(str, enum.Enum):
    open = "open"
    closed = "closed"
    cliffhanger = "cliffhanger"
    # Auto-set sentinel (never user-selectable) — set when the watch wasn't finished
    # (on_hold/dropped), alongside ending_quality. v0.14.13.
    not_applicable = "not_applicable"

class EndingQuality(str, enum.Enum):
    unsatisfying = "unsatisfying"
    # Middle anchor (v0.14.13) so an indifferent "it was okay" ending has its own value
    # instead of collapsing into a forced side or an ambiguous unset.
    neutral = "neutral"
    satisfying = "satisfying"
    very_satisfying = "very_satisfying"
    not_applicable = "not_applicable"

class StoryQuality(str, enum.Enum):
    weak = "weak"
    average = "average"
    good = "good"
    outstanding = "outstanding"

class Originality(str, enum.Enum):
    conventional = "conventional"
    unique = "unique"
    experimental = "experimental"


class WatchStatus(str, enum.Enum):
    """User's watch status for a media. Replaced the legacy `dropped` boolean
    in v0.14.10. `on_hold` is distinguished from `dropped` so a future
    "continue watching" surface can resume paused-but-not-abandoned shows.
    `on_hold` and `dropped` both carry `episodes_watched`."""
    completed = "completed"
    on_hold = "on_hold"
    dropped = "dropped"


class Ratings(BaseModel):
    __tablename__ = "ratings"

    # Rating: float between 0 and 10
    rating = Column(Float, nullable=False)

    # Foreign Key Media and Users
    media_id = Column(Integer, ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'media_id', name='unique_user_media_rating'),
        CheckConstraint("rating >= 0 AND rating <= 10", name="rating_range_check"),
    )

    # Optional note field
    note = Column(String(1000), nullable=True)

    # Number of episodes watched (relevant for on_hold / dropped)
    episodes_watched = Column(Integer, nullable=True)

    # Watch status — completed / on_hold / dropped (replaced the `dropped` boolean in v0.14.10)
    watch_status = Column(
        Enum(WatchStatus),
        nullable=False,
        default=WatchStatus.completed,
        server_default=WatchStatus.completed.value,
    )

    # Rating attributes (all optional) — keep RATING_ATTRIBUTE_FIELDS in sync
    pace = Column(Enum(Pace), nullable=True)
    animation_quality = Column(Enum(AnimationQuality), nullable=True)
    has_3d_animation = Column(Enum(ThreeDAnimation), nullable=True)
    watched_format = Column(Enum(WatchedFormat), nullable=True)
    fan_service = Column(Enum(FanService), nullable=True)
    dialogue_quality = Column(Enum(DialogueQuality), nullable=True)
    character_depth = Column(Enum(CharacterDepth), nullable=True)
    ending_type = Column(Enum(EndingType), nullable=True)
    ending_quality = Column(Enum(EndingQuality), nullable=True)
    story_quality = Column(Enum(StoryQuality), nullable=True)
    originality = Column(Enum(Originality), nullable=True)

    # Relationships
    media = relationship("Media", back_populates="ratings", lazy="raise")
    users = relationship("Users", back_populates="ratings", lazy="raise")
    rating_search = relationship("RatingSearch", back_populates="rating", cascade="all, delete-orphan", uselist=False, lazy="raise")

# Module-level constant — keep in sync with attribute columns above
RATING_ATTRIBUTE_FIELDS: tuple[str, ...] = (
    "pace", "animation_quality", "has_3d_animation", "watched_format",
    "fan_service", "dialogue_quality", "character_depth",
    "ending_type", "ending_quality", "story_quality", "originality",
)

# Composite index for paginated listing: WHERE user_id = ? ORDER BY modified_at DESC
Index("ix_ratings_user_modified", Ratings.user_id, Ratings.modified_at.desc())
