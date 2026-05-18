import logging

import pytest

logger = logging.getLogger(__name__)

# Fake anime data (shared)
FAKE_ANIME_MAL_ID = -54321
FAKE_SEARCH_RESULTS = [
    {
        "anime_mal_id": FAKE_ANIME_MAL_ID,
        "unconnected_media_list": [
            {
                "mal_id": FAKE_ANIME_MAL_ID,
                "mal_url": "https://myanimelist.net/anime/54321/Fake_Anime",
                "title": "Fake Anime Title",
                "name_eng": "Fake Anime English",
                "name_jap": "フェイクアニメ",
                "other_names": ["Fake Alt Title"],
                "media_type": "TV",
                "relation_type": "main",
                "age_rating": "PG-13",
                "description": "A fake anime used for testing.",
                "original_source": "Manga",
                "cover_image": "https://cdn.fake/fakeanime.jpg",
                "score": 8.7,
                "scored_by": 12345,
                "episodes": 12,
                "anime_season_name": "Spring",
                "anime_season_year": 2025,
                "airing_status": "finished",
                "aired_from": "2025-04-01T00:00:00",
                "aired_to": "2025-06-17T00:00:00",
                "duration": "24 min per ep",
                "duration_seconds": 1440,
                "genres": ["Action", "Adventure"],
                "studio": ["Fake Studio"],
            }
        ]
    }
]

@pytest.mark.asyncio
async def test_save_search_results_as_admin(client, admin_auth_headers):
    # Save as admin — should succeed
    response = await client.post("/save/search-results", json=FAKE_SEARCH_RESULTS, headers=admin_auth_headers)
    assert response.status_code == 200, f"Admin: Expected 200 OK, got {response.status_code}"

@pytest.mark.asyncio
async def test_save_search_results_as_user(client, user_auth_headers):
    # Save as normal user — should succeed
    response = await client.post("/save/search-results", json=FAKE_SEARCH_RESULTS, headers=user_auth_headers)
    assert response.status_code == 200, f"User: Expected 200 OK, got {response.status_code}"

@pytest.mark.asyncio
async def test_save_search_results_twice(client, user_auth_headers):
    # Save result the first time — should succeed
    response = await client.post("/save/search-results", json=FAKE_SEARCH_RESULTS, headers=user_auth_headers)
    assert response.status_code == 200, f"User: Expected 200 OK, got {response.status_code}"

    # Save result the second time — should fail (Conflict)
    response = await client.post("/save/search-results", json=FAKE_SEARCH_RESULTS, headers=user_auth_headers)
    assert response.status_code == 409, f"User: Expected 409 Conflict, got {response.status_code}"
    logger.debug(f"Duplicate save attempt response: {response.status_code} {response.json()}")

@pytest.mark.asyncio
async def test_save_search_results_as_restricted_user(client, restricted_user_auth_headers):
    # Save as restricted user — should fail (Forbidden)
    response = await client.post("/save/search-results", json=FAKE_SEARCH_RESULTS, headers=restricted_user_auth_headers)
    assert response.status_code == 403, f"Restricted user: Expected 403 Forbidden, got {response.status_code}"
    logger.debug(f"Restricted user save attempt response: {response.status_code} {response.json()}")

@pytest.mark.asyncio
async def test_save_search_results_without_token(client):
    # No auth header — should fail (Unauthorized)
    response = await client.post("/save/search-results", json=FAKE_SEARCH_RESULTS)
    assert response.status_code == 401, f"Expected 401 Unauthorized, got {response.status_code}"


@pytest.mark.asyncio
async def test_save_creates_anime_freshness_sidecar(client, user_auth_headers, db_session):
    """Every catalog row born with its sidecar — sweep tier query relies
    on this so its LEFT JOIN + COALESCE stays defensive belt-and-braces
    rather than load-bearing."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.anime import Anime

    resp = await client.post("/save/search-results", json=FAKE_SEARCH_RESULTS, headers=user_auth_headers)
    assert resp.status_code == 200

    result = await db_session.execute(
        select(Anime)
        .where(Anime.mal_id == FAKE_ANIME_MAL_ID)
        .options(selectinload(Anime.freshness))
    )
    anime = result.scalars().first()
    assert anime is not None
    assert anime.freshness is not None
    assert anime.freshness.last_checked_at is None
    assert anime.freshness.stable_check_count == 0


@pytest.mark.asyncio
async def test_save_creates_media_freshness_sidecars(client, user_auth_headers, db_session):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.anime import Anime
    from app.models.media import Media

    resp = await client.post("/save/search-results", json=FAKE_SEARCH_RESULTS, headers=user_auth_headers)
    assert resp.status_code == 200

    result = await db_session.execute(
        select(Anime)
        .where(Anime.mal_id == FAKE_ANIME_MAL_ID)
        .options(selectinload(Anime.media).selectinload(Media.freshness))
    )
    anime = result.scalars().first()
    assert anime is not None
    assert len(anime.media) >= 1
    for media in anime.media:
        assert media.freshness is not None
        assert media.freshness.last_checked_at is None


@pytest.mark.asyncio
async def test_save_populates_spoiler_cache_for_existing_users(client, user_auth_headers):
    # Regression: existing users need spoiler cache refreshed on new anime saves.
    await client.put("/users/settings", json={"spoiler_level": "hide"}, headers=user_auth_headers)

    save_resp = await client.post("/save/search-results", json=FAKE_SEARCH_RESULTS, headers=user_auth_headers)
    assert save_resp.status_code == 200

    # Narrow with a title query so the fake row isn't pushed off the
    # default 50-row page by real catalog data in a dev DB.
    search_resp = await client.get(
        "/search/media", params={"query": "Fake Anime Title"}, headers=user_auth_headers
    )
    assert search_resp.status_code == 200
    titles = [m["title"] for m in search_resp.json()]
    assert "Fake Anime Title" in titles, f"Expected first main visible under hide, got {titles}"
