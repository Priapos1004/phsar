"""Browse pages: which carousels a page shows, and the search each one runs
(docs/features/browse.md)."""

import hashlib
from collections.abc import Collection, Iterable
from datetime import date
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos import search_filters
from app.daos.browse_dao import BrowseCarouselDAO, DiscoverProgressDAO
from app.exceptions import CarouselNotFoundError, WorldNotFoundError
from app.models.browse import BrowseCarousel
from app.models.media import SEASONS_IN_ORDER
from app.models.users import RoleType, Users
from app.schemas.browse_schema import (
    BrowseCarouselOut,
    BrowseFilterSetOut,
    BrowsePage,
    CarouselParams,
    DiscoverOut,
    DiscoverTodayOut,
    WorldOut,
)

browse_carousel_dao = BrowseCarouselDAO()
discover_progress_dao = DiscoverProgressDAO()

class World(NamedTuple):
    title: str
    # Its rows, top to bottom.
    carousels: tuple[str, ...]


# Discover's worlds, in the wheel's order. A row may sit in several worlds.
WORLDS: dict[str, World] = {
    "beasts": World("Beasts & Legends", ("dragons", "vampires", "demon-lords", "myths", "witches", "paws")),
    "other-worlds": World("Other Worlds", ("isekai", "reborn", "in-the-game", "magic-academy", "space")),
    "cozy": World("Cozy Corner", ("healing", "gourmet", "cgdct", "tiny-humans", "paws")),
    "twists": World("Twists & Turns", ("death-games", "detective", "time-travel", "five-steps", "whodunit")),
    "steel": World("Blood & Steel", ("samurai", "war", "revenge", "assassins", "family-business")),
    "after-dark": World("After Dark", ("lights-off", "haunting", "beyond", "city-magic", "vampires")),
    "future": World("Future Shock", ("mecha", "aliens", "after-the-end", "in-the-game")),
    "power-up": World("Power Up", ("superhuman", "fists", "tournament", "shinobi", "samurai")),
    "spotlight": World("Spotlight", ("idols", "on-stage", "game-on", "otaku")),
    "offbeat": World("Off the Beat", ("hidden-gems", "one-evening", "originals", "grown-ups", "nine-to-five")),
}

# Each page's carousels, top to bottom.
PAGE_LAYOUT: dict[BrowsePage, tuple[str, ...]] = {
    BrowsePage.HOME: ("lucky-find", "new-to-catalogue"),
    BrowsePage.NEWS: ("just-announced", "fresh", "announced-continuations", "new-this-season", "next-season"),
    BrowsePage.DISCOVER: tuple(dict.fromkeys(key for world in WORLDS.values() for key in world.carousels)),
}
# Each carousel's page; one only, pinned by `test_each_carousel_names_the_one_page_laying_it_out`.
_PAGE_OF = {key: page for page, keys in PAGE_LAYOUT.items() for key in keys}


def _season_filter(day: date, ahead: int = 0) -> str:
    """The `anime_season` filter value ("Fall 2026") for the season holding `day`, or
    `ahead` seasons after it. Seasons are calendar quarters, as MAL counts them."""
    index = (day.month - 1) // 3 + ahead
    return search_filters.season_filter(SEASONS_IN_ORDER[index % 4], day.year + index // 4)


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
        sortable=carousel.sortable,
        filter_sets=[
            BrowseFilterSetOut(
                key=link.filter_set.key,
                label=link.filter_set.label,
                default_on=link.default_on,
                params=_fill(link.filter_set.params, placeholders),
            )
            for link in carousel.filter_sets
        ],
        page=_PAGE_OF.get(carousel.key),
    )


async def _resolve_all(db: AsyncSession, keys: Iterable[str]) -> list[BrowseCarouselOut]:
    carousels = await browse_carousel_dao.get_with_filter_sets(db, keys)
    # Indexed: the seeder writes every carousel a layout names, from the same repo.
    return [resolve(carousels[key]) for key in keys]


async def get_page(db: AsyncSession, page: BrowsePage) -> list[BrowseCarouselOut]:
    return await _resolve_all(db, PAGE_LAYOUT[page])


async def get_carousel(
    db: AsyncSession, key: str, on: Collection[str], off: Collection[str],
) -> BrowseCarouselOut:
    carousel = (await browse_carousel_dao.get_with_filter_sets(db, [key])).get(key)
    if carousel is None:
        raise CarouselNotFoundError(key)
    return resolve(carousel, on, off)


def _cycle(seed: UUID, cycle: int) -> list[str]:
    """Every world once, in an order fixed by the seed and the cycle. Sorted by a hash
    rather than shuffled by `random`, whose algorithms may change between Python versions."""
    return sorted(WORLDS, key=lambda key: hashlib.sha256(f"{seed}:{cycle}:{key}".encode()).digest())


_REST = 3


def world_for(seed: UUID, n: int) -> str:
    """The `n`-th world (from 0) drawn for `seed`: a shuffle bag, so each cycle of
    `len(WORLDS)` draws holds every world once in an order of its own, and a world
    drawn sits out the next `_REST` draws."""
    cycle, index = divmod(n, len(WORLDS))
    order = _cycle(seed, cycle)
    if cycle:
        # Open with worlds the last cycle didn't close with. That moves only the first
        # 2 × _REST places, so with 3 × _REST worlds or more the last cycle's closing
        # worlds are its plain order's.
        closing = set(_cycle(seed, cycle - 1)[-_REST:])
        opening = [world for world in order if world not in closing][:_REST]
        order = opening + [world for world in order if world not in opening]
    return order[index]


async def _drawn(db: AsyncSession, world: str) -> DiscoverTodayOut:
    return DiscoverTodayOut(world=world, carousels=await _resolve_all(db, WORLDS[world].carousels))


async def get_discover(db: AsyncSession, user: Users) -> DiscoverOut:
    day = search_filters.utc_today()
    if user.role == RoleType.RestrictedUser:
        n: int | None = day.toordinal()
    else:
        progress = await discover_progress_dao.get_by_field(db, user_id=user.id, spun_on=day)
        n = progress.spin_count - 1 if progress else None
    return DiscoverOut(
        worlds=[WorldOut(key=key, title=world.title) for key, world in WORLDS.items()],
        today=await _drawn(db, world_for(user.uuid, n)) if n is not None else None,
    )


async def spin(db: AsyncSession, user: Users) -> DiscoverTodayOut:
    n = await discover_progress_dao.record_spin(db, user.id, search_filters.utc_today()) - 1
    await db.commit()
    return await _drawn(db, world_for(user.uuid, n))


async def preview(db: AsyncSession, world: str) -> DiscoverTodayOut:
    if world not in WORLDS:
        raise WorldNotFoundError(world)
    return await _drawn(db, world)
