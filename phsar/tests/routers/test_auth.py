import pytest

from app.models.users import RoleType

# Constants for test users
TEST_USERNAME = "testuser1"
TEST_PASSWORD = "testpassword1"
TEST_INVALID_TOKEN = "thisisnotavalidtoken"

# Helper for logging in users (DRY)
async def login_user(client, username, password):
    return await client.post(
        "/auth/login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )

@pytest.mark.asyncio
async def test_register_and_login_flow(client, create_user_with_role):
    # Use generic role-based fixture
    await create_user_with_role(username=TEST_USERNAME, password=TEST_PASSWORD, role=RoleType.User)

    # Login as the new user
    login_resp = await login_user(client, TEST_USERNAME, TEST_PASSWORD)
    assert login_resp.status_code == 200
    print("Login token:", login_resp.json())

@pytest.mark.asyncio
async def test_register_with_invalid_token(client):
    reg_resp = await client.post("/auth/register", json={
        "username": "invaliduser",
        "password": "invalidpassword",
        "registration_token": TEST_INVALID_TOKEN
    })
    assert reg_resp.status_code == 400
    print("Invalid token register response:", reg_resp.json())

@pytest.mark.asyncio
async def test_register_with_used_token(client, create_user_with_role, get_admin_token):
    admin_token = await get_admin_token()

    # Issue a registration token manually
    issue_resp = await client.post(
        "/auth/issue-token",
        json={"role": RoleType.User.value},
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    reg_token = issue_resp.json()["token"]

    # Register first time
    reg_resp_1 = await client.post("/auth/register", json={
        "username": "firstuse",
        "password": "firstpass",
        "registration_token": reg_token
    })
    assert reg_resp_1.status_code == 200

    # Attempt second registration with same token
    reg_resp_2 = await client.post("/auth/register", json={
        "username": "seconduse",
        "password": "secondpass",
        "registration_token": reg_token
    })
    assert reg_resp_2.status_code == 400
    print("Re-used token register response:", reg_resp_2.json())

@pytest.mark.asyncio
async def test_login_with_wrong_password(client, create_user_with_role):
    # Create a normal user
    await create_user_with_role(username="wrongpassuser", password="correctpass", role=RoleType.User)

    # Attempt login with wrong password
    login_resp = await login_user(client, "wrongpassuser", "wrongpass")
    assert login_resp.status_code == 401
    print("Wrong password login response:", login_resp.json())

@pytest.mark.asyncio
async def test_issue_token_requires_admin(client, create_user_with_role):
    # Create a normal user
    token = await create_user_with_role(username="nonadmin", password="nonadminpass", role=RoleType.User)

    # Try to issue a token as non-admin user
    issue_resp_non_admin = await client.post(
        "/auth/issue-token",
        json={"role": RoleType.User.value},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert issue_resp_non_admin.status_code == 403
    print("Non-admin trying to issue token response:", issue_resp_non_admin.json())
