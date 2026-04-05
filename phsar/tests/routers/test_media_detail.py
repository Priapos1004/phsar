import uuid

import pytest

from app.models.anime import Anime
from app.models.genre import Genre, GenreType
from app.models.media import Media, MediaType, RelationType
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.studio import Studio


@pytest.fixture
async def test_anime_with_siblings(db_session):
    """Create an Anime with 3 Media entries (different types/relations), each with a genre and studio."""
    genre = Genre(name="TestGenreDetail", genre_type=GenreType.Genres)
    studio = Studio(name="TestStudioDetail")
    db_session.add_all([genre, studio])
    await db_session.flush()

    anime = Anime(mal_id=77777, title="Test Anime Series")
    db_session.add(anime)
    await db_session.flush()

    media_main = Media(
        anime_id=anime.id,
        mal_id=77701,
        mal_url="https://myanimelist.net/anime/77701",
        title="Test Anime S1",
        name_eng="Test Anime Season 1",
        media_type=MediaType.TV,
        relation_type=RelationType.Main,
        scored_by=1000,
        score=8.5,
        episodes=12,
        airing_status="Finished Airing",
        description="A great anime about testing.",
    )
    media_ova = Media(
        anime_id=anime.id,
        mal_id=77702,
        mal_url="https://myanimelist.net/anime/77702",
        title="Test Anime OVA",
        media_type=MediaType.OVA,
        relation_type=RelationType.Other,
        scored_by=200,
        score=7.0,
        episodes=2,
        airing_status="Finished Airing",
    )
    media_movie = Media(
        anime_id=anime.id,
        mal_id=77703,
        mal_url="https://myanimelist.net/anime/77703",
        title="Test Anime Movie",
        media_type=MediaType.Movie,
        relation_type=RelationType.Other,
        scored_by=500,
        score=9.0,
        episodes=1,
        airing_status="Finished Airing",
    )
    db_session.add_all([media_main, media_ova, media_movie])
    await db_session.flush()

    # Link genre and studio to main media
    db_session.add(MediaGenre(media_id=media_main.id, genre_id=genre.id))
    db_session.add(MediaStudio(media_id=media_main.id, studio_id=studio.id))
    await db_session.flush()

    return {"anime": anime, "main": media_main, "ova": media_ova, "movie": media_movie}


async def test_get_media_detail(client, user_auth_headers, test_anime_with_siblings):
    media = test_anime_with_siblings["main"]
    response = await client.get(f"/media/{media.uuid}", headers=user_auth_headers)

    assert response.status_code == 200
    data = response.json()

    # Core fields
    assert data["uuid"] == str(media.uuid)
    assert data["title"] == "Test Anime S1"
    assert data["name_eng"] == "Test Anime Season 1"
    assert data["media_type"] == "TV"
    assert data["relation_type"] == "main"
    assert data["score"] == 8.5
    assert data["episodes"] == 12
    assert data["description"] == "A great anime about testing."

    # Anime relationship
    assert data["anime_title"] == "Test Anime Series"

    # Genre and studio
    assert "TestGenreDetail" in data["genres"]
    assert "TestStudioDetail" in data["studio"]

    # Siblings (excludes self)
    assert len(data["sibling_media"]) == 2
    sibling_titles = {s["title"] for s in data["sibling_media"]}
    assert sibling_titles == {"Test Anime OVA", "Test Anime Movie"}


async def test_get_media_detail_not_found(client, user_auth_headers):
    fake_uuid = uuid.uuid4()
    response = await client.get(f"/media/{fake_uuid}", headers=user_auth_headers)
    assert response.status_code == 404


async def test_restricted_user_can_view(client, restricted_user_auth_headers, test_anime_with_siblings):
    media = test_anime_with_siblings["main"]
    response = await client.get(f"/media/{media.uuid}", headers=restricted_user_auth_headers)
    assert response.status_code == 200
    assert response.json()["title"] == "Test Anime S1"


async def test_unauthenticated_cannot_view(client, test_anime_with_siblings):
    media = test_anime_with_siblings["main"]
    response = await client.get(f"/media/{media.uuid}")
    assert response.status_code == 401
