import pytest

from app.models.anime import Anime
from app.models.media import Media
from tests._helpers import media_kwargs

_RATED_MEDIA_DATA = [
    ("Action Search Media", {"rating": 9.0, "pace": "fast"}),
    ("Drama Search Media", {"rating": 6.0, "pace": "slow"}),
    ("Comedy Search Media", {"rating": 7.5}),
]


async def _rate_new_media(
    client, headers, db_session, *, mal_id: int, rated: list[tuple[str, dict]],
) -> list[Media]:
    """One anime whose media carry `rated`'s titles, each rated by the caller with
    its body, in list order."""
    anime = Anime(mal_id=mal_id, title=f"Ratings Search Anime {mal_id}")
    db_session.add(anime)
    await db_session.flush()
    media_items = [
        Media(**media_kwargs(anime.id, mal_id * 10 + i, title=title, scored_by=100, score=8.0))
        for i, (title, _) in enumerate(rated)
    ]
    db_session.add_all(media_items)
    await db_session.flush()
    for media, (_, body) in zip(media_items, rated, strict=True):
        resp = await client.put(f"/ratings/media/{media.uuid}", json=body, headers=headers)
        assert resp.status_code == 200, resp.text
    return media_items


@pytest.fixture
async def rated_media(client, user_auth_headers, db_session):
    """Create media and rate them so the search endpoint has data to return."""
    return await _rate_new_media(
        client, user_auth_headers, db_session, mal_id=77777, rated=_RATED_MEDIA_DATA,
    )


# --- Basic search ---


async def test_search_ratings_empty(client, user_auth_headers):
    response = await client.get("/search/ratings", headers=user_auth_headers)
    assert response.status_code == 200
    assert response.json() == []


async def test_search_ratings_returns_results(client, user_auth_headers, rated_media):
    response = await client.get("/search/ratings", headers=user_auth_headers)
    assert response.status_code == 200
    assert len(response.json()) == 3


async def test_search_ratings_title_query_ranks_substring_hits_first(
    client, user_auth_headers, db_session,
):
    """A title query over your ratings filters like the catalogue search does.

    None of these media carries a search embedding, so a hit at all proves the
    title path joins none. Rated in fixture order, newest-first recency puts
    "Lord, of Ashes" ahead; only the substring tier puts "Overlord of Darkness"
    there — and only once the padded query is stripped, since `%  lord of  %` is
    contained in no title."""
    await _rate_new_media(client, user_auth_headers, db_session, mal_id=77801, rated=[
        (title, {"rating": 7.0})
        for title in ("Overlord of Darkness", "Lord, of Ashes", "Unrelated Anime")
    ])

    response = await client.get(
        "/search/ratings", params={"query": "  lord of  "}, headers=user_auth_headers,
    )
    assert response.status_code == 200
    assert [r["title"] for r in response.json()] == ["Overlord of Darkness", "Lord, of Ashes"]


async def test_search_ratings_title_query_falls_back_when_nothing_matches(
    client, user_auth_headers, rated_media,
):
    """"comdy" splits its match on "comedy" mid-word (0.5) and stays under the
    first threshold; with nothing above it, the fallback finds the row."""
    response = await client.get(
        "/search/ratings", params={"query": "comdy"}, headers=user_auth_headers,
    )
    assert response.status_code == 200
    assert [r["title"] for r in response.json()] == ["Comedy Search Media"]


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

