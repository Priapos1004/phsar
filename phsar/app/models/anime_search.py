from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class AnimeSearch(BaseModel):
    __tablename__ = "anime_search"

    anime_id = Column(Integer, ForeignKey("anime.id", ondelete="CASCADE"), nullable=False, unique=True)
    title_embedding = Column(Vector(384), nullable=False)
    description_embedding = Column(Vector(384), nullable=False)

    # Relationships
    anime = relationship("Anime", back_populates="anime_search", lazy="raise")
