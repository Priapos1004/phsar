import pytest

from app.models.anime import Anime
from app.models.media import Media, MediaType, RelationType


@pytest.fixture
async def test_media(db_session):
    """Create a minimal Anime + Media pair for rating tests."""
    anime = Anime(mal_id=99999, title="Test Anime")
    db_session.add(anime)
    await db_session.flush()

    media = Media(
        anime_id=anime.id,
        mal_id=99999,
        mal_url="https://myanimelist.net/anime/99999",
        title="Test Media",
        media_type=MediaType.TV,
        relation_type=RelationType.Main,
        scored_by=0,
        airing_status="Finished Airing",
    )
    db_session.add(media)
    await db_session.flush()
    return media


@pytest.fixture
async def test_media_list(db_session):
    """Create multiple media under one anime for bulk rating tests."""
    anime = Anime(mal_id=88888, title="Bulk Test Anime")
    db_session.add(anime)
    await db_session.flush()

    media_items = []
    for i in range(3):
        media = Media(
            anime_id=anime.id,
            mal_id=88880 + i,
            mal_url=f"https://myanimelist.net/anime/{88880 + i}",
            title=f"Bulk Test Media {i + 1}",
            media_type=MediaType.TV,
            relation_type=RelationType.Main,
            scored_by=0,
            airing_status="Finished Airing",
        )
        db_session.add(media)
        media_items.append(media)
    await db_session.flush()
    return media_items


# --- Upsert (create) ---


