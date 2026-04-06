import uuid

import pytest

from app.models.anime import Anime
from app.models.genre import Genre, GenreType
from app.models.media import Media, MediaType, RelationType, SeasonType
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.studio import Studio


@pytest.fixture
async def anime_for_detail(db_session):
    """Create an anime with 3 media for detail page tests."""
    genre_action = Genre(name="DetailAction", genre_type=GenreType.Genres)
    genre_comedy = Genre(name="DetailComedy", genre_type=GenreType.Genres)
    studio = Studio(name="DetailStudio")
    db_session.add_all([genre_action, genre_comedy, studio])
    await db_session.flush()

    anime = Anime(
        mal_id=88001, title="Detail Test Anime",
        name_eng="Detail Test English", name_jap="Detail Test Japanese",
        other_names=["DTA", "Detail Alt"],
        description="A detailed test anime description.",
        cover_image="https://example.com/cover.jpg",
    )
    db_session.add(anime)
    await db_session.flush()

    media_s1 = Media(
        anime_id=anime.id, mal_id=88101,
        mal_url="https://myanimelist.net/anime/88101",
        title="Detail S1", media_type=MediaType.TV,
        relation_type=RelationType.Main, scored_by=4000,
        score=8.5, episodes=12, duration_seconds=1440,
        airing_status="Finished Airing",
        anime_season_name=SeasonType.Spring, anime_season_year=2020,
        age_rating="PG-13 - Teens 13 or older",
    )
    media_s2 = Media(
        anime_id=anime.id, mal_id=88102,
        mal_url="https://myanimelist.net/anime/88102",
        title="Detail S2", media_type=MediaType.TV,
        relation_type=RelationType.Main, scored_by=3000,
        score=9.0, episodes=12, duration_seconds=1440,
        airing_status="Currently Airing",
        anime_season_name=SeasonType.Fall, anime_season_year=2021,
        age_rating="PG-13 - Teens 13 or older",
    )
    media_movie = Media(
        anime_id=anime.id, mal_id=88103,
        mal_url="https://myanimelist.net/anime/88103",
        title="Detail Movie", media_type=MediaType.Movie,
        relation_type=RelationType.Other, scored_by=1000,
        score=7.0, episodes=1, duration_seconds=7200,
        airing_status="Not yet aired",
        age_rating="R - 17+ (violence & profanity)",
    )
    db_session.add_all([media_s1, media_s2, media_movie])
    await db_session.flush()

    # Action on S1 + S2 (2/3 majority), Comedy on Movie only (1/3)
    db_session.add(MediaGenre(media_id=media_s1.id, genre_id=genre_action.id))
    db_session.add(MediaGenre(media_id=media_s2.id, genre_id=genre_action.id))
    db_session.add(MediaGenre(media_id=media_movie.id, genre_id=genre_comedy.id))

    # Studio on S1
    db_session.add(MediaStudio(media_id=media_s1.id, studio_id=studio.id))
    await db_session.flush()

    return {"anime": anime, "s1": media_s1, "s2": media_s2, "movie": media_movie}


async def test_get_anime_detail(client, user_auth_headers, anime_for_detail):
    anime = anime_for_detail["anime"]
    response = await client.get(f"/media/anime/{anime.uuid}", headers=user_auth_headers)

    assert response.status_code == 200
    data = response.json()

    # Core fields
    assert data["uuid"] == str(anime.uuid)
    assert data["title"] == "Detail Test Anime"
    assert data["name_eng"] == "Detail Test English"
    assert data["name_jap"] == "Detail Test Japanese"
    assert data["other_names"] == ["DTA", "Detail Alt"]
    assert data["description"] == "A detailed test anime description."
    assert data["cover_image"] == "https://example.com/cover.jpg"


async def test_anime_detail_aggregated_values(client, user_auth_headers, anime_for_detail):
    anime = anime_for_detail["anime"]
    response = await client.get(f"/media/anime/{anime.uuid}", headers=user_auth_headers)
    data = response.json()

    # avg score: (8.5 + 9.0 + 7.0) / 3 ≈ 8.17
    assert data["avg_score"] == pytest.approx(8.17, abs=0.01)
    # avg scored_by: (4000 + 3000 + 1000) / 3 ≈ 2667
    assert data["avg_scored_by"] == pytest.approx(2667, abs=1)
    # total episodes: 12 + 12 + 1 = 25
    assert data["total_episodes"] == 25


async def test_anime_detail_genres_majority(client, user_auth_headers, anime_for_detail):
    anime = anime_for_detail["anime"]
    response = await client.get(f"/media/anime/{anime.uuid}", headers=user_auth_headers)
    data = response.json()

    # Action on 2/3 = majority, Comedy on 1/3 = not majority
    assert "DetailAction" in data["genres"]
    assert "DetailComedy" not in data["genres"]


async def test_anime_detail_studios(client, user_auth_headers, anime_for_detail):
    anime = anime_for_detail["anime"]
    response = await client.get(f"/media/anime/{anime.uuid}", headers=user_auth_headers)
    data = response.json()

    assert "DetailStudio" in data["studios"]


async def test_anime_detail_airing_status(client, user_auth_headers, anime_for_detail):
    """Has Currently Airing + Not yet aired → status=Currently Airing, has_upcoming=True."""
    anime = anime_for_detail["anime"]
    response = await client.get(f"/media/anime/{anime.uuid}", headers=user_auth_headers)
    data = response.json()

    assert data["airing_status"] == "Currently Airing"
    assert data["has_upcoming"] is True


async def test_anime_detail_season_range(client, user_auth_headers, anime_for_detail):
    anime = anime_for_detail["anime"]
    response = await client.get(f"/media/anime/{anime.uuid}", headers=user_auth_headers)
    data = response.json()

    assert data["season_start"] == "Spring 2020"
    assert data["season_end"] == "Fall 2021"


async def test_anime_detail_media_list(client, user_auth_headers, anime_for_detail):
    anime = anime_for_detail["anime"]
    response = await client.get(f"/media/anime/{anime.uuid}", headers=user_auth_headers)
    data = response.json()

    assert len(data["media"]) == 3
    titles = {m["title"] for m in data["media"]}
    assert titles == {"Detail S1", "Detail S2", "Detail Movie"}


async def test_anime_detail_media_items_have_genres(client, user_auth_headers, anime_for_detail):
    anime = anime_for_detail["anime"]
    response = await client.get(f"/media/anime/{anime.uuid}", headers=user_auth_headers)
    data = response.json()

    s1 = next(m for m in data["media"] if m["title"] == "Detail S1")
    assert "DetailAction" in s1["genres"]
    assert "DetailStudio" in s1["studios"]


async def test_anime_detail_not_found(client, user_auth_headers):
    fake_uuid = uuid.uuid4()
    response = await client.get(f"/media/anime/{fake_uuid}", headers=user_auth_headers)
    assert response.status_code == 404


async def test_anime_detail_unauthorized(client, anime_for_detail):
    anime = anime_for_detail["anime"]
    response = await client.get(f"/media/anime/{anime.uuid}")
    assert response.status_code == 401


async def test_anime_detail_restricted_user(client, restricted_user_auth_headers, anime_for_detail):
    anime = anime_for_detail["anime"]
    response = await client.get(f"/media/anime/{anime.uuid}", headers=restricted_user_auth_headers)
    assert response.status_code == 200
    assert response.json()["title"] == "Detail Test Anime"
