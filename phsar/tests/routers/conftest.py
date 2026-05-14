import pytest
from fastapi import Header
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.dependencies import get_db, require_jobs_cron_token
from app.exceptions import InvalidCronTokenError
from app.main import create_app
from app.models.users import RoleType

CRON_TOKEN = "test-token"
CRON_AUTH_HEADER = {"Authorization": f"Bearer {CRON_TOKEN}"}

# db_engine + db_session fixtures live in tests/conftest.py so non-router
# tests can reuse them.


@pytest.fixture
async def client(db_session):
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()

@pytest.fixture
async def get_admin_token(client):
    async def _get_token(username: str = None, password: str = None):
        username = username or settings.ADMIN_USERNAME
        password = password or settings.ADMIN_PASSWORD

        login_response = await client.post(
            "/auth/login",
            data={
                "username": username,
                "password": password
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        assert login_response.status_code == 200, f"Login failed: {login_response.text}"
        return login_response.json()["access_token"]
    return _get_token

@pytest.fixture
async def create_user_with_role(client, get_admin_token):
    """
    Generic fixture to create & login a user with any RoleType.
    Usage:
    token = await create_user_with_role(username="myuser", password="mypass12", role=RoleType.User)
    """
    async def _create_user(username: str, password: str, role: RoleType):
        admin_token = await get_admin_token()

        # Issue registration token via admin endpoint
        issue_resp = await client.post(
            "/admin/registration-tokens",
            json={"role": role.value},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert issue_resp.status_code == 200, f"Issue token failed: {issue_resp.text}"
        reg_token = issue_resp.json()["token"]

        # Register user
        reg_resp = await client.post("/auth/register", json={
            "username": username,
            "password": password,
            "registration_token": reg_token
        })
        assert reg_resp.status_code == 200, f"Registration failed: {reg_resp.text}"

        # Login user
        login_resp = await client.post(
            "/auth/login",
            data={"username": username, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
        return login_resp.json()["access_token"]
    return _create_user

@pytest.fixture
async def admin_auth_headers(get_admin_token):
    token = await get_admin_token()
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
async def user_auth_headers(create_user_with_role):
    token = await create_user_with_role(username="normaluser", password="userpassword", role=RoleType.User)
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
async def restricted_user_auth_headers(create_user_with_role):
    token = await create_user_with_role(username="restricteduser", password="restrictedpass", role=RoleType.RestrictedUser)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def cron_client(db_session):
    """Test client whose require_jobs_cron_token dep accepts a literal
    token. Mirrors the production gate (raises InvalidCronTokenError on
    missing/wrong bearer) without depending on settings.JOBS_CRON_TOKEN
    being set in the test env. Shared across every cron-authed endpoint
    (sweep schedulers + /backups/auto) — they all consume the same token
    post-v0.14.0 consolidation."""
    app = create_app()

    async def override_get_db():
        yield db_session

    def fake_require(authorization: str | None = Header(default=None)) -> None:
        if authorization != f"Bearer {CRON_TOKEN}":
            raise InvalidCronTokenError()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_jobs_cron_token] = fake_require

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()
