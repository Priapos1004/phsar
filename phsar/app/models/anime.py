from sqlalchemy import Column, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Anime(BaseModel):
    __tablename__ = "anime"

    mal_id = Column(Integer, nullable=False, unique=True)
    title = Column(String, nullable=False)
    name_eng = Column(String)
    name_jap = Column(String)
    other_names = Column(JSONB, default=list)
    description = Column(String)
    cover_image = Column(String)

    # One-to-many relationship: Anime has many Media
    media = relationship("Media", back_populates="anime", cascade="all, delete-orphan", lazy="raise")

    # One-to-one relationship: Anime has one AnimeSearch (vector embeddings)
    anime_search = relationship("AnimeSearch", back_populates="anime", cascade="all, delete-orphan", uselist=False, lazy="raise")

    # One-to-one sidecar with the nightly-sweep freshness state. Lives in
    # its own table so operational tracking doesn't widen the canonical
    # anime row or risk leaking into Pydantic response schemas.
    freshness = relationship(
        "AnimeFreshness",
        back_populates="anime",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="raise",
    )
