from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.media import Media


class MediaSearch(BaseModel):
    __tablename__ = "media_search"

    media_id: Mapped[int] = mapped_column(Integer, ForeignKey("media.id", ondelete="CASCADE"), nullable=False, unique=True)
    title_embedding: Mapped[Any] = mapped_column(Vector(384), nullable=False)  # Specified vector length
    description_embedding: Mapped[Any] = mapped_column(Vector(384), nullable=False)  # Specified vector length

    # Relationships
    media: Mapped["Media"] = relationship("Media", back_populates="media_search", lazy="raise")
