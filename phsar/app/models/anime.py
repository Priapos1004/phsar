from sqlalchemy import Column, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Anime(BaseModel):
    __tablename__ = "anime"

    title = Column(String, nullable=False)
    name_eng = Column(String)
    name_jap = Column(String)
    other_names = Column(JSONB, default=list)
    description = Column(String)
    cover_image = Column(String)

    # One-to-many relationship: Anime has many Media
    media = relationship("Media", back_populates="anime", cascade="all, delete-orphan")
