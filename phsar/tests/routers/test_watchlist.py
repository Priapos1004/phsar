"""Watchlist router — tag endpoints (v0.15.0).

Entry endpoints (upsert / bulk / items / media-ids) are exercised in Block 3;
this file covers the tag surface + the restricted-user gate.
"""


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
