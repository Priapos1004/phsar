import uuid

import pytest

from app.models.users import RoleType

TOKENS_URL = "/admin/registration-tokens"


@pytest.mark.asyncio
async def test_create_token(client, admin_auth_headers):
    resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value},
        headers=admin_auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["role"] == RoleType.User.value
    assert data["expires_on"] is not None


@pytest.mark.asyncio
async def test_create_token_with_expiry(client, admin_auth_headers):
    resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value, "expires_in_days": 30},
        headers=admin_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == RoleType.User.value


@pytest.mark.asyncio
async def test_create_token_invalid_expiry(client, admin_auth_headers):
    resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value, "expires_in_days": 15},
        headers=admin_auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_token_requires_admin(client, user_auth_headers):
    resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value},
        headers=user_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_token_restricted_user_forbidden(client, restricted_user_auth_headers):
    resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value},
        headers=restricted_user_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_tokens(client, admin_auth_headers):
    # Create two tokens
    await client.post(TOKENS_URL, json={"role": RoleType.User.value}, headers=admin_auth_headers)
    await client.post(TOKENS_URL, json={"role": RoleType.RestrictedUser.value}, headers=admin_auth_headers)

    resp = await client.get(TOKENS_URL, headers=admin_auth_headers)
    assert resp.status_code == 200
    tokens = resp.json()
    assert len(tokens) >= 2

    # Verify structure of first token
    t = tokens[0]
    assert "uuid" in t
    assert "token" in t
    assert "status" in t
    assert t["status"] in ("active", "used", "expired")


@pytest.mark.asyncio
async def test_list_tokens_requires_admin(client, user_auth_headers):
    resp = await client.get(TOKENS_URL, headers=user_auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_tokens_shows_used_status(client, admin_auth_headers):
    # Create a token and use it to register a user
    create_resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value},
        headers=admin_auth_headers,
    )
    reg_token = create_resp.json()["token"]

    await client.post("/auth/register", json={
        "username": "usedtokenuser",
        "password": "testpassword",
        "registration_token": reg_token,
    })

    # List and find the used token
    list_resp = await client.get(TOKENS_URL, headers=admin_auth_headers)
    tokens = list_resp.json()
    used = [t for t in tokens if t["token"] == reg_token]
    assert len(used) == 1
    assert used[0]["status"] == "used"
    assert used[0]["used_by"] == "usedtokenuser"


@pytest.mark.asyncio
async def test_delete_unused_token(client, admin_auth_headers):
    # Create a token
    create_resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value},
        headers=admin_auth_headers,
    )
    token_str = create_resp.json()["token"]

    # Find its uuid
    list_resp = await client.get(TOKENS_URL, headers=admin_auth_headers)
    token_entry = next(t for t in list_resp.json() if t["token"] == token_str)

    # Delete it
    del_resp = await client.delete(f"{TOKENS_URL}/{token_entry['uuid']}", headers=admin_auth_headers)
    assert del_resp.status_code == 204

    # Verify it's gone
    list_resp2 = await client.get(TOKENS_URL, headers=admin_auth_headers)
    uuids = [t["uuid"] for t in list_resp2.json()]
    assert token_entry["uuid"] not in uuids


@pytest.mark.asyncio
async def test_delete_used_token_fails(client, admin_auth_headers):
    # Create and use a token
    create_resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value},
        headers=admin_auth_headers,
    )
    reg_token = create_resp.json()["token"]

    await client.post("/auth/register", json={
        "username": "useddeluser",
        "password": "testpassword",
        "registration_token": reg_token,
    })

    # Find its uuid
    list_resp = await client.get(TOKENS_URL, headers=admin_auth_headers)
    token_entry = next(t for t in list_resp.json() if t["token"] == reg_token)

    # Attempt delete — should fail
    del_resp = await client.delete(f"{TOKENS_URL}/{token_entry['uuid']}", headers=admin_auth_headers)
    assert del_resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_invalid_uuid_format(client, admin_auth_headers):
    resp = await client.delete(f"{TOKENS_URL}/not-a-uuid", headers=admin_auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_nonexistent_token(client, admin_auth_headers):
    resp = await client.delete(f"{TOKENS_URL}/{uuid.uuid4()}", headers=admin_auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_token_requires_admin(client, user_auth_headers):
    resp = await client.delete(f"{TOKENS_URL}/{uuid.uuid4()}", headers=user_auth_headers)
    assert resp.status_code == 403
