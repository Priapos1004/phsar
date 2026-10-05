"""The rated-coverage endpoint and the media-level `is_rated` flag it pairs with.

The tier arithmetic is pinned in `tests/services/test_rating_coverage.py`; what
these cover is the wiring — that the route is user-scoped and closed to the one
role that cannot rate, and that `/search/media` reports the caller's own
ratings. Search rows are scoped by a `SentinelSeason` so the assertions hold
against a populated dev catalogue as well as CI's empty one.
"""

from app.models.anime import Anime
from app.models.media import Media
from tests._helpers import SentinelSeason, media_kwargs

_COVERAGE_SEASON = SentinelSeason(1903)


async def _anime_with_media(db_session, mal_seed: int, count: int) -> tuple:
    """No embeddings: every search below passes `query=""`, which is the branch
    `MediaDAO.search_media_by_vector_with_filters` answers without joining
    `MediaSearch` at all."""
    anime = Anime(mal_id=mal_seed, title=f"CoverageFixture{mal_seed}")
    db_session.add(anime)
    await db_session.flush()
    media = [
        Media(**media_kwargs(
            anime.id, mal_seed - i - 1,
            title=f"CoverageFixture{mal_seed} {i}",
            **_COVERAGE_SEASON.columns,
        ))
        for i in range(count)
    ]
    db_session.add_all(media)
    await db_session.flush()
    return anime, media


async def _rate(client, headers, media):
    res = await client.put(
        f"/ratings/media/{media.uuid}",
        json={"rating": 8.0, "watch_status": "completed"},
        headers=headers,
    )
    assert res.status_code == 200


async def _search(client, headers) -> dict[str, bool]:
    res = await client.get("/search/media", params={
        "query": "", "anime_season": _COVERAGE_SEASON.filter,
    }, headers=headers)
    assert res.status_code == 200
    return {r["uuid"]: r["is_rated"] for r in res.json()}


async def test_coverage_reports_the_tier_for_a_rated_anime(client, user_auth_headers, db_session):
    anime, media = await _anime_with_media(db_session, -93000, 2)
    await _rate(client, user_auth_headers, media[0])

    res = await client.get("/ratings/coverage", headers=user_auth_headers)
    assert res.status_code == 200
    assert {e["anime_uuid"]: e["tier"] for e in res.json()}[str(anime.uuid)] == "some"


async def test_coverage_is_closed_to_restricted_users(client, restricted_user_auth_headers):
    """They cannot rate at all, which is why the layout skips this fetch for them."""
    res = await client.get("/ratings/coverage", headers=restricted_user_auth_headers)
    assert res.status_code == 403


async def test_coverage_requires_a_token(client):
    assert (await client.get("/ratings/coverage")).status_code == 401


async def test_search_media_flags_the_callers_own_ratings(client, user_auth_headers, db_session):
    _, media = await _anime_with_media(db_session, -93200, 2)
    await _rate(client, user_auth_headers, media[0])

    by_uuid = await _search(client, user_auth_headers)
    assert by_uuid[str(media[0].uuid)] is True
    assert by_uuid[str(media[1].uuid)] is False


async def test_search_media_does_not_leak_another_users_ratings(
    client, user_auth_headers, admin_auth_headers, db_session,
):
    _, media = await _anime_with_media(db_session, -93300, 1)
    await _rate(client, admin_auth_headers, media[0])

    by_uuid = await _search(client, user_auth_headers)
    assert by_uuid[str(media[0].uuid)] is False
