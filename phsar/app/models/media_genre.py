from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.genre import Genre
    from app.models.media import Media


class MediaGenre(BaseModel):
    __tablename__ = "media_genre"

    media_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("media.id", ondelete="CASCADE"))
    genre_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("genre.id", ondelete="CASCADE"))
    __table_args__ = (
        UniqueConstraint('media_id', 'genre_id', name='unique_media_genre'),
    )
    # Relationships
    media: Mapped["Media | None"] = relationship("Media", back_populates="media_genre", lazy="raise")
    genre: Mapped["Genre | None"] = relationship("Genre", back_populates="media_genre", lazy="raise")
