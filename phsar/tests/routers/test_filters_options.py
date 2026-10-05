import pytest

from app.models.anime import Anime
from app.models.media import Media, OriginalSource
from tests._helpers import media_kwargs


@pytest.mark.asyncio
async def test_filters_default_anime(client, admin_auth_headers):
    """Default view_type is anime — verify core filter keys are present."""
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
    assert "duration_per_episode_min" in data
    assert "duration_per_episode_max" in data

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


@pytest.mark.asyncio
async def test_filters_list_sources_without_null(client, admin_auth_headers, db_session):
    """Sources come back A→Z without NULL. Manga sorts before Original but is
    declared after it, so ordering by the column (enum declaration order) fails."""
    anime = Anime(mal_id=86001, title="SourceOptions Anime")
    db_session.add(anime)
    await db_session.flush()
    db_session.add_all([
        Media(**media_kwargs(anime.id, 860011, original_source=OriginalSource.Original)),
        Media(**media_kwargs(anime.id, 860012, original_source=OriginalSource.Manga)),
        Media(**media_kwargs(anime.id, 860013, original_source=None)),
    ])
    await db_session.flush()

    response = await client.get("/filters/options", headers=admin_auth_headers)
    sources = response.json()["original_source"]

    assert {"Manga", "Original"} <= set(sources)
    assert None not in sources
    assert sources == sorted(sources)
