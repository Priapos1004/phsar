from datetime import date

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
    history_start: date | None
    recommend_hot: bool

    model_config = ConfigDict(from_attributes=True)


class UserSettingsUpdate(BaseModel):
    theme: Theme | None = None
    name_language: NameLanguage | None = None
    default_search_view: DefaultSearchView | None = None
    rating_step: RatingStep | None = None
    spoiler_level: SpoilerLevel | None = None
    # Null clears it: the recommender detects the start again.
    history_start: date | None = None
    recommend_hot: bool | None = None