async def test_upsert_rating_creates(client, user_auth_headers, test_media):
    response = await client.put(
        f"/ratings/media/{test_media.uuid}",
        json={"rating": 8.5, "dropped": False},
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["rating"] == 8.5
    assert data["dropped"] is False
    assert data["media_uuid"] == str(test_media.uuid)
    assert data["anime_title"] == "Test Anime"


async def test_upsert_rating_with_note(client, user_auth_headers, test_media):
    response = await client.put(
        f"/ratings/media/{test_media.uuid}",
        json={"rating": 9.0, "note": "Great soundtrack"},
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["note"] == "Great soundtrack"


async def test_upsert_rating_with_enums(client, user_auth_headers, test_media):
    response = await client.put(
        f"/ratings/media/{test_media.uuid}",
        json={
            "rating": 7.0,
            "pace": "normal",
            "animation_quality": "good",
            "story_quality": "outstanding",
        },
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["pace"] == "normal"
    assert data["animation_quality"] == "good"
    assert data["story_quality"] == "outstanding"


# --- Upsert (update) ---


async def test_upsert_rating_updates_existing(client, user_auth_headers, test_media):
    # Create
    await client.put(
        f"/ratings/media/{test_media.uuid}",
        json={"rating": 6.0},
        headers=user_auth_headers,
    )
    # Update
    response = await client.put(
        f"/ratings/media/{test_media.uuid}",
        json={"rating": 9.0, "note": "Changed my mind"},
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["rating"] == 9.0
    assert data["note"] == "Changed my mind"


# --- Get single ---


async def test_get_rating_for_media(client, user_auth_headers, test_media):
    await client.put(
        f"/ratings/media/{test_media.uuid}",
        json={"rating": 7.5},
        headers=user_auth_headers,
    )
    response = await client.get(
        f"/ratings/media/{test_media.uuid}",
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["rating"] == 7.5


async def test_get_rating_not_found(client, user_auth_headers, test_media):
    response = await client.get(
        f"/ratings/media/{test_media.uuid}",
        headers=user_auth_headers,
    )
    assert response.status_code == 404


# --- List ---


async def test_list_user_ratings(client, user_auth_headers, test_media_list):
    for media in test_media_list:
        await client.put(
            f"/ratings/media/{media.uuid}",
            json={"rating": 8.0},
            headers=user_auth_headers,
        )

    response = await client.get("/ratings/", headers=user_auth_headers)
    assert response.status_code == 200
    assert len(response.json()) == 3


async def test_list_user_ratings_pagination(client, user_auth_headers, test_media_list):
    for media in test_media_list:
        await client.put(
            f"/ratings/media/{media.uuid}",
            json={"rating": 8.0},
            headers=user_auth_headers,
        )

    response = await client.get(
        "/ratings/", params={"limit": 2, "offset": 0}, headers=user_auth_headers
    )
    assert response.status_code == 200
    assert len(response.json()) == 2

    response = await client.get(
        "/ratings/", params={"limit": 2, "offset": 2}, headers=user_auth_headers
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_list_user_ratings_empty(client, user_auth_headers):
    response = await client.get("/ratings/", headers=user_auth_headers)
    assert response.status_code == 200
    assert response.json() == []


# --- Delete ---


async def test_delete_rating(client, user_auth_headers, test_media):
    create_resp = await client.put(
        f"/ratings/media/{test_media.uuid}",
        json={"rating": 5.0},
        headers=user_auth_headers,
    )
    rating_uuid = create_resp.json()["uuid"]

    delete_resp = await client.delete(
        f"/ratings/{rating_uuid}", headers=user_auth_headers
    )
    assert delete_resp.status_code == 204

    # Confirm gone
    get_resp = await client.get(
        f"/ratings/media/{test_media.uuid}", headers=user_auth_headers
    )
    assert get_resp.status_code == 404


async def test_delete_nonexistent_rating(client, user_auth_headers):
    response = await client.delete(
        "/ratings/00000000-0000-0000-0000-000000000000",
        headers=user_auth_headers,
    )
    assert response.status_code == 404


# --- Bulk upsert ---


async def test_bulk_upsert(client, user_auth_headers, test_media_list):
    uuids = [str(m.uuid) for m in test_media_list]
    response = await client.put(
        "/ratings/bulk",
        json={
            "rating": 7.0,
            "media_uuids": uuids,
            "note": "Solid series overall",
        },
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    # Note should only be on the last media
    assert data[0]["note"] is None
    assert data[1]["note"] is None
    assert data[2]["note"] == "Solid series overall"


# --- Validation ---


async def test_rating_out_of_range(client, user_auth_headers, test_media):
    response = await client.put(
        f"/ratings/media/{test_media.uuid}",
        json={"rating": 11.0},
        headers=user_auth_headers,
    )
    assert response.status_code == 422


async def test_rating_invalid_enum(client, user_auth_headers, test_media):
    response = await client.put(
        f"/ratings/media/{test_media.uuid}",
        json={"rating": 7.0, "pace": "invalid_value"},
        headers=user_auth_headers,
    )
    assert response.status_code == 422


async def test_rating_nonexistent_media(client, user_auth_headers):
    response = await client.put(
        "/ratings/media/00000000-0000-0000-0000-000000000000",
        json={"rating": 7.0},
        headers=user_auth_headers,
    )
    assert response.status_code == 404


# --- Role access ---


async def test_restricted_user_cannot_rate(client, restricted_user_auth_headers, test_media):
    response = await client.put(
        f"/ratings/media/{test_media.uuid}",
        json={"rating": 7.0},
        headers=restricted_user_auth_headers,
    )
    assert response.status_code == 403


async def test_restricted_user_cannot_list_ratings(client, restricted_user_auth_headers):
    response = await client.get("/ratings/", headers=restricted_user_auth_headers)
    assert response.status_code == 403


async def test_no_auth_cannot_rate(client, test_media):
    response = await client.put(
        f"/ratings/media/{test_media.uuid}",
        json={"rating": 7.0},
    )
    assert response.status_code == 401


# --- Admin access ---


async def test_admin_can_rate(client, admin_auth_headers, test_media):
    response = await client.put(
        f"/ratings/media/{test_media.uuid}",
        json={"rating": 8.0},
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
