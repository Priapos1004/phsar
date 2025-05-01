from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class MediaSearch(BaseModel):
    __tablename__ = "media_search"

    media_id = Column(Integer, ForeignKey("media.id", ondelete="CASCADE"), nullable=False, unique=True)
    title_embedding = Column(Vector(384), nullable=False)  # Specified vector length
    description_embedding = Column(Vector(384), nullable=False)  # Specified vector length

    # Relationships
    media = relationship("Media", back_populates="media_search")
