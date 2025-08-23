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
                "fsk": "PG-13",
                "description": "A fake anime used for testing.",
                "original_source": "Manga",
                "cover_image": "https://cdn.fake/fakeanime.jpg",
                "score": 8.7,
                "scored_by": 12345,
                "episodes": 12,
                "anime_season": "Spring 2025",
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
