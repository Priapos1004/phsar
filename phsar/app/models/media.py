import enum

from sqlalchemy import (Column, DateTime, Enum, Float, ForeignKey, Integer,
                        String)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class MediaType(str, enum.Enum):
    TV = "TV"
    TVSpecial = "TV Special"
    Movie = "Movie"
    OVA = "OVA"
    ONA = "ONA"
    Special = "Special"

class RelationType(str, enum.Enum):
    Main = "main"
    Summary = "summary"
    Other = "other"

class Media(BaseModel):
    __tablename__ = "media"

    anime_id = Column(Integer, ForeignKey("anime.id", ondelete="CASCADE"), nullable=False)
    mal_id = Column(Integer, nullable=False)
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
    aired_from = Column(DateTime, nullable=True)
    aired_to = Column(DateTime, nullable=True)
    duration = Column(String, nullable=True)

    # Relationships
    anime = relationship("Anime", back_populates="media")
    ratings = relationship("Ratings", back_populates="media", cascade="all, delete-orphan")
    watchlist = relationship("Watchlist", back_populates="media", cascade="all, delete-orphan")
    media_genre = relationship("MediaGenre", back_populates="media", cascade="all, delete-orphan")
    media_studio = relationship("MediaStudio", back_populates="media", cascade="all, delete-orphan")
    media_search = relationship("MediaSearch", back_populates="media", cascade="all, delete-orphan")
