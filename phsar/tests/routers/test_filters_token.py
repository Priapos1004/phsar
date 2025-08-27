import logging

import pytest

logger = logging.getLogger(__name__)

VALID_FILTER_PAYLOAD = {
    "query": "spy",
    "genre_name": ["Action", "Comedy"],
    "anime_season": ["Winter 2022"],
    "media_type": ["TV"]
}

TOO_LONG_FILTER_PAYLOAD = {
    "query": (
        "In this anime, a group of genetically enhanced teenagers engage in a philosophical battle against "
        "a corrupt government while navigating themes of identity, memory, and artificial intelligence. "
        "The protagonist, haunted by dreams of a parallel world, must choose between saving reality and preserving free will."
    ),
    "genre_name": [
        "Magical Sex Shift",
        "High Stakes Game",
        "Love Status Quo",
        "Performing Arts",
        "Adult Cast"],
    "anime_season": [
        "Winter 2022",
        "Spring 2022",
        "Summer 2022",
        "Summer 2021",
        "Winter 2023"],
    "media_type": ["TV", "Movie", "OVA", "ONA", "TVSpecial"],
    "relation_type": ["main", "summary", "crossover", "other"],
    "age_rating": [
        "G - All Ages",
        "PG - Children",
        "PG-13 - Teens 13 or older",
        "R - 17+ (violence & profanity)",
        "R+ - Mild Nudity"
    ],
    "airing_status": ["Currently Airing", "Finished Airing", "Not Yet Aired"],
    "studio_name": [
        "Studio A with a pretty long name",
        "Studio B also having the longest name ever seen",
        "Studio C having a name that could reach the atmosphere",
        "Studio D with a name that is just too long to be real",
        "Studio E going on and on with its name for no reason at all really no reason at all"
    ],
    "score_min": 0,
    "score_max": 10,
    "scored_by_min": 1000,
    "episodes_min": 1,
    "episodes_max": 100,
    "duration_per_episode_min": 10,
    "duration_per_episode_max": 60,
    "total_watch_time_min": 100,
    "total_watch_time_max": 10000
}

TOO_MANY_ELEMENTS_FILTER_PAYLOAD = {
    "query": "spy",
    "genre_name": ["Action", "Comedy", "Drama", "Fantasy", "Horror", "Mystery", "Romance", "Sci-Fi"],
    "anime_season": ["Winter 2022"],
    "media_type": ["TV"]
}

@pytest.mark.asyncio
async def test_create_token_too_long(client, admin_auth_headers):
    response = await client.post(
        "/filters/create-token",
        json=TOO_LONG_FILTER_PAYLOAD,
        headers=admin_auth_headers
    )
    assert response.status_code == 400, f"Expected 400 for long token, got {response.status_code}"
    logger.debug(f"Create token with too long token response: {response.json()}")
    assert "token is too long" in response.text.lower()

@pytest.mark.asyncio
async def test_create_token_too_many_items(client, admin_auth_headers):
    response = await client.post(
        "/filters/create-token",
        json=TOO_MANY_ELEMENTS_FILTER_PAYLOAD,
        headers=admin_auth_headers
    )
    assert response.status_code == 400, f"Expected 400 for too many filter items, got {response.status_code}"
    logger.debug(f"Create token with too many items response: {response.json()}")
    assert "exceeds maximum allowed items" in response.text.lower()

@pytest.mark.asyncio
async def test_verify_token_missing_search_data(client, admin_auth_headers):
    # Create a valid token with missing 'data' field manually
    from jose import jwt

    from app.core.config import settings

    bad_payload = {
        "ver": settings.CURRENT_SEARCH_API_VERSION,
        # intentionally no 'data' field
    }
    bad_token = jwt.encode(bad_payload, settings.SEARCH_SECRET_KEY, algorithm=settings.ALGORITHM)

    response = await client.post(
        "/filters/verify-token",
        json={"token": bad_token},
        headers=admin_auth_headers
    )
    assert response.status_code == 400, f"Expected 400 for missing search data, got {response.status_code}"
    logger.debug(f"Verify token without search data response: {response.json()}")
    assert "missing search data" in response.text.lower()

@pytest.mark.asyncio
async def test_create_and_verify_token_as_admin(client, admin_auth_headers):
    # Create token
    create_resp = await client.post(
        "/filters/create-token",
        json=VALID_FILTER_PAYLOAD,
        headers=admin_auth_headers
    )
    assert create_resp.status_code == 200, f"Admin create: Expected 200, got {create_resp.status_code}"

    token_data = create_resp.json()
    assert "token" in token_data
    token = token_data["token"]
    assert isinstance(token, str)

    # Verify token
    verify_resp = await client.post(
        "/filters/verify-token",
        json={"token": token},
        headers=admin_auth_headers
    )
    assert verify_resp.status_code == 200, f"Admin verify: Expected 200, got {verify_resp.status_code}"
    data = verify_resp.json()
    assert data["query"] == "spy"
    assert "Action" in data["genre_name"]

@pytest.mark.asyncio
async def test_token_endpoints_as_user(client, user_auth_headers):
    create_resp = await client.post(
        "/filters/create-token",
        json=VALID_FILTER_PAYLOAD,
        headers=user_auth_headers
    )
    assert create_resp.status_code == 200, f"User create: Expected 200, got {create_resp.status_code}"
    token = create_resp.json()["token"]

    verify_resp = await client.post(
        "/filters/verify-token",
        json={"token": token},
        headers=user_auth_headers
    )
    assert verify_resp.status_code == 200, f"User verify: Expected 200, got {verify_resp.status_code}"

@pytest.mark.asyncio
async def test_token_endpoints_as_restricted_user(client, restricted_user_auth_headers):
    create_resp = await client.post(
        "/filters/create-token",
        json=VALID_FILTER_PAYLOAD,
        headers=restricted_user_auth_headers
    )
    assert create_resp.status_code == 200, f"Restricted create: Expected 200, got {create_resp.status_code}"
    token = create_resp.json()["token"]

    verify_resp = await client.post(
        "/filters/verify-token",
        json={"token": token},
        headers=restricted_user_auth_headers
    )
    assert verify_resp.status_code == 200, f"Restricted verify: Expected 200, got {verify_resp.status_code}"

@pytest.mark.asyncio
async def test_token_endpoints_without_token(client):
    # Missing auth for create
    create_resp = await client.post("/filters/create-token", json=VALID_FILTER_PAYLOAD)
    assert create_resp.status_code == 401, f"Create without auth: Expected 401, got {create_resp.status_code}"

    # Invalid token
    fake_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.payload"
    verify_resp = await client.post("/filters/verify-token", json={"token": fake_token})
    assert verify_resp.status_code == 401, f"Verify invalid token: Expected 401, got {verify_resp.status_code}"
