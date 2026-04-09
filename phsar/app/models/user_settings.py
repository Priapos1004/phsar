import enum

from sqlalchemy import Column, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


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


class UserSettings(BaseModel):
    __tablename__ = "user_settings"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    profile_picture = Column(String, nullable=False, default="bunny_01")
    name_language = Column(Enum(NameLanguage), nullable=False, default=NameLanguage.english)
    default_search_view = Column(Enum(DefaultSearchView), nullable=False, default=DefaultSearchView.anime)
    rating_step = Column(Enum(RatingStep), nullable=False, default=RatingStep.half)
    spoiler_level = Column(Enum(SpoilerLevel), nullable=False, default=SpoilerLevel.off)

    # Relationships
    users = relationship("Users", back_populates="settings", lazy="raise")
