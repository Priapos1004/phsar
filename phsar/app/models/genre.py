import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.media_genre import MediaGenre


class GenreType(str, enum.Enum):
    Genres = "genres"
    ExplicitGenres = "explicit_genres"
    Themes = "themes"
    Demographics = "demographics"

class Genre(BaseModel):
    __tablename__ = "genre"

    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    genre_type: Mapped[GenreType] = mapped_column(Enum(GenreType), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    media_genre: Mapped[list["MediaGenre"]] = relationship("MediaGenre", back_populates="genre", cascade="all, delete-orphan", lazy="raise")
