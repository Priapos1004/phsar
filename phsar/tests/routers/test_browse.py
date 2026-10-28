"""The browse endpoints: a page's carousels, and the search each one resolves to.

The core rows are seeded into the rolled-back session first, so the suite runs the
same whether or not the database has booted the app since the seeder last changed.
"""

import json
from datetime import date

import pytest
from pydantic import ValidationError

from app.daos import search_filters
from app.daos.discover_progress_dao import DiscoverProgressDAO
from app.daos.user_dao import UserDAO
from app.models.browse import BrowseCarousel, BrowseFilterSet, CarouselFilterSet
from app.models.users import Users
from app.schemas.browse_schema import BrowsePage
from app.seeders.browse_seeder import CAROUSELS, seed_browse
from app.services.browse_service import MOODS, PAGE_LAYOUT, mood_for, resolve


@pytest.fixture(autouse=True)
async def _seeded(db_session):
    await seed_browse(db_session)


async def _carousel(client, headers, key: str, **params) -> dict:
    resp = await client.get(f"/browse/carousels/{key}", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_pages_list_their_layout_in_order(client, user_auth_headers):
    for page in BrowsePage:
        resp = await client.get(f"/browse/{page.value}", headers=user_auth_headers)
        assert resp.status_code == 200, resp.text
        assert [c["key"] for c in resp.json()] == list(PAGE_LAYOUT[page])


async def test_each_carousel_names_the_one_page_laying_it_out(client, user_auth_headers):
    laid_out = [(key, page) for page, keys in PAGE_LAYOUT.items() for key in keys]
    assert len({key for key, _ in laid_out}) == len(laid_out), "a carousel sits on two pages"
    assert {key for key, _ in laid_out} == {core.key for core in CAROUSELS}, "a seeded carousel no page shows"
    for key, page in laid_out:
        assert (await _carousel(client, user_auth_headers, key))["page"] == page.value


async def test_season_placeholders_resolve_to_today(client, user_auth_headers, monkeypatch):
    """Fall rolls over into the next year's winter."""
    monkeypatch.setattr(search_filters, "utc_today", lambda: date(2026, 11, 3))
    current = await _carousel(client, user_auth_headers, "new-this-season")
    upcoming = await _carousel(client, user_auth_headers, "next-season")
    assert current["params"]["anime_season"] == ["Fall 2026"]
    assert upcoming["params"]["anime_season"] == ["Winter 2027"]


@pytest.fixture
async def clashing_carousel(db_session) -> str:
    """Two sets writing the same key: the first off by default, the second on.

    So switching the first on puts position and switching on opposite sides — the
    later set must win although the earlier one is the one just switched on."""
    carousel = BrowseCarousel(
        key="test-clash", title="Clash", params={"sort": "score"}, see_all_limit=10,
        filter_sets=[
            CarouselFilterSet(
                filter_set=BrowseFilterSet(key="test-wide", label="Wide", params={"top_percent": 50}),
                default_on=False, position=0,
            ),
            CarouselFilterSet(
                filter_set=BrowseFilterSet(key="test-narrow", label="Narrow", params={"top_percent": 10}),
                default_on=True, position=1,
            ),
        ],
    )
    db_session.add(carousel)
    await db_session.flush()
    return carousel.key


async def test_filter_sets_follow_their_default_unless_switched(client, user_auth_headers, clashing_carousel):
    default = await _carousel(client, user_auth_headers, clashing_carousel)
    assert default["params"] == {"sort": "score", "top_percent": 10}
    assert [(s["key"], s["default_on"]) for s in default["filter_sets"]] == [
        ("test-wide", False), ("test-narrow", True),
    ]

    off = await _carousel(client, user_auth_headers, clashing_carousel, off="test-narrow")
    assert off["params"] == {"sort": "score"}

    swapped = await _carousel(client, user_auth_headers, clashing_carousel, on="test-wide", off="test-narrow")
    assert swapped["params"] == {"sort": "score", "top_percent": 50}


async def test_a_later_filter_set_wins_a_key_clash(client, user_auth_headers, clashing_carousel):
    """Both on: the narrow set sits later, so its value stands over the one just switched on."""
    both = await _carousel(client, user_auth_headers, clashing_carousel, on="test-wide")
    assert both["params"]["top_percent"] == 10


async def test_unknown_carousel_is_404(client, user_auth_headers):
    resp = await client.get("/browse/carousels/no-such-carousel", headers=user_auth_headers)
    assert resp.status_code == 404


# The flat genre pair too: a token reads it as a group, a seeded row must not.
@pytest.mark.parametrize("param", ["genre_names", "genre_name"])
def test_a_misspelt_param_fails_resolution(param):
    carousel = BrowseCarousel(
        key="typo", title="Typo", params={param: ["Action"]}, see_all_limit=10, sortable=False, filter_sets=[],
    )
    with pytest.raises(ValidationError):
        resolve(carousel)


@pytest.mark.parametrize("core", CAROUSELS, ids=lambda c: c.key)
async def test_every_seeded_carousel_runs_as_a_search(client, user_auth_headers, core):
    """Each carousel, bare and with every set it offers switched on, is a search
    `/search/anime` accepts — a seeded value it rejects would empty the row."""
    every_set = [key for key, _ in core.filter_sets]
    for switched in ({}, {"on": every_set}):
        carousel = await _carousel(client, user_auth_headers, core.key, **switched)
        # As the frontend's `buildSearchParams` sends them: the genre groups as JSON.
        params = {key: json.dumps(value) if isinstance(value, dict) else value
                  for key, value in carousel["params"].items()}
        resp = await client.get("/search/anime", params={**params, "limit": 25}, headers=user_auth_headers)
        assert resp.status_code == 200, f"{core.key} {switched}: {resp.text}"


async def test_guest_reads_browse_but_not_a_personal_search(client, restricted_user_auth_headers):
    resp = await client.get("/browse/news", headers=restricted_user_auth_headers)
    assert resp.status_code == 200
    continuations = next(c for c in resp.json() if c["key"] == "announced-continuations")
    search = await client.get(
        "/search/anime", params={**continuations["params"], "limit": 25}, headers=restricted_user_auth_headers,
    )
    assert search.status_code == 403


async def _user(db_session, username: str) -> Users:
    user = await UserDAO().get_by_username(db_session, username)
    assert user is not None
    return user


def _drawn(today: dict) -> dict:
    """A drawn mood, checked to carry its own rows in order."""
    assert [c["key"] for c in today["carousels"]] == list(MOODS[today["mood"]].carousels)
    return today


async def _today(client, headers) -> dict | None:
    resp = await client.get("/browse/moods", headers=headers)
    assert resp.status_code == 200, resp.text
    assert [mood["key"] for mood in resp.json()["moods"]] == list(MOODS)
    today = resp.json()["today"]
    return today and _drawn(today)


async def _spin(client, headers) -> dict:
    resp = await client.post("/browse/moods/spin", headers=headers)
    assert resp.status_code == 200, resp.text
    return _drawn(resp.json())


async def test_a_spin_counts_once_a_day_and_moves_on_the_next(client, user_auth_headers, db_session, monkeypatch):
    user = await _user(db_session, "normaluser")
    monkeypatch.setattr(search_filters, "utc_today", lambda: date(2026, 11, 3))
    assert await _today(client, user_auth_headers) is None

    first = await _spin(client, user_auth_headers)
    assert first["mood"] == mood_for(user.uuid, 0)
    # The draw never repeats a mood on consecutive spins, so a second count would show.
    assert (await _spin(client, user_auth_headers))["mood"] == first["mood"]
    assert (await _today(client, user_auth_headers))["mood"] == first["mood"]

    monkeypatch.setattr(search_filters, "utc_today", lambda: date(2026, 11, 4))
    assert await _today(client, user_auth_headers) is None
    assert (await _spin(client, user_auth_headers))["mood"] == mood_for(user.uuid, 1)
    progress = await DiscoverProgressDAO().get_by_field(db_session, user_id=user.id)
    assert progress is not None
    assert (progress.spin_count, progress.spun_on, progress.mood) == (2, date(2026, 11, 4), mood_for(user.uuid, 1))

    # A spin sent before midnight, committing after this one.
    monkeypatch.setattr(search_filters, "utc_today", lambda: date(2026, 11, 3))
    await _spin(client, user_auth_headers)
    await db_session.refresh(progress)
    assert (progress.spin_count, progress.spun_on) == (2, date(2026, 11, 4))


async def test_the_day_s_mood_is_the_one_its_spin_stored(client, user_auth_headers, db_session, monkeypatch):
    """So a release editing the moods leaves a drawn one in place; one it dropped is drawn again."""
    user = await _user(db_session, "normaluser")
    monkeypatch.setattr(search_filters, "utc_today", lambda: date(2026, 11, 3))
    drawn = (await _spin(client, user_auth_headers))["mood"]
    progress = await DiscoverProgressDAO().get_by_field(db_session, user_id=user.id)
    assert progress is not None
    # Not what the bag draws, as a draw under another list of moods would be.
    progress.mood = next(key for key in MOODS if key != drawn)
    await db_session.flush()
    assert (await _today(client, user_auth_headers))["mood"] == progress.mood
    assert (await _spin(client, user_auth_headers))["mood"] == progress.mood

    progress.mood = "dropped-since"
    await db_session.flush()
    assert (await _today(client, user_auth_headers))["mood"] == drawn


async def test_an_admin_previews_a_mood_without_spinning(client, admin_auth_headers, monkeypatch):
    # A day the database holds no spin for, so "still unspun" means the previews counted none.
    monkeypatch.setattr(search_filters, "utc_today", lambda: date(2099, 1, 1))
    # Two, so the mood shown is the one asked for rather than one the endpoint settled on.
    for key in list(MOODS)[:2]:
        resp = await client.get(f"/browse/moods/{key}", headers=admin_auth_headers)
        assert resp.status_code == 200, resp.text
        assert _drawn(resp.json())["mood"] == key
    assert await _today(client, admin_auth_headers) is None


async def test_only_an_admin_previews_a_mood(client, user_auth_headers):
    assert (await client.get(f"/browse/moods/{next(iter(MOODS))}", headers=user_auth_headers)).status_code == 403


async def test_previewing_an_unknown_mood_is_404(client, admin_auth_headers):
    assert (await client.get("/browse/moods/no-such-mood", headers=admin_auth_headers)).status_code == 404


async def test_a_guest_cannot_spin_and_gets_the_day_s_mood(client, restricted_user_auth_headers, db_session, monkeypatch):
    guest = await _user(db_session, "restricteduser")
    day = date(2026, 11, 3)
    monkeypatch.setattr(search_filters, "utc_today", lambda: day)

    assert (await client.post("/browse/moods/spin", headers=restricted_user_auth_headers)).status_code == 403
    today = await _today(client, restricted_user_auth_headers)
    assert today is not None
    assert today["mood"] == mood_for(guest.uuid, day.toordinal())
