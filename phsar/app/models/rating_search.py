from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class RatingSearch(BaseModel):
    __tablename__ = "rating_search"

    rating_id = Column(Integer, ForeignKey("ratings.id", ondelete="CASCADE"), nullable=False, unique=True)
    note_embedding = Column(Vector(384), nullable=False)

    # Relationships
    rating = relationship("Ratings", back_populates="rating_search")
