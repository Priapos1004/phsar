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
    *, on: tuple[str, ...] = (), sortable: bool = False,
) -> CoreCarousel:
    """A carousel offering every set that leaves its own params alone, all off but `on`."""
    offered = [(s.key, s.key in on) for s in FILTER_SETS if not s.params.keys() & params.keys()]
    return CoreCarousel(key, title, params, see_all_limit, offered, sortable)


def _discover(key: str, title: str, params: dict[str, Any], *on: str) -> CoreCarousel:
    """A row of Discover's worlds. Its params are what it is, so its see-all may sort."""
    return _carousel(key, title, params, 1000, on=("not-watched", *on), sortable=True)


def _tags(*names: str, sort: str = "top_rated") -> dict[str, Any]:
    """Anime carrying any of the genres or themes named."""
    params: dict[str, Any] = {"genre_name": list(names), "sort": sort}
    if len(names) > 1:
        params["genre_mode"] = "any"
    return params


def _about(query: str) -> dict[str, Any]:
    """Anime whose description is about `query`. One or two plain words — a longer
    phrase loses its literal hits and keeps few."""
    return {"query": query, "search_type": "description", "sort": "relevance"}


CAROUSELS = [
    _carousel(
        "announced-continuations", "Announced continuations",
        {"upcoming_main": True, "rated": ["in_progress", "on_hold", "main", "all"], "sort": "release"},
        1000, sortable=True,
    ),
    _carousel(
        "fresh", "Fresh out of the oven",
        {"airing_status": [AIRING_STATUS_FINISHED_AIRING], "sort": "aired"},
        250, on=("top-75",),
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
    _carousel(
        "lucky-find", "Lucky find",
        {"rated": [RatedState.NONE.value, RatedState.IN_PROGRESS.value], "sort": "random"},
        250, on=("top-75",),
    ),
    _carousel("new-to-catalogue", "New to the catalogue", {"sort": "added"}, 250, on=("top-75",)),
    # Discover's rows; `browse_service.WORLDS` groups them.
    _discover("dragons", "Here be dragons", _about("dragon")),
    _discover("vampires", "Fangs at midnight", _about("vampire")),
    _discover("demon-lords", "All hail the demon lord", _about("demon lord")),
    _discover("myths", "Gods & myths", _tags("Mythology")),
    _discover("witches", "Witching hour", _about("witch")),
    _discover("paws", "Paws & tails", _tags("Pets", "Anthropomorphic")),
    _discover("isekai", "Truck-kun strikes again", _tags("Isekai", sort="random"), "top-50"),
    _discover("reborn", "Born again", _tags("Reincarnation", "Villainess")),
    _discover("in-the-game", "Trapped in the game", _tags("Video Game")),
    _discover("magic-academy", "Magic academy", _about("magic academy")),
    _discover("space", "Among the stars", _tags("Space")),
    _discover("healing", "Healing hour", _tags("Iyashikei")),
    _discover("gourmet", "Eat well", _tags("Gourmet")),
    _discover("cgdct", "Cute girls doing cute things", _tags("CGDCT")),
    _discover("tiny-humans", "Tiny humans", _tags("Childcare")),
    _discover("death-games", "Death games", _tags("High Stakes Game", "Survival")),
    _discover("detective", "The detective's desk", _tags("Detective")),
    _discover("time-travel", "Loops & paradoxes", _tags("Time Travel")),
    _discover("five-steps", "Five steps ahead", _tags("Strategy Game", "Psychological")),
    _discover("whodunit", "Whodunit", _about("murder mystery")),
    _discover("samurai", "Way of the sword", _tags("Samurai")),
    _discover("war", "Fog of war", _tags("Military")),
    _discover("revenge", "Served cold", _about("revenge")),
    _discover("assassins", "Contract killers", _about("assassin")),
    _discover("family-business", "Family business", _tags("Organized Crime")),
    _discover("lights-off", "Lights off", _tags("Horror")),
    _discover("haunting", "Something's haunting", _about("ghosts")),
    _discover("beyond", "Beyond explanation", _tags("Supernatural", sort="random"), "top-50"),
    _discover("city-magic", "Magic in the city", _tags("Urban Fantasy")),
    _discover("mecha", "Get in the robot", _tags("Mecha")),
    _discover("robots", "Ghost in the machine", _about("robot")),
    _discover("after-the-end", "After the end", _about("post-apocalyptic world")),
    _discover("superhuman", "Superhuman", _tags("Super Power")),
    # Top 75%, not 50%: the martial-arts pool is mostly low-rated, and half of it
    # leaves a well-watched viewer a handful of tiles.
    _discover("fists", "Fists of fury", _tags("Martial Arts", "Combat Sports", sort="random"), "top-75"),
    _discover("tournament", "Tournament arc", _about("tournament")),
    _discover("shinobi", "Shinobi", _about("ninja")),
    _discover("idols", "Idol life", _tags("Idols (Female)", "Idols (Male)")),
    _discover("on-stage", "On stage", _tags("Performing Arts", "Showbiz", "Music")),
    _discover("game-on", "Game on", _tags("Team Sports", "Sports")),
    _discover("otaku", "Otaku culture", _tags("Otaku Culture")),
    # Plain score: the vote-weighted top-rated order would bury the low-vote anime
    # this row exists for.
    _discover("hidden-gems", "Hidden gems", {"score_min": 7.8, "scored_by_max": 50_000, "sort": "score"}),
    _discover("one-evening", "One evening", {"total_watch_time_max": 3 * 3600, "sort": "random"}, "top-50"),
    _discover("originals", "Pure originals", {"original_source": ["Original"], "sort": "random"}, "top-50"),
    _discover("grown-ups", "No high-schoolers", _tags("Adult Cast", sort="random"), "top-50"),
    _discover("nine-to-five", "9 to 5", _tags("Workplace")),
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
