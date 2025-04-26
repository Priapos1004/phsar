from sqlalchemy import Column, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class MediaGenre(BaseModel):
    __tablename__ = "media_genre"

    media_id = Column(Integer, ForeignKey("media.id", ondelete="CASCADE"))
    genre_id = Column(Integer, ForeignKey("genre.id", ondelete="CASCADE"))
    __table_args__ = (
        UniqueConstraint('media_id', 'genre_id', name='unique_media_genre'),
    )
    # Relationships
    media = relationship("Media", back_populates="media_genre")
    genre = relationship("Genre", back_populates="media_genre")
