import enum

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    case,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class MediaType(str, enum.Enum):
    TV = "TV"
    TVSpecial = "TVSpecial"
    Movie = "Movie"
    OVA = "OVA"
    ONA = "ONA"
    Special = "Special"

class RelationType(str, enum.Enum):
    Main = "main"
    Summary = "summary"
    Crossover = "crossover"
    Other = "other"

class SeasonType(str, enum.Enum):
    Winter = "Winter"
    Spring = "Spring"
    Summer = "Summer"
    Fall   = "Fall"

# Define ordered mapping to ensure correct prefix priority
AGE_RATING_MAP = [
    ("PG-13", 13),   # Must come before PG
    ("R+", 18),      # Must come before R
    ("R", 17),
    ("PG", 6),
    ("G", 0),
]

class Media(BaseModel):
    __tablename__ = "media"

    anime_id = Column(Integer, ForeignKey("anime.id", ondelete="CASCADE"), nullable=False, index=True)
    mal_id = Column(Integer, nullable=False, unique=True)
    mal_url = Column(String, nullable=False)
    title = Column(String, nullable=False)
    name_eng = Column(String)
    name_jap = Column(String)
    other_names = Column(JSONB, default=list)
    media_type = Column(Enum(MediaType), nullable=False)
    relation_type = Column(Enum(RelationType), nullable=False)
    age_rating = Column(String)
    description = Column(String)
    original_source = Column(String)
    cover_image = Column(String)
    score = Column(Float, nullable=True)
    scored_by = Column(Integer, nullable=False)
    episodes = Column(Integer, nullable=True)
    anime_season_name = Column(Enum(SeasonType), nullable=True)
    anime_season_year = Column(Integer, nullable=True)
    airing_status = Column(String, nullable=False)
    aired_from = Column(DateTime(timezone=True), nullable=True)
    aired_to = Column(DateTime(timezone=True), nullable=True)
    duration = Column(String, nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    @hybrid_property
    def age_rating_numeric(self):
        """Returns numeric age rating based on MAL's age rating strings."""
        if not self.age_rating:
            return None

        normalized = self.age_rating.strip()
        for prefix, value in AGE_RATING_MAP:
            if normalized.startswith(prefix):
                return value
        return None

    @age_rating_numeric.expression
    def age_rating_numeric(cls):
        """SQL expression to compute numeric age rating using prefix matching."""
        return case(
            *[(cls.age_rating.startswith(prefix), value) for prefix, value in AGE_RATING_MAP],
            else_=None
        )

    @hybrid_property
    def total_watch_time(self):
        if self.episodes and self.duration_seconds:
            return self.episodes * self.duration_seconds
        return None

    @total_watch_time.expression
    def total_watch_time(cls):
        return case(
            (
                (cls.episodes.isnot(None) & cls.duration_seconds.isnot(None)),
                cls.episodes * cls.duration_seconds
            ),
            else_=None  # Changeable default value for total_watch_time = None
        )
    
    __table_args__ = (
        CheckConstraint(
            "anime_season_year >= 1900 AND anime_season_year <= 2200",
            name="check_season_year_4_digits"
        ),
        CheckConstraint(
            "(anime_season_name IS NULL AND anime_season_year IS NULL) "
            "OR (anime_season_name IS NOT NULL AND anime_season_year IS NOT NULL)",
            name="check_season_parts_both_or_none",
        ),
    )

    # Relationships
    anime = relationship("Anime", back_populates="media", lazy="raise")
    ratings = relationship("Ratings", back_populates="media", cascade="all, delete-orphan", lazy="raise")
    watchlist = relationship("Watchlist", back_populates="media", cascade="all, delete-orphan", lazy="raise")
    media_genre = relationship("MediaGenre", back_populates="media", cascade="all, delete-orphan", lazy="raise")
    media_studio = relationship("MediaStudio", back_populates="media", cascade="all, delete-orphan", lazy="raise")
    media_search = relationship("MediaSearch", back_populates="media", cascade="all, delete-orphan", lazy="raise")

# Index to optimize queries filtering or ordering by season year and name
Index(
    "ix_media_year_season",
    Media.anime_season_year,
    Media.anime_season_name,
)
