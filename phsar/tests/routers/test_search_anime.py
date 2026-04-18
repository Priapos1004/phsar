import logging

import pytest

from app.models.anime import Anime
from app.models.genre import Genre, GenreType
from app.models.media import Media, MediaType, RelationType, SeasonType
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.studio import Studio
from app.services.anime_search_service import anime_title_texts
from app.services.vector_embedding_service import (
    create_anime_embedding,
    create_media_embedding,
)

logger = logging.getLogger(__name__)


@pytest.fixture
async def anime_with_media(db_session):
    """Create an anime with 3 media of different types/genres/studios for search tests.
    Genre setup: Action on 2/3 media (majority), Romance on 1/3 (not majority)."""
    genre_action = Genre(name="SearchAction", genre_type=GenreType.Genres)
    genre_romance = Genre(name="SearchRomance", genre_type=GenreType.Genres)
    studio = Studio(name="SearchStudio")
    db_session.add_all([genre_action, genre_romance, studio])
    await db_session.flush()

    anime = Anime(
        mal_id=99001, title="Search Test Anime",
        name_eng="Search Test English", description="A great search test anime.",
    )
    db_session.add(anime)
    await db_session.flush()

    # Anime embedding
    await create_anime_embedding(
        db_session, anime_id=anime.id,
        title_texts=anime_title_texts(anime),
        description_text=anime.description or "",
    )

    media_tv = Media(
        anime_id=anime.id, mal_id=99101,
        mal_url="https://myanimelist.net/anime/99101",
        title="Search Test S1", media_type=MediaType.TV,
        relation_type=RelationType.Main, scored_by=5000,
        score=8.0, episodes=24, duration_seconds=1440,
        airing_status="Finished Airing",
        anime_season_name=SeasonType.Spring, anime_season_year=2020,
        age_rating="PG-13 - Teens 13 or older",
    )
    media_movie = Media(
        anime_id=anime.id, mal_id=99102,
        mal_url="https://myanimelist.net/anime/99102",
        title="Search Test Movie", media_type=MediaType.Movie,
        relation_type=RelationType.SideStory, scored_by=3000,
        score=9.0, episodes=1, duration_seconds=7200,
        airing_status="Finished Airing",
        anime_season_name=SeasonType.Winter, anime_season_year=2022,
        age_rating="R - 17+ (violence & profanity)",
    )
    media_ova = Media(
        anime_id=anime.id, mal_id=99103,
        mal_url="https://myanimelist.net/anime/99103",
        title="Search Test OVA", media_type=MediaType.OVA,
        relation_type=RelationType.SideStory, scored_by=500,
        score=7.0, episodes=2, duration_seconds=1800,
        airing_status="Not yet aired",
        age_rating="PG-13 - Teens 13 or older",
    )
    db_session.add_all([media_tv, media_movie, media_ova])
    await db_session.flush()

    # Genre links: Action on TV + Movie (2/3 = majority), Romance on OVA only (1/3 = not majority)
    db_session.add(MediaGenre(media_id=media_tv.id, genre_id=genre_action.id))
    db_session.add(MediaGenre(media_id=media_movie.id, genre_id=genre_action.id))
    db_session.add(MediaGenre(media_id=media_ova.id, genre_id=genre_romance.id))

    # Studio on TV only
    db_session.add(MediaStudio(media_id=media_tv.id, studio_id=studio.id))

    # Media embeddings
    for m in [media_tv, media_movie, media_ova]:
        await create_media_embedding(
            db_session, media_id=m.id,
            title_texts=[m.title], description_text=m.title or "",
        )

    await db_session.flush()
    return {"anime": anime, "tv": media_tv, "movie": media_movie, "ova": media_ova}


