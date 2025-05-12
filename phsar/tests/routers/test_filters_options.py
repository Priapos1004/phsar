import pytest


@pytest.mark.asyncio
async def test_filters_as_admin(client, admin_auth_headers):
    # Save as admin — should succeed
    response = await client.get("/filters/options", headers=admin_auth_headers)
    assert response.status_code == 200, f"Admin: Expected 200 OK, got {response.status_code}"

@pytest.mark.asyncio
async def test_filters_as_user(client, user_auth_headers):
    # Save as admin — should succeed
    response = await client.get("/filters/options", headers=user_auth_headers)
    assert response.status_code == 200, f"User: Expected 200 OK, got {response.status_code}"

@pytest.mark.asyncio
async def test_filters_as_restricted_user(client, restricted_user_auth_headers):
    # Save as admin — should succeed
    response = await client.get("/filters/options", headers=restricted_user_auth_headers)
    assert response.status_code == 200, f"Restricted user: Expected 200 OK, got {response.status_code}"

@pytest.mark.asyncio
async def test_filters_without_token(client):
    # No auth header — should fail (Unauthorized)
    response = await client.get("/filters/options")
    assert response.status_code == 401, f"Expected 401 Unauthorized, got {response.status_code}"
