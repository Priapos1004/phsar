import functools

import pytest
from fastapi import FastAPI, Header
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.dependencies import get_db, require_jobs_cron_token
from app.core.security import create_user_access_token, get_password_hash
from app.exceptions import InvalidCronTokenError
from app.main import create_app
from app.models.users import RoleType
from app.services.auth_service import create_user

CRON_TOKEN = "test-token"
CRON_AUTH_HEADER = {"Authorization": f"Bearer {CRON_TOKEN}"}

# db_engine + db_session fixtures live in tests/conftest.py so non-router
# tests can reuse them.


@pytest.fixture(scope="session")
def asgi_app() -> FastAPI:
    """One app for the run: it holds no per-test state but the dependency overrides, which
    each client sets and clears around its test."""
    return create_app()


@pytest.fixture
async def client(asgi_app, db_session):
    async def override_get_db():
        yield db_session

    asgi_app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=asgi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    asgi_app.dependency_overrides.clear()

@pytest.fixture
async def get_admin_token(client):
    async def _get_token(username: str | None = None, password: str | None = None):
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
    Create & log in a user through the real HTTP flow — registration token, register,
    login. For the tests of that flow; any other test takes `make_auth_user`.
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


@functools.cache
def _password_hash(password: str) -> str:
    """One real hash per password per run, so a fixture user's password still verifies wherever
    the app checks one, without each test paying for argon2."""
    return get_password_hash(password)


def _bearer(username: str, role: RoleType) -> dict[str, str]:
    """Auth headers carrying the token `/auth/login` would hand back, signed here."""
    return {"Authorization": f"Bearer {create_user_access_token(username, role)}"}


@pytest.fixture
def make_auth_user(db_session):
    """A user created as registration creates one (`auth_service.create_user`), and its auth
    headers."""
    async def _make(username: str, password: str, role: RoleType) -> dict[str, str]:
        await create_user(db_session, username, _password_hash(password), role)
        return _bearer(username, role)
    return _make

@pytest.fixture
def admin_auth_headers():
    """The admin the suite's database is seeded with."""
    return _bearer(settings.ADMIN_USERNAME, RoleType.Admin)

@pytest.fixture
async def user_auth_headers(make_auth_user):
    return await make_auth_user("normaluser", "userpassword", RoleType.User)

@pytest.fixture
async def restricted_user_auth_headers(make_auth_user):
    return await make_auth_user("restricteduser", "restrictedpass", RoleType.RestrictedUser)


@pytest.fixture
async def cron_client(asgi_app, client):
    """Test client whose require_jobs_cron_token dep accepts a literal
    token. Mirrors the production gate (raises InvalidCronTokenError on
    missing/wrong bearer) without depending on settings.JOBS_CRON_TOKEN
    being set in the test env. Shared across every cron-authed endpoint
    (sweep schedulers + /backups/auto) — they all consume the same token
    post-v0.14.0 consolidation."""
    def fake_require(authorization: str | None = Header(default=None)) -> None:
        if authorization != f"Bearer {CRON_TOKEN}":
            raise InvalidCronTokenError()

    # `client` clears it with its own override on teardown.
    asgi_app.dependency_overrides[require_jobs_cron_token] = fake_require
    return client