async def test_search_anime_no_query(client, user_auth_headers, anime_with_media):
    response = await client.get("/search/anime", headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    # Find our test anime
    anime_result = next((a for a in data if a["title"] == "Search Test Anime"), None)
    assert anime_result is not None


async def test_search_anime_title_query(client, user_auth_headers, anime_with_media):
    response = await client.get("/search/anime", params={
        "query": "Search Test",
    }, headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1
    assert data[0]["title"] == "Search Test Anime"


async def test_search_anime_description_query(client, user_auth_headers, anime_with_media):
    response = await client.get("/search/anime", params={
        "query": "search test",
        "search_type": "description",
    }, headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


async def test_search_anime_aggregated_fields(client, user_auth_headers, anime_with_media):
    """Verify aggregated fields are computed correctly."""
    response = await client.get("/search/anime", params={
        "query": "Search Test",
    }, headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    anime_result = next((a for a in data if a["title"] == "Search Test Anime"), None)
    assert anime_result is not None

    assert anime_result["media_count"] == 3
    # avg score: (8.0 + 9.0 + 7.0) / 3 = 8.0
    assert anime_result["avg_score"] == pytest.approx(8.0, abs=0.01)
    # avg scored_by: (5000 + 3000 + 500) / 3 ≈ 2833
    assert anime_result["avg_scored_by"] == pytest.approx(2833, abs=1)
    # total episodes: 24 + 1 + 2 = 27
    assert anime_result["total_episodes"] == 27


async def test_search_anime_genre_majority(client, user_auth_headers, anime_with_media):
    """Action is on 2/3 media — should appear in genres. Romance is on 1/3 — should not."""
    response = await client.get("/search/anime", params={
        "query": "Search Test",
    }, headers=user_auth_headers)
    data = response.json()
    anime_result = next((a for a in data if a["title"] == "Search Test Anime"), None)
    assert anime_result is not None

    assert "SearchAction" in anime_result["genres"]
    assert "SearchRomance" not in anime_result["genres"]


async def test_search_anime_genre_filter(client, user_auth_headers, anime_with_media):
    """Filter by Action genre — anime should match (2/3 majority)."""
    response = await client.get("/search/anime", params=[
        ("genre_name", "SearchAction"),
    ], headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    anime_result = next((a for a in data if a["title"] == "Search Test Anime"), None)
    assert anime_result is not None


async def test_search_anime_genre_filter_non_majority(client, user_auth_headers, anime_with_media):
    """Filter by Romance genre — anime should NOT match (only 1/3, not majority)."""
    response = await client.get("/search/anime", params=[
        ("genre_name", "SearchRomance"),
    ], headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    anime_result = next((a for a in data if a["title"] == "Search Test Anime"), None)
    assert anime_result is None


async def test_search_anime_studio_filter(client, user_auth_headers, anime_with_media):
    """Studio is on 1 media — any-match should include the anime."""
    response = await client.get("/search/anime", params=[
        ("studio_name", "SearchStudio"),
    ], headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    anime_result = next((a for a in data if a["title"] == "Search Test Anime"), None)
    assert anime_result is not None


async def test_search_anime_range_filter(client, user_auth_headers, anime_with_media):
    """Filter by aggregated score range."""
    # avg score is 8.0 — filter min 7.5, max 8.5 should match
    response = await client.get("/search/anime", params={
        "score_min": 7.5,
        "score_max": 8.5,
    }, headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    anime_result = next((a for a in data if a["title"] == "Search Test Anime"), None)
    assert anime_result is not None


async def test_search_anime_range_filter_excludes(client, user_auth_headers, anime_with_media):
    """Filter by score range that excludes our anime (avg 8.0)."""
    response = await client.get("/search/anime", params={
        "score_min": 9.0,
    }, headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    anime_result = next((a for a in data if a["title"] == "Search Test Anime"), None)
    assert anime_result is None


async def test_search_anime_airing_status(client, user_auth_headers, anime_with_media):
    """Anime has finished + not-yet-aired media — should show has_upcoming."""
    response = await client.get("/search/anime", params={
        "query": "Search Test",
    }, headers=user_auth_headers)
    data = response.json()
    anime_result = next((a for a in data if a["title"] == "Search Test Anime"), None)
    assert anime_result is not None
    assert anime_result["airing_status"] == "Finished Airing"
    assert anime_result["has_upcoming"] is True


async def test_search_anime_season_range(client, user_auth_headers, anime_with_media):
    """Season range should span Spring 2020 to Winter 2022."""
    response = await client.get("/search/anime", params={
        "query": "Search Test",
    }, headers=user_auth_headers)
    data = response.json()
    anime_result = next((a for a in data if a["title"] == "Search Test Anime"), None)
    assert anime_result is not None
    assert anime_result["season_start"] == "Spring 2020"
    assert anime_result["season_end"] == "Winter 2022"


async def test_search_anime_relation_type_counts(client, user_auth_headers, anime_with_media):
    """Should have 1 main and 2 other."""
    response = await client.get("/search/anime", params={
        "query": "Search Test",
    }, headers=user_auth_headers)
    data = response.json()
    anime_result = next((a for a in data if a["title"] == "Search Test Anime"), None)
    assert anime_result is not None
    rt_map = {rt["relation_type"]: rt["count"] for rt in anime_result["relation_types"]}
    assert rt_map.get("main") == 1
    assert rt_map.get("side_story") == 2


async def test_search_anime_rating_notes_rejected(client, user_auth_headers):
    """rating_notes search type should be rejected on anime search."""
    response = await client.get("/search/anime", params={
        "query": "test",
        "search_type": "rating_notes",
    }, headers=user_auth_headers)
    assert response.status_code == 400


async def test_search_anime_unauthorized(client):
    response = await client.get("/search/anime")
    assert response.status_code == 401


# --- Genre majority regression tests ---

@pytest.fixture
async def large_anime_with_genre_majority(db_session):
    """Simulate MHA-like anime: many media where most (but not all) have the genre.
    5/6 media have TestMajority genre = 83% majority."""
    genre = Genre(name="TestMajority", genre_type=GenreType.Genres)
    db_session.add(genre)
    await db_session.flush()

    anime = Anime(mal_id=99900, title="Large Majority Anime", description="Majority test.")
    db_session.add(anime)
    await db_session.flush()

    # Anime embedding
    await create_anime_embedding(
        db_session, anime_id=anime.id,
        title_texts=anime_title_texts(anime),
        description_text=anime.description or "",
    )

    media_ids = []
    for i in range(6):
        m = Media(
            anime_id=anime.id, mal_id=99900 + i + 1,
            mal_url=f"https://myanimelist.net/anime/{99900 + i + 1}",
            title=f"Large Test Media {i+1}",
            media_type=MediaType.TV, relation_type=RelationType.Main,
            scored_by=1000, score=7.0 + i * 0.5, episodes=12,
            airing_status="Finished Airing",
        )
        db_session.add(m)
        await db_session.flush()
        media_ids.append(m.id)

        # Create media embedding
        await create_media_embedding(
            db_session, media_id=m.id,
            title_texts=[m.title], description_text="test",
        )

    # Genre on 5 of 6 media (majority)
    for mid in media_ids[:5]:
        db_session.add(MediaGenre(media_id=mid, genre_id=genre.id))
    await db_session.flush()

    return {"anime": anime, "genre": genre}


async def test_large_anime_genre_majority_included(client, user_auth_headers, large_anime_with_genre_majority):
    """5/6 media have genre — anime should be returned by genre filter."""
    response = await client.get("/search/anime", params=[
        ("genre_name", "TestMajority"),
    ], headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    anime_result = next((a for a in data if a["title"] == "Large Majority Anime"), None)
    assert anime_result is not None
    assert "TestMajority" in anime_result["genres"]


async def test_large_anime_genre_majority_in_display(client, user_auth_headers, large_anime_with_genre_majority):
    """5/6 = 83% majority — genre should appear in the result's genres list."""
    response = await client.get("/search/anime", params={
        "query": "Large Majority",
    }, headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    anime_result = next((a for a in data if a["title"] == "Large Majority Anime"), None)
    assert anime_result is not None
    assert "TestMajority" in anime_result["genres"]


async def test_no_filter_returns_all_anime(client, user_auth_headers, anime_with_media):
    """No filters should return all anime in the database."""
    response = await client.get("/search/anime", headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    # At minimum our test anime should be there; check total is >= 1
    assert len(data) >= 1
    titles = [a["title"] for a in data]
    assert "Search Test Anime" in titles
