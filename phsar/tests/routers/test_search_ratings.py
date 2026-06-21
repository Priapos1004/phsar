import pytest

from app.models.anime import Anime
from app.models.media import Media
from tests._helpers import media_kwargs

_RATED_MEDIA_DATA = [
    ("Action Search Media", 9.0, "fast"),
    ("Drama Search Media", 6.0, "slow"),
    ("Comedy Search Media", 7.5, None),
]


@pytest.fixture
async def rated_media(client, user_auth_headers, db_session):
    """Create media and rate them so the search endpoint has data to return."""
    anime = Anime(mal_id=77777, title="Search Test Anime")
    db_session.add(anime)
    await db_session.flush()

    media_items = []
    for i, (title, rating, pace) in enumerate(_RATED_MEDIA_DATA):
        media = Media(**media_kwargs(
            anime.id, 77770 + i,
            title=title,
            scored_by=100,
            score=8.0,
        ))
        db_session.add(media)
        media_items.append(media)
    await db_session.flush()

    for media, (_, rating, pace) in zip(media_items, _RATED_MEDIA_DATA):
        body = {"rating": rating}
        if pace:
            body["pace"] = pace
        await client.put(
            f"/ratings/media/{media.uuid}",
            json=body,
            headers=user_auth_headers,
        )

    return media_items


# --- Basic search ---


async def test_search_ratings_empty(client, user_auth_headers):
    response = await client.get("/search/ratings", headers=user_auth_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_search_ratings_returns_results(client, user_auth_headers, rated_media):
    response = await client.get("/search/ratings", headers=user_auth_headers)
    assert response.status_code == 200
    assert len(response.json()) == 3


# --- Rating-specific filters ---


async def test_search_ratings_filter_by_pace(client, user_auth_headers, rated_media):
    response = await client.get(
        "/search/ratings",
        params={"pace": "fast"},
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["pace"] == "fast"


async def test_search_ratings_filter_by_user_rating_min(client, user_auth_headers, rated_media):
    response = await client.get(
        "/search/ratings",
        params={"user_rating_min": 7.0},
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(r["user_rating"] >= 7.0 for r in data)


async def test_search_ratings_filter_by_user_rating_range(client, user_auth_headers, rated_media):
    response = await client.get(
        "/search/ratings",
        params={"user_rating_min": 7.0, "user_rating_max": 8.0},
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["user_rating"] == 7.5


async def test_search_ratings_filter_by_watch_status(client, user_auth_headers, rated_media):
    # All fixture ratings default to completed
    response = await client.get(
        "/search/ratings",
        params={"watch_status": "completed"},
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    assert len(response.json()) == 3

    # None are on_hold
    response = await client.get(
        "/search/ratings",
        params={"watch_status": "on_hold"},
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    assert len(response.json()) == 0


# --- Media filters on rating search ---


async def test_search_ratings_with_media_filter(client, user_auth_headers, rated_media):
    response = await client.get(
        "/search/ratings",
        params={"media_type": "TV"},
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    assert len(response.json()) == 3


async def test_search_ratings_with_relation_type_filter(client, user_auth_headers, rated_media):
    response = await client.get(
        "/search/ratings",
        params={"relation_type": "summary"},
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    assert len(response.json()) == 0


# --- Limit ---


async def test_search_ratings_limit(client, user_auth_headers, rated_media):
    response = await client.get(
        "/search/ratings",
        params={"limit": 1},
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


# --- Role access ---


async def test_search_ratings_restricted_user(client, restricted_user_auth_headers):
    response = await client.get("/search/ratings", headers=restricted_user_auth_headers)
    assert response.status_code == 403


async def test_search_ratings_no_auth(client):
    response = await client.get("/search/ratings")
    assert response.status_code == 401


# --- Validation ---


async def test_search_ratings_invalid_pace_filter(client, user_auth_headers):
    response = await client.get(
        "/search/ratings",
        params={"pace": "nonexistent_pace"},
        headers=user_auth_headers,
    )
    assert response.status_code == 422


async def test_search_ratings_invalid_limit(client, user_auth_headers):
    response = await client.get(
        "/search/ratings",
        params={"limit": 0},
        headers=user_auth_headers,
    )
    assert response.status_code == 422
