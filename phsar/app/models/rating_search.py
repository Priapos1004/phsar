from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.ratings import Ratings


class RatingSearch(BaseModel):
    __tablename__ = "rating_search"

    rating_id: Mapped[int] = mapped_column(Integer, ForeignKey("ratings.id", ondelete="CASCADE"), nullable=False, unique=True)
    note_embedding: Mapped[Any] = mapped_column(Vector(384), nullable=False)

    # Relationships
    rating: Mapped["Ratings"] = relationship("Ratings", back_populates="rating_search", lazy="raise")
