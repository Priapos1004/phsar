from sqlalchemy import Column, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class MediaStudio(BaseModel):
    __tablename__ = "media_studio"

    media_id = Column(Integer, ForeignKey("media.id", ondelete="CASCADE"))
    studio_id = Column(Integer, ForeignKey("studio.id", ondelete="CASCADE"))
    __table_args__ = (
        UniqueConstraint('media_id', 'studio_id', name='unique_media_studio'),
    )
    # Relationships
    media = relationship("Media", back_populates="media_studio")
    studio = relationship("Studio", back_populates="media_studio")
