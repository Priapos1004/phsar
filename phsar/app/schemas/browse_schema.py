from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.media_filter_schema import (
    CatalogueSearchFilters,
    SearchQuery,
    SearchType,
    SortDir,
    SortKey,
)


class BrowsePage(str, Enum):
    HOME = "home"
    NEWS = "news"
    DISCOVER = "discover"


class CarouselParams(CatalogueSearchFilters):
    """A resolved carousel search: what `/search/anime` takes, and nothing else.

    Strict where the search schemas are not: they ignore an unknown key, so a
    misspelt filter in a seeded row would quietly filter nothing."""
    model_config = ConfigDict(extra="forbid")

    query: SearchQuery = ""
    search_type: SearchType = SearchType.TITLE
    sort: SortKey | None = None
    sort_dir: SortDir | None = None


class BrowseFilterSetOut(BaseModel):
    key: str
    label: str
    default_on: bool
    # Sent so the client can tell a set over the caller's own data from its params.
    params: dict[str, Any]


class BrowseCarouselOut(BaseModel):
    key: str
    title: str
    # The search to run: `/search/anime` query params, active filter sets merged in.
    params: dict[str, Any]
    see_all_limit: int
    sortable: bool
    filter_sets: list[BrowseFilterSetOut]
    page: BrowsePage | None


class WorldOut(BaseModel):
    """One segment of Discover's wheel. Its look is the frontend's, keyed by `key`."""
    key: str
    title: str


class DiscoverTodayOut(BaseModel):
    """Today's world, with its rows top to bottom."""
    world: str
    carousels: list[BrowseCarouselOut]


class DiscoverOut(BaseModel):
    worlds: list[WorldOut]
    today: DiscoverTodayOut | None
