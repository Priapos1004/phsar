"""Browse pages: which carousels a page shows, and the search each one runs
(docs/features/browse.md)."""

from collections.abc import Collection
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos import search_filters
from app.daos.browse_dao import BrowseCarouselDAO
from app.exceptions import CarouselNotFoundError
from app.models.browse import BrowseCarousel
from app.models.media import SEASON_ORDER, SeasonType
from app.schemas.browse_schema import (
    BrowseCarouselOut,
    BrowseFilterSetOut,
    BrowsePage,
    CarouselParams,
)

browse_carousel_dao = BrowseCarouselDAO()

# Each page's carousels, top to bottom.
PAGE_LAYOUT: dict[BrowsePage, tuple[str, ...]] = {
    BrowsePage.NEWS: ("announced-continuations", "fresh", "airing-now", "new-this-season", "next-season"),
}


def _season_filter(day: date, ahead: int = 0) -> str:
    """The `anime_season` filter value ("Fall 2026") for the season holding `day`, or
    `ahead` seasons after it. Seasons are calendar quarters, as MAL counts them."""
    index = (day.month - 1) // 3 + ahead
    season = sorted(SEASON_ORDER, key=SEASON_ORDER.__getitem__)[index % 4]
    return f"{SeasonType(season).value} {day.year + index // 4}"


def _fill(value: Any, placeholders: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: _fill(v, placeholders) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, placeholders) for v in value]
    if isinstance(value, str) and value.startswith("$"):
        # Indexed: an unknown placeholder is a bug in the seeded row, not a value.
        return placeholders[value]
    return value


def resolve(carousel: BrowseCarousel, on: Collection[str] = (), off: Collection[str] = ()) -> BrowseCarouselOut:
    """The search `carousel` runs, its filter sets at their defaults except those
    named in `on` / `off`, as the query params `/search/anime` takes."""
    today = search_filters.utc_today()
    placeholders = {"$current_season": _season_filter(today), "$next_season": _season_filter(today, 1)}
    params = dict(carousel.params)
    for link in carousel.filter_sets:
        key = link.filter_set.key
        if (link.default_on or key in on) and key not in off:
            params |= link.filter_set.params
    checked = CarouselParams.model_validate(_fill(params, placeholders))
    return BrowseCarouselOut(
        key=carousel.key,
        title=carousel.title,
        params=checked.model_dump(mode="json", exclude_unset=True),
        see_all_limit=carousel.see_all_limit,
        filter_sets=[
            BrowseFilterSetOut(
                key=link.filter_set.key,
                label=link.filter_set.label,
                default_on=link.default_on,
                params=_fill(link.filter_set.params, placeholders),
            )
            for link in carousel.filter_sets
        ],
    )


async def get_page(db: AsyncSession, page: BrowsePage) -> list[BrowseCarouselOut]:
    keys = PAGE_LAYOUT[page]
    carousels = await browse_carousel_dao.get_with_filter_sets(db, keys)
    # Indexed: the seeder writes every carousel a layout names, from the same repo.
    return [resolve(carousels[key]) for key in keys]


async def get_carousel(
    db: AsyncSession, key: str, on: Collection[str], off: Collection[str],
) -> BrowseCarouselOut:
    carousel = (await browse_carousel_dao.get_with_filter_sets(db, [key])).get(key)
    if carousel is None:
        raise CarouselNotFoundError(key)
    return resolve(carousel, on, off)
