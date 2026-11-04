"""GET /search/anime/uuids: every anime the search's filters keep, uncapped and unordered,
through the anime search's own filter phase — so the set always matches what the search
would list."""

import pytest

from app.models.anime import Anime
from app.models.media import Media
from app.models.media_studio import MediaStudio
from app.models.studio import Studio
from tests._helpers import media_kwargs

_URL = "/search/anime/uuids"
_STUDIO = "Uu Studio Kept"


@pytest.fixture
async def studio_anime(db_session) -> dict[str, Anime]:
    """Two anime by the test's studio, one by another; nothing else carries either name."""
    studios = {name: Studio(name=name) for name in (_STUDIO, "Uu Studio Other")}
    db_session.add_all(studios.values())
    anime = {}
    for i, (title, studio) in enumerate([("Uu One", _STUDIO), ("Uu Two", _STUDIO), ("Uu Three", "Uu Studio Other")]):
        a = Anime(mal_id=-95200 - i, title=title)
        db_session.add(a)
        await db_session.flush()
        media = Media(**media_kwargs(a.id, -95200 - i, title=title, score=7.0, scored_by=1000))
        db_session.add(media)
        await db_session.flush()
        db_session.add(MediaStudio(media_id=media.id, studio_id=studios[studio].id))
        anime[title] = a
    await db_session.flush()
    return anime


async def test_lists_what_the_search_keeps(client, user_auth_headers, studio_anime):
    res = await client.get(_URL, params={"studio_name": _STUDIO}, headers=user_auth_headers)
    assert res.status_code == 200, res.text
    kept = {str(studio_anime[t].uuid) for t in ("Uu One", "Uu Two")}
    assert set(res.json()) == kept
    listed = await client.get("/search/anime", params={"studio_name": _STUDIO, "limit": 1000}, headers=user_auth_headers)
    assert {row["uuid"] for row in listed.json()} == kept


async def test_personal_filters_narrow_by_the_callers_ratings(client, user_auth_headers, studio_anime):
    # The caller has rated none of the fixture's anime.
    unrated = await client.get(_URL, params={"studio_name": _STUDIO, "rated": "none"}, headers=user_auth_headers)
    assert len(unrated.json()) == 2
    done = await client.get(_URL, params={"studio_name": _STUDIO, "rated": "all"}, headers=user_auth_headers)
    assert done.json() == []


async def test_a_guest_gets_the_catalogue_but_not_their_ratings(client, restricted_user_auth_headers, studio_anime):
    assert (await client.get(_URL, params={"studio_name": _STUDIO}, headers=restricted_user_auth_headers)).status_code == 200
    assert (await client.get(_URL, params={"rated": "none"}, headers=restricted_user_auth_headers)).status_code == 403


@pytest.mark.parametrize(("param", "value"), [("top_percent", 0), ("top_percent", 101), ("genres", "Action")])
async def test_out_of_range_is_rejected(client, user_auth_headers, param, value):
    assert (await client.get(_URL, params={param: value}, headers=user_auth_headers)).status_code == 422
