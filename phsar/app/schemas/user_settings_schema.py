
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
    theme: Theme | None = None
    name_language: NameLanguage | None = None
    default_search_view: DefaultSearchView | None = None
    rating_step: RatingStep | None = None
    spoiler_level: SpoilerLevel | None = None
