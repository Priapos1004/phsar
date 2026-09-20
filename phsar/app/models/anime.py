from typing import TYPE_CHECKING

from sqlalchemy import Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.anime_completion import AnimeCompletion
    from app.models.anime_freshness import AnimeFreshness
    from app.models.anime_search import AnimeSearch
    from app.models.media import Media


class Anime(BaseModel):
    __tablename__ = "anime"

    mal_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    name_eng: Mapped[str | None] = mapped_column(String)
    name_jap: Mapped[str | None] = mapped_column(String)
    other_names: Mapped[list[str] | None] = mapped_column(JSONB, default=list)
    description: Mapped[str | None] = mapped_column(String)
    cover_image: Mapped[str | None] = mapped_column(String)

    # One-to-many relationship: Anime has many Media
    media: Mapped[list["Media"]] = relationship("Media", back_populates="anime", cascade="all, delete-orphan", lazy="raise")

    # One-to-one relationship: Anime has one AnimeSearch (vector embeddings)
    anime_search: Mapped["AnimeSearch | None"] = relationship("AnimeSearch", back_populates="anime", cascade="all, delete-orphan", uselist=False, lazy="raise")

    # One-to-one sidecar with the nightly-sweep freshness state. Lives in
    # its own table so operational tracking doesn't widen the canonical
    # anime row or risk leaking into Pydantic response schemas.
    freshness: Mapped["AnimeFreshness | None"] = relationship(
        "AnimeFreshness",
        back_populates="anime",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="raise",
    )

    # One-to-one sidecar: presence = admin marked the story as complete (v0.14.10).
    completion: Mapped["AnimeCompletion | None"] = relationship(
        "AnimeCompletion",
        back_populates="anime",
        cascade="all, delete-orphan",
        uselist=False,
        lazy="raise",
    )
