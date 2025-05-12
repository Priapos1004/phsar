import pytest

VALID_FILTER_PAYLOAD = {
    "query": "spy",
    "genre_name": ["Action", "Comedy"],
    "anime_season": ["Winter 2022"],
    "media_type": ["TV"]
}

@pytest.mark.asyncio
async def test_create_and_verify_token_as_admin(client, admin_auth_headers):
    # Create token
    create_resp = await client.post(
        "/filters/create-token",
        json=VALID_FILTER_PAYLOAD,
        headers=admin_auth_headers
    )
    assert create_resp.status_code == 200, f"Admin create: Expected 200, got {create_resp.status_code}"

    token_data = create_resp.json()
    assert "token" in token_data
    token = token_data["token"]
    assert isinstance(token, str)

    # Verify token
    verify_resp = await client.post(
        "/filters/verify-token",
        json={"token": token},
        headers=admin_auth_headers
    )
    assert verify_resp.status_code == 200, f"Admin verify: Expected 200, got {verify_resp.status_code}"
    data = verify_resp.json()
    assert data["query"] == "spy"
    assert "Action" in data["genre_name"]

@pytest.mark.asyncio
async def test_token_endpoints_as_user(client, user_auth_headers):
    create_resp = await client.post(
        "/filters/create-token",
        json=VALID_FILTER_PAYLOAD,
        headers=user_auth_headers
    )
    assert create_resp.status_code == 200, f"User create: Expected 200, got {create_resp.status_code}"
    token = create_resp.json()["token"]

    verify_resp = await client.post(
        "/filters/verify-token",
        json={"token": token},
        headers=user_auth_headers
    )
    assert verify_resp.status_code == 200, f"User verify: Expected 200, got {verify_resp.status_code}"

@pytest.mark.asyncio
async def test_token_endpoints_as_restricted_user(client, restricted_user_auth_headers):
    create_resp = await client.post(
        "/filters/create-token",
        json=VALID_FILTER_PAYLOAD,
        headers=restricted_user_auth_headers
    )
    assert create_resp.status_code == 200, f"Restricted create: Expected 200, got {create_resp.status_code}"
    token = create_resp.json()["token"]

    verify_resp = await client.post(
        "/filters/verify-token",
        json={"token": token},
        headers=restricted_user_auth_headers
    )
    assert verify_resp.status_code == 200, f"Restricted verify: Expected 200, got {verify_resp.status_code}"

@pytest.mark.asyncio
async def test_token_endpoints_without_token(client):
    # Missing auth for create
    create_resp = await client.post("/filters/create-token", json=VALID_FILTER_PAYLOAD)
    assert create_resp.status_code == 401, f"Create without auth: Expected 401, got {create_resp.status_code}"

    # Invalid token
    fake_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid.payload"
    verify_resp = await client.post("/filters/verify-token", json={"token": fake_token})
    assert verify_resp.status_code == 401, f"Verify invalid token: Expected 401, got {verify_resp.status_code}"
