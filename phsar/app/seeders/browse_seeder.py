"""The core browse carousels and filter sets, synced from the lists below on every
boot: docs/features/browse.md."""

from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.browse_dao import BrowseCarouselDAO
from app.models.browse import BrowseCarousel, BrowseFilterSet, CarouselFilterSet
from app.models.media import (
    AIRING_STATUS_CURRENTLY_AIRING,
    AIRING_STATUS_FINISHED_AIRING,
)


class CoreFilterSet(NamedTuple):
    key: str
    label: str
    params: dict[str, Any]


class CoreCarousel(NamedTuple):
    key: str
    title: str
    params: dict[str, Any]
    see_all_limit: int
    # (filter set key, on by default), in merge order.
    filter_sets: list[tuple[str, bool]]


FILTER_SETS = [
    CoreFilterSet("not-watched", "Not watched yet", {"rated": ["none"]}),
    CoreFilterSet("on-watchlist", "On my watchlist", {"watchlisted": True}),
    CoreFilterSet("not-on-watchlist", "Not on my watchlist", {"watchlisted": False}),
    CoreFilterSet("top-20", "Top 20%", {"top_percent": 20}),
]

# What a catalogue-wide carousel offers. A carousel over your own ratings leaves out
# "Not watched yet", whose `rated` would replace the carousel's own.
_CATALOGUE_SETS = [("not-watched", False), ("on-watchlist", False), ("not-on-watchlist", False), ("top-20", False)]

CAROUSELS = [
    CoreCarousel(
        "announced-continuations", "Announced continuations",
        {"upcoming_main": True, "rated": ["in_progress", "on_hold", "main", "all"], "sort": "release"},
        1000, [s for s in _CATALOGUE_SETS if s[0] != "not-watched"],
    ),
    CoreCarousel(
        "fresh", "Fresh out of the oven",
        {"airing_status": [AIRING_STATUS_FINISHED_AIRING], "sort": "aired"},
        250, _CATALOGUE_SETS,
    ),
    CoreCarousel(
        "airing-now", "Airing now",
        {"airing_status": [AIRING_STATUS_CURRENTLY_AIRING], "sort": "popularity"},
        1000, _CATALOGUE_SETS,
    ),
    CoreCarousel(
        "new-this-season", "New this season",
        {"anime_season": ["$current_season"], "sort": "popularity"},
        1000, _CATALOGUE_SETS,
    ),
    CoreCarousel(
        "next-season", "Coming next season",
        {"anime_season": ["$next_season"], "sort": "popularity"},
        1000, _CATALOGUE_SETS,
    ),
]


async def seed_browse(db: AsyncSession) -> None:
    # Plain assignment throughout: the ORM writes only what differs, so an unchanged
    # list costs no write (pinned by `test_a_second_seed_writes_nothing`).
    sets = {s.key: s for s in (await db.execute(select(BrowseFilterSet))).scalars().all()}
    for core_set in FILTER_SETS:
        filter_set = sets.get(core_set.key) or BrowseFilterSet(key=core_set.key)
        filter_set.label, filter_set.params = core_set.label, core_set.params
        db.add(filter_set)
        sets[core_set.key] = filter_set
    for key in sets.keys() - {s.key for s in FILTER_SETS}:
        await db.delete(sets.pop(key))

    carousels = await BrowseCarouselDAO().get_with_filter_sets(db)
    for core in CAROUSELS:
        carousel = carousels.pop(core.key, None) or BrowseCarousel(key=core.key, filter_sets=[])
        carousel.title, carousel.params, carousel.see_all_limit = core.title, core.params, core.see_all_limit
        db.add(carousel)

        links = {link.filter_set.key: link for link in carousel.filter_sets}
        wanted = []
        for position, (set_key, default_on) in enumerate(core.filter_sets):
            link = links.get(set_key) or CarouselFilterSet(filter_set=sets[set_key])
            link.default_on, link.position = default_on, position
            wanted.append(link)
        # Kept links stay the same rows; delete-orphan removes the rest.
        carousel.filter_sets = wanted
    for stale in carousels.values():
        await db.delete(stale)
    await db.flush()
