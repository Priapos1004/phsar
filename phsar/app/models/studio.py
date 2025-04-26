from sqlalchemy import Column, String
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Studio(BaseModel):
    __tablename__ = "studio"

    name = Column(String, unique=True, nullable=False)

    # Relationships
    media_studio = relationship("MediaStudio", back_populates="studio", cascade="all, delete-orphan")
