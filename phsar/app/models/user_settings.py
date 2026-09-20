import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel

if TYPE_CHECKING:
    from app.models.users import Users


class NameLanguage(str, enum.Enum):
    english = "english"
    japanese = "japanese"
    romaji = "romaji"


class DefaultSearchView(str, enum.Enum):
    anime = "anime"
    media = "media"


class RatingStep(str, enum.Enum):
    half = "0.5"
    quarter = "0.25"
    tenth = "0.1"
    hundredth = "0.01"


class SpoilerLevel(str, enum.Enum):
    off = "off"
    blur = "blur"
    hide = "hide"


class Theme(str, enum.Enum):
    default = "default"
    red = "red"
    blue = "blue"
    green = "green"


class UserSettings(BaseModel):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    theme: Mapped[Theme] = mapped_column(Enum(Theme), nullable=False, default=Theme.default)
    name_language: Mapped[NameLanguage] = mapped_column(Enum(NameLanguage), nullable=False, default=NameLanguage.english)
    default_search_view: Mapped[DefaultSearchView] = mapped_column(Enum(DefaultSearchView), nullable=False, default=DefaultSearchView.anime)
    rating_step: Mapped[RatingStep] = mapped_column(Enum(RatingStep), nullable=False, default=RatingStep.half)
    spoiler_level: Mapped[SpoilerLevel] = mapped_column(Enum(SpoilerLevel), nullable=False, default=SpoilerLevel.off)

    # Relationships
    users: Mapped["Users"] = relationship("Users", back_populates="settings", lazy="raise")
