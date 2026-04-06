import pytest


@pytest.mark.asyncio
async def test_filters_default_media(client, admin_auth_headers):
    response = await client.get("/filters/options", headers=admin_auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "genre_name" in data
    assert "episodes_min" in data
    assert "duration_per_episode_min" in data

@pytest.mark.asyncio
async def test_filters_media_view(client, admin_auth_headers):
    response = await client.get("/filters/options", params={"view_type": "media"}, headers=admin_auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["duration_per_episode_min"] is not None or data["duration_per_episode_max"] is not None

@pytest.mark.asyncio
async def test_filters_anime_view(client, admin_auth_headers):
    response = await client.get("/filters/options", params={"view_type": "anime"}, headers=admin_auth_headers)
    assert response.status_code == 200
    data = response.json()
    # Anime view has no duration-per-episode filter
    assert data["duration_per_episode_min"] is None
    assert data["duration_per_episode_max"] is None

@pytest.mark.asyncio
async def test_filters_as_user(client, user_auth_headers):
    response = await client.get("/filters/options", headers=user_auth_headers)
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_filters_as_restricted_user(client, restricted_user_auth_headers):
    response = await client.get("/filters/options", headers=restricted_user_auth_headers)
    assert response.status_code == 200

@pytest.mark.asyncio
async def test_filters_without_token(client):
    response = await client.get("/filters/options")
    assert response.status_code == 401
