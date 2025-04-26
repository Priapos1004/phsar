import enum

from sqlalchemy import Column, Enum, String
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class GenreType(str, enum.Enum):
    Genres = "genres"
    ExplicitGenres = "explicit_genres"
    Themes = "themes"
    Demographics = "demographics"

class Genre(BaseModel):
    __tablename__ = "genre"

    name = Column(String(50), unique=True, nullable=False)
    genre_type = Column(Enum(GenreType), nullable=False)

    # Relationships
    media_genre = relationship("MediaGenre", back_populates="genre", cascade="all, delete-orphan")
