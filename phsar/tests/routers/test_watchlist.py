"""Watchlist router — tag + entry endpoints (v0.15.0)."""

import pytest

from app.models.anime import Anime
from app.models.media import Media
from tests._helpers import media_kwargs


# NEGATIVE mal_ids so fixtures can't collide with the dev DB's real catalog on the
# globally-unique media.mal_id (real MAL ids are always positive) — the suite-wide
# convention documented in tests/seeders/test_relation_backfiller.py.
@pytest.fixture
async def test_media(db_session):
    anime = Anime(mal_id=-61000, title="WL Test Anime")
    db_session.add(anime)
    await db_session.flush()
    media = Media(**media_kwargs(anime.id, -61001, title="WL Test Media"))
    db_session.add(media)
    await db_session.flush()
    return media


@pytest.fixture
async def test_media_list(db_session):
    anime = Anime(mal_id=-62000, title="WL Bulk Anime")
    db_session.add(anime)
    await db_session.flush()
    media = [Media(**media_kwargs(anime.id, -62001 - i, title=f"WL Bulk {i}")) for i in range(3)]
    db_session.add_all(media)
    await db_session.flush()
    return media


async def _default_tag_uuid(client, headers) -> str:
    tags = (await client.get("/watchlist/tags", headers=headers)).json()
    return next(t["uuid"] for t in tags if t["is_default"])


async def test_registered_user_has_default_tag(client, user_auth_headers):
    """Registration seeds the immutable default tag, so a fresh user already
    has exactly one tag and it's the default."""
    resp = await client.get("/watchlist/tags", headers=user_auth_headers)
    assert resp.status_code == 200
    tags = resp.json()
    assert len(tags) == 1
    assert tags[0]["is_default"] is True
    assert tags[0]["name"] == "Watchlist"
    assert tags[0]["entry_count"] == 0
    assert tags[0]["anime_count"] == 0


async def test_restricted_user_cannot_access_tags(client, restricted_user_auth_headers):
    resp = await client.get("/watchlist/tags", headers=restricted_user_auth_headers)
    assert resp.status_code == 403


