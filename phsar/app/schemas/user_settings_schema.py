from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.user_settings import (
    DefaultSearchView,
    NameLanguage,
    RatingStep,
    SpoilerLevel,
    Theme,
)


class UserSettingsOut(BaseModel):
    theme: Theme
    name_language: NameLanguage
    default_search_view: DefaultSearchView
    rating_step: RatingStep
    spoiler_level: SpoilerLevel

    model_config = ConfigDict(from_attributes=True)


class UserSettingsUpdate(BaseModel):
    theme: Optional[Theme] = None
    name_language: Optional[NameLanguage] = None
    default_search_view: Optional[DefaultSearchView] = None
    rating_step: Optional[RatingStep] = None
    spoiler_level: Optional[SpoilerLevel] = None
