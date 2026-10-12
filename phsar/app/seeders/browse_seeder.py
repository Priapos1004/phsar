"""The core browse carousels and filter sets, synced from the lists below on every
boot: docs/features/browse.md."""

from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.browse_dao import BrowseCarouselDAO
from app.models.browse import BrowseCarousel, BrowseFilterSet, CarouselFilterSet
from app.models.media import AIRING_STATUS_FINISHED_AIRING
from app.schemas.media_filter_schema import ANIME_RATED_STATES, RatedState


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
    sortable: bool = False


FILTER_SETS = [
    *(CoreFilterSet(f"top-{n}", f"{n}%", {"top_percent": n}) for n in (5, 10, 20, 50, 75)),
    CoreFilterSet("on-watchlist", "In list", {"watchlisted": True}),
    CoreFilterSet("not-on-watchlist", "Not in list", {"watchlisted": False}),
    # "Already" is every other state, so the pair splits a list exactly, as the
    # watchlist pair does.
    CoreFilterSet("not-watched", "Not yet", {"rated": [RatedState.NONE.value]}),
    CoreFilterSet("watched", "Already", {
        "rated": [s.value for s in RatedState if s in ANIME_RATED_STATES - {RatedState.NONE}],
    }),
]


def _carousel(
    key: str, title: str, params: dict[str, Any], see_all_limit: int,
    *, on: str | None = None, sortable: bool = False,
) -> CoreCarousel:
    """A carousel offering every set that leaves its own params alone, all off but `on`."""
    offered = [(s.key, s.key == on) for s in FILTER_SETS if not s.params.keys() & params.keys()]
    return CoreCarousel(key, title, params, see_all_limit, offered, sortable)


CAROUSELS = [
    _carousel(
        "announced-continuations", "Announced continuations",
        {"upcoming_main": True, "rated": ["in_progress", "on_hold", "main", "all"], "sort": "release"},
        1000, sortable=True,
    ),
    _carousel(
        "fresh", "Fresh out of the oven",
        {"airing_status": [AIRING_STATUS_FINISHED_AIRING], "sort": "aired"},
        250, on="top-75",
    ),
    _carousel("just-announced", "Just announced", {"upcoming_main": True, "sort": "announced"}, 1000),
    _carousel(
        "new-this-season", "New this season",
        {"anime_season": ["$current_season"], "sort": "popularity"},
        1000, sortable=True,
    ),
    _carousel(
        "next-season", "Coming next season",
        {"anime_season": ["$next_season"], "sort": "popularity"},
        1000, sortable=True,
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
        carousel.sortable = core.sortable
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