async def test_create_and_list_tag(client, user_auth_headers):
    resp = await client.post(
        "/watchlist/tags", json={"name": "Films", "color": "#123ABC"}, headers=user_auth_headers
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["name"] == "Films"
    assert created["color"] == "#123abc"  # normalized
    assert created["is_default"] is False

    listing = (await client.get("/watchlist/tags", headers=user_auth_headers)).json()
    assert [t["name"] for t in listing] == ["Watchlist", "Films"]  # default first


async def test_create_duplicate_tag_name_conflicts(client, user_auth_headers):
    await client.post(
        "/watchlist/tags", json={"name": "Dup", "color": "#000000"}, headers=user_auth_headers
    )
    resp = await client.post(
        "/watchlist/tags", json={"name": "Dup", "color": "#ffffff"}, headers=user_auth_headers
    )
    assert resp.status_code == 409


async def test_invalid_color_rejected(client, user_auth_headers):
    resp = await client.post(
        "/watchlist/tags", json={"name": "Bad", "color": "red"}, headers=user_auth_headers
    )
    assert resp.status_code == 422


async def test_default_tag_cannot_be_renamed_or_deleted(client, user_auth_headers):
    default = (await client.get("/watchlist/tags", headers=user_auth_headers)).json()[0]
    uuid = default["uuid"]

    patch = await client.patch(
        f"/watchlist/tags/{uuid}", json={"name": "Nope"}, headers=user_auth_headers
    )
    assert patch.status_code == 403

    delete = await client.delete(f"/watchlist/tags/{uuid}", headers=user_auth_headers)
    assert delete.status_code == 403


async def test_update_and_delete_custom_tag(client, user_auth_headers):
    created = (await client.post(
        "/watchlist/tags", json={"name": "Temp", "color": "#000000"}, headers=user_auth_headers
    )).json()
    uuid = created["uuid"]

    patched = await client.patch(
        f"/watchlist/tags/{uuid}", json={"color": "#ABCDEF"}, headers=user_auth_headers
    )
    assert patched.status_code == 200
    assert patched.json()["color"] == "#abcdef"

    deleted = await client.delete(f"/watchlist/tags/{uuid}", headers=user_auth_headers)
    assert deleted.status_code == 200
    assert deleted.json() == {"affected": 0}

    remaining = (await client.get("/watchlist/tags", headers=user_auth_headers)).json()
    assert [t["name"] for t in remaining] == ["Watchlist"]


async def test_empty_endpoint_on_default_tag(client, user_auth_headers):
    """The default tag exposes empty (not delete); with no entries it removes 0."""
    default = (await client.get("/watchlist/tags", headers=user_auth_headers)).json()[0]
    resp = await client.post(
        f"/watchlist/tags/{default['uuid']}/empty", headers=user_auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"removed": 0}


# --- Entries ---

async def test_upsert_entry_and_media_tags(client, user_auth_headers, test_media):
    tag_uuid = await _default_tag_uuid(client, user_auth_headers)
    resp = await client.put(
        f"/watchlist/media/{test_media.uuid}",
        json={"tag_uuid": tag_uuid, "priority": 1, "note": "soon"},
        headers=user_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["priority"] == 1
    assert data["note"] == "soon"
    assert data["tag"]["uuid"] == tag_uuid
    assert data["media_uuid"] == str(test_media.uuid)

    tags = (await client.get("/watchlist/media-tags", headers=user_auth_headers)).json()
    assert len(tags["entries"]) == 1
    entry = tags["entries"][0]
    assert entry["media_uuid"] == str(test_media.uuid)
    assert entry["tag_uuid"] == tag_uuid
    assert entry["tag_name"] == "Watchlist"
    assert entry["tag_color"]  # colored bookmark source

    items = (await client.get("/watchlist/items", headers=user_auth_headers)).json()
    assert len(items) == 1
    assert items[0]["tag_name"] == "Watchlist"


async def test_upsert_defaults_priority(client, user_auth_headers, test_media):
    tag_uuid = await _default_tag_uuid(client, user_auth_headers)
    resp = await client.put(
        f"/watchlist/media/{test_media.uuid}",
        json={"tag_uuid": tag_uuid},
        headers=user_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["priority"] == 3


async def test_delete_entry(client, user_auth_headers, test_media):
    tag_uuid = await _default_tag_uuid(client, user_auth_headers)
    await client.put(
        f"/watchlist/media/{test_media.uuid}",
        json={"tag_uuid": tag_uuid}, headers=user_auth_headers,
    )
    deleted = await client.delete(f"/watchlist/media/{test_media.uuid}", headers=user_auth_headers)
    assert deleted.status_code == 204
    tags = (await client.get("/watchlist/media-tags", headers=user_auth_headers)).json()
    assert tags["entries"] == []


async def test_bulk_upsert_note_on_all(client, user_auth_headers, test_media_list):
    tag_uuid = await _default_tag_uuid(client, user_auth_headers)
    resp = await client.put(
        "/watchlist/bulk",
        json={
            "media_uuids": [str(m.uuid) for m in test_media_list],
            "tag_uuid": tag_uuid,
            "priority": 2,
            "note": "all",
        },
        headers=user_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert len(out) == 3
    assert all(o["note"] == "all" for o in out)


async def test_bulk_delete_entries(client, user_auth_headers, test_media_list):
    tag_uuid = await _default_tag_uuid(client, user_auth_headers)
    await client.put(
        "/watchlist/bulk",
        json={"media_uuids": [str(m.uuid) for m in test_media_list], "tag_uuid": tag_uuid},
        headers=user_auth_headers,
    )
    resp = await client.post(
        "/watchlist/bulk-delete",
        json={"media_uuids": [str(test_media_list[0].uuid), str(test_media_list[1].uuid)]},
        headers=user_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 2}


async def test_restricted_user_cannot_upsert_entry(client, restricted_user_auth_headers, test_media):
    resp = await client.put(
        f"/watchlist/media/{test_media.uuid}",
        json={"tag_uuid": "00000000-0000-0000-0000-000000000000"},
        headers=restricted_user_auth_headers,
    )
    assert resp.status_code == 403
