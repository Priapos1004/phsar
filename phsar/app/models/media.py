import enum

from sqlalchemy import (Column, DateTime, Enum, Float, ForeignKey, Integer,
                        String, case)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_method, hybrid_property
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

class Media(BaseModel):
    __tablename__ = "media"

    anime_id = Column(Integer, ForeignKey("anime.id", ondelete="CASCADE"), nullable=False)
    mal_id = Column(Integer, nullable=False, unique=True)
    mal_url = Column(String, nullable=False)
    title = Column(String, nullable=False)
    name_eng = Column(String)
    name_jap = Column(String)
    other_names = Column(JSONB, default=list)
    media_type = Column(Enum(MediaType), nullable=False)
    relation_type = Column(Enum(RelationType), nullable=False)
    fsk = Column(String)
    description = Column(String)
    original_source = Column(String)
    cover_image = Column(String)
    score = Column(Float, nullable=True)
    scored_by = Column(Integer, nullable=True)
    episodes = Column(Integer, nullable=True)
    anime_season = Column(String, nullable=True)
    airing_status = Column(String, nullable=False)
    aired_from = Column(DateTime(timezone=True), nullable=True)
    aired_to = Column(DateTime(timezone=True), nullable=True)
    duration = Column(String, nullable=True)
    duration_seconds = Column(Integer, nullable=True)

    @hybrid_property
    def total_watch_time(self):
        if self.episodes and self.duration_seconds:
            return self.episodes * self.duration_seconds
        return None

    @total_watch_time.expression
    def total_watch_time(cls):
        return case(
            (
                (cls.episodes != None) & (cls.duration_seconds != None),
                cls.episodes * cls.duration_seconds
            ),
            else_=None # Changeable default value for total_watch_time = None
        )

    # Relationships
    anime = relationship("Anime", back_populates="media")
    ratings = relationship("Ratings", back_populates="media", cascade="all, delete-orphan")
    watchlist = relationship("Watchlist", back_populates="media", cascade="all, delete-orphan")
    media_genre = relationship("MediaGenre", back_populates="media", cascade="all, delete-orphan")
    media_studio = relationship("MediaStudio", back_populates="media", cascade="all, delete-orphan")
    media_search = relationship("MediaSearch", back_populates="media", cascade="all, delete-orphan")
