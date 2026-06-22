import pytest

from app.models.genre import Genre, GenreType


@pytest.fixture
async def genre_with_description(db_session):
    genre = Genre(
        name="ZTestGenreWithDesc",
        genre_type=GenreType.Genres,
        description="A test genre description.",
    )
    db_session.add(genre)
    await db_session.flush()
    return genre


async def test_filters_genres_returns_name_and_description(
    client, user_auth_headers, genre_with_description,
):
    response = await client.get("/filters/genres", headers=user_auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)

    entry = next((g for g in data if g["name"] == "ZTestGenreWithDesc"), None)
    assert entry is not None
    assert entry["description"] == "A test genre description."


async def test_filters_genres_unauthorized(client):
    response = await client.get("/filters/genres")
    assert response.status_code == 401
