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
    episode_counts = [12, 24, 6]
    for i in range(3):
        media = Media(
            anime_id=anime.id,
            mal_id=88880 + i,
            mal_url=f"https://myanimelist.net/anime/{88880 + i}",
            title=f"Bulk Test Media {i + 1}",
            media_type=MediaType.TV,
            relation_type=RelationType.Main,
            episodes=episode_counts[i],
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

    response = await client.get("/ratings", headers=user_auth_headers)
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
        "/ratings", params={"limit": 2, "offset": 0}, headers=user_auth_headers
    )
    assert response.status_code == 200
    assert len(response.json()) == 2

    response = await client.get(
        "/ratings", params={"limit": 2, "offset": 2}, headers=user_auth_headers
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_list_user_ratings_empty(client, user_auth_headers):
    response = await client.get("/ratings", headers=user_auth_headers)
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
    # Episodes watched auto-filled from each media's episode count
    assert data[0]["episodes_watched"] == 12
    assert data[1]["episodes_watched"] == 24
    assert data[2]["episodes_watched"] == 6


async def test_bulk_upsert_note_on_last_main_media(client, user_auth_headers, db_session):
    """Note should land on the last 'main' media, not the last media overall."""
    anime = Anime(mal_id=77777, title="Mixed Relation Anime")
    db_session.add(anime)
    await db_session.flush()

    media_items = []
    relation_types = [RelationType.Main, RelationType.Main, RelationType.SideStory]
    for i, rt in enumerate(relation_types):
        media = Media(
            anime_id=anime.id,
            mal_id=77770 + i,
            mal_url=f"https://myanimelist.net/anime/{77770 + i}",
            title=f"Mixed Media {i + 1}",
            media_type=MediaType.TV,
            relation_type=rt,
            scored_by=0,
            airing_status="Finished Airing",
        )
        db_session.add(media)
        media_items.append(media)
    await db_session.flush()

    uuids = [str(m.uuid) for m in media_items]
    response = await client.put(
        "/ratings/bulk",
        json={"rating": 8.0, "media_uuids": uuids, "note": "Great anime"},
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    # Note on index 1 (last main), not index 2 (last overall, which is "other")
    assert data[0]["note"] is None
    assert data[1]["note"] == "Great anime"
    assert data[2]["note"] is None


async def test_get_ratings_for_anime(client, user_auth_headers, test_media_list):
    """GET /ratings/anime/{uuid} returns all user ratings for media in that anime."""
    # Rate 2 of the 3 media
    for media in test_media_list[:2]:
        await client.put(
            f"/ratings/media/{media.uuid}",
            json={"rating": 7.5},
            headers=user_auth_headers,
        )

    # Fetch the anime UUID via the media detail endpoint (requires auth)
    media_resp = await client.get(
        f"/media/{test_media_list[0].uuid}",
        headers=user_auth_headers,
    )
    anime_uuid = media_resp.json()["anime_uuid"]

    response = await client.get(
        f"/ratings/anime/{anime_uuid}",
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(r["rating"] == 7.5 for r in data)


async def test_bulk_delete(client, user_auth_headers, test_media_list):
    """DELETE /ratings/bulk removes ratings for selected media."""
    # First, bulk-rate all 3
    uuids = [str(m.uuid) for m in test_media_list]
    await client.put(
        "/ratings/bulk",
        json={"rating": 7.0, "media_uuids": uuids},
        headers=user_auth_headers,
    )

    # Delete ratings for the first 2 media
    response = await client.post(
        "/ratings/bulk-delete",
        json={"media_uuids": uuids[:2]},
        headers=user_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["deleted"] == 2

    # Only 1 rating should remain
    list_resp = await client.get("/ratings", headers=user_auth_headers)
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["media_title"] == "Bulk Test Media 3"


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
    response = await client.get("/ratings", headers=restricted_user_auth_headers)
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
