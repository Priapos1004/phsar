import uuid

import pytest

from app.models.anime import Anime
from app.models.genre import Genre, GenreType
from app.models.media import Media, MediaType, RelationType
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.studio import Studio
from tests._helpers import media_kwargs


@pytest.fixture
async def test_anime_with_siblings(db_session):
    """Anime with 3 Media entries staggered across seasons so sibling
    ordering is testable: OVA (Spring 2019) → main S1 (Winter 2020) →
    Movie (Fall 2021). Querying any of the three exercises a different
    "you are here" slot (0 / 1 / 2) without re-seeding."""
    genre = Genre(name="TestGenreDetail", genre_type=GenreType.Genres)
    studio = Studio(name="TestStudioDetail")
    db_session.add_all([genre, studio])
    await db_session.flush()

    anime = Anime(mal_id=77777, title="Test Anime Series")
    db_session.add(anime)
    await db_session.flush()

    media_main = Media(**media_kwargs(
        anime.id, 77701,
        title="Test Anime S1",
        name_eng="Test Anime Season 1",
        scored_by=1000,
        score=8.5,
        episodes=12,
        description="A great anime about testing.",
        anime_season_name="Winter",
        anime_season_year=2020,
    ))
    media_ova = Media(**media_kwargs(
        anime.id, 77702,
        title="Test Anime OVA",
        media_type=MediaType.OVA,
        relation_type=RelationType.SideStory,
        scored_by=200,
        score=7.0,
        episodes=2,
        anime_season_name="Spring",
        anime_season_year=2019,
    ))
    media_movie = Media(**media_kwargs(
        anime.id, 77703,
        title="Test Anime Movie",
        media_type=MediaType.Movie,
        relation_type=RelationType.SideStory,
        scored_by=500,
        score=9.0,
        episodes=1,
        anime_season_name="Fall",
        anime_season_year=2021,
    ))
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

    # Siblings (excludes self) — chronological order: OVA (Spring 2019) →
    # Movie (Fall 2021). The main S1 (Winter 2020) sits between them, so the
    # marker renders at current_position=1.
    assert [s["title"] for s in data["sibling_media"]] == ["Test Anime OVA", "Test Anime Movie"]
    assert data["current_position"] == 1

    # Sibling schema includes season fields, not score
    for sibling in data["sibling_media"]:
        assert "anime_season_name" in sibling
        assert "anime_season_year" in sibling
        assert "score" not in sibling


async def test_media_detail_score_top_percent(client, user_auth_headers, test_anime_with_siblings):
    """A scored media always gets a top-N% rank in [1, 100]."""
    media = test_anime_with_siblings["main"]
    response = await client.get(f"/media/{media.uuid}", headers=user_auth_headers)
    data = response.json()

    assert data["score_top_percent"] is not None
    assert 1 <= data["score_top_percent"] <= 100


async def test_sibling_position_when_current_is_oldest(client, user_auth_headers, test_anime_with_siblings):
    """Querying the OVA (Spring 2019, oldest) puts the marker before every
    sibling — exercises the leading boundary."""
    ova = test_anime_with_siblings["ova"]
    response = await client.get(f"/media/{ova.uuid}", headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert [s["title"] for s in data["sibling_media"]] == ["Test Anime S1", "Test Anime Movie"]
    assert data["current_position"] == 0


async def test_sibling_position_when_current_is_newest(client, user_auth_headers, test_anime_with_siblings):
    """Querying the Movie (Fall 2021, newest) puts the marker after every
    sibling — exercises the trailing-branch render path in the carousel."""
    movie = test_anime_with_siblings["movie"]
    response = await client.get(f"/media/{movie.uuid}", headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert [s["title"] for s in data["sibling_media"]] == ["Test Anime OVA", "Test Anime S1"]
    assert data["current_position"] == 2


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
