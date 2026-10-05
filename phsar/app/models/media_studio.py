from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.media import Media
    from app.models.studio import Studio


class MediaStudio(BaseModel):
    __tablename__ = "media_studio"

    media_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("media.id", ondelete="CASCADE"))
    studio_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("studio.id", ondelete="CASCADE"))
    __table_args__ = (
        UniqueConstraint('media_id', 'studio_id', name='unique_media_studio'),
    )
    # Relationships
    media: Mapped["Media | None"] = relationship("Media", back_populates="media_studio", lazy="raise")
    studio: Mapped["Studio | None"] = relationship("Studio", back_populates="media_studio", lazy="raise")
