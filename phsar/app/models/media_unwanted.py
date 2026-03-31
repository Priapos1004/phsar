from sqlalchemy import Column, Integer, String

from app.models.base import BaseModel


class MediaUnwanted(BaseModel):
    __tablename__ = "media_unwanted"

    mal_id = Column(Integer, nullable=False, unique=True)
    title = Column(String, nullable=False)
    reason = Column(String(20), nullable=False)
