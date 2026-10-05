from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.anime import Anime


class AnimeSearch(BaseModel):
    __tablename__ = "anime_search"

    anime_id: Mapped[int] = mapped_column(Integer, ForeignKey("anime.id", ondelete="CASCADE"), nullable=False, unique=True)
    title_embedding: Mapped[Any] = mapped_column(Vector(384), nullable=False)
    description_embedding: Mapped[Any] = mapped_column(Vector(384), nullable=False)

    # Relationships
    anime: Mapped["Anime"] = relationship("Anime", back_populates="anime_search", lazy="raise")
