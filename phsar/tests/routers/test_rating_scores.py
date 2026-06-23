import pytest

from app.models.anime import Anime
from app.models.genre import Genre, GenreType
from app.models.media import Media, SeasonType
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.studio import Studio
from tests._helpers import media_kwargs


@pytest.fixture
async def rated_media_two_anime(db_session):
    """Two anime with one media each (one carrying a genre + studio + age) — the
    inputs the rating-consistency helper compares against."""
    genre = Genre(name="ScoreItemGenre", genre_type=GenreType.Genres)
    studio = Studio(name="ScoreItemStudio")
    db_session.add_all([genre, studio])
    await db_session.flush()

    anime_a = Anime(
        mal_id=96001, title="Score Item Anime A", name_eng="Score Anime A (EN)",
        cover_image="https://example/anime_a.jpg",
    )
    anime_b = Anime(mal_id=96002, title="Score Item Anime B")
    db_session.add_all([anime_a, anime_b])
    await db_session.flush()

    # age_rating_numeric is derived from the age_rating string prefix (PG-13 → 13, R → 17).
    # MAL score/votes + watch-time + season feed the /ratings page projection.
    # anime_season_name + anime_season_year are constrained both-or-neither.
    media_a = Media(**media_kwargs(
        anime_a.id, 96101, title="Score Media A", name_eng="Score Media A (EN)",
        age_rating="PG-13 - Teens 13 or older",
        score=8.5, scored_by=1200, episodes=12, duration_seconds=1440,
        anime_season_name=SeasonType.Spring, anime_season_year=2021,
    ))
    media_b = Media(**media_kwargs(anime_b.id, 96102, title="Score Media B", age_rating="R - 17+ (violence & profanity)"))
    db_session.add_all([media_a, media_b])
    await db_session.flush()

    db_session.add(MediaGenre(media_id=media_a.id, genre_id=genre.id))
    db_session.add(MediaStudio(media_id=media_a.id, studio_id=studio.id))
    await db_session.flush()
    return {"media_a": media_a, "media_b": media_b, "anime_a": anime_a, "anime_b": anime_b}


async def test_rating_scores_returns_compact_items(client, user_auth_headers, rated_media_two_anime):
    media_a = rated_media_two_anime["media_a"]
    media_b = rated_media_two_anime["media_b"]
    await client.put(
        f"/ratings/media/{media_a.uuid}",
        json={"rating": 8.0, "watch_status": "completed", "pace": "normal"},
        headers=user_auth_headers,
    )
    await client.put(
        f"/ratings/media/{media_b.uuid}",
        json={"rating": 6.0, "watch_status": "completed"},
        headers=user_auth_headers,
    )

    response = await client.get("/ratings/scores", headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    # Freshly-registered user → exactly the two ratings just created.
    assert len(data) == 2

    by_uuid = {item["media_uuid"]: item for item in data}

    item_a = by_uuid[str(media_a.uuid)]
    assert item_a["anime_uuid"] == str(rated_media_two_anime["anime_a"].uuid)
    # eng/jap names ride along so the frontend can resolve titles per the user's language
    assert item_a["media_name_eng"] == "Score Media A (EN)"
    assert item_a["anime_name_eng"] == "Score Anime A (EN)"
    assert item_a["media_name_jap"] is None
    assert item_a["rating"] == 8.0
    assert item_a["genres"] == ["ScoreItemGenre"]
    assert item_a["studios"] == ["ScoreItemStudio"]
    assert item_a["age_rating_numeric"] == 13
    assert item_a["pace"] == "normal"
    assert "modified_at" in item_a
    assert "created_at" in item_a
    # /ratings page projection fields
    assert item_a["anime_cover_image"] == "https://example/anime_a.jpg"
    assert item_a["mal_score"] == 8.5
    assert item_a["scored_by"] == 1200
    assert item_a["episodes"] == 12
    assert item_a["total_watch_time"] == 12 * 1440  # episodes × duration_seconds
    assert item_a["anime_season_year"] == 2021

    item_b = by_uuid[str(media_b.uuid)]
    assert item_b["genres"] == []
    assert item_b["studios"] == []
    assert item_b["age_rating_numeric"] == 17
    # media_b carries no MAL score and no season/duration → nulls + zero votes
    assert item_b["mal_score"] is None
    assert item_b["scored_by"] == 0
    assert item_b["total_watch_time"] is None
    assert item_b["anime_season_year"] is None
    assert item_b["anime_cover_image"] is None


async def test_rating_scores_unauthorized(client):
    response = await client.get("/ratings/scores")
    assert response.status_code == 401
