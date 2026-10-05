from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.media_studio import MediaStudio


class Studio(BaseModel):
    __tablename__ = "studio"

    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    # Relationships
    media_studio: Mapped[list["MediaStudio"]] = relationship("MediaStudio", back_populates="studio", cascade="all, delete-orphan", lazy="raise")
