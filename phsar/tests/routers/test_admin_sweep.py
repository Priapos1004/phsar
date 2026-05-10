"""POST /admin/jobs/schedule-sweep — cron-token-gated sweep scheduler.

The endpoint inserts an `update_sweep` job with a future `not_before_at`
and bumps the maintenance banner schedule. Tests pin the auth surface,
the schema, and the maintenance-allowlist.

Auth is faked via app.dependency_overrides because the require_jobs_cron_token
dependency is bound once at module load from settings.JOBS_CRON_TOKEN; the
test env leaves that empty so the dep would otherwise always raise.
"""

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core import maintenance
from app.core.dependencies import get_db, require_jobs_cron_token
from app.exceptions import InvalidCronTokenError
from app.main import create_app
from app.models.job import Job, JobKind, JobStatus

URL = "/admin/jobs/schedule-sweep"
GOOD_HEADER = {"Authorization": "Bearer test-token"}


@pytest.fixture
async def cron_client(db_session):
    """Test client whose require_jobs_cron_token dep accepts a literal
    token. Mirrors the production gate (raises InvalidCronTokenError on
    missing/wrong bearer) without depending on settings.JOBS_CRON_TOKEN."""
    app = create_app()

    async def override_get_db():
        yield db_session

    def fake_cron_token(authorization: str | None = None):
        if authorization != "Bearer test-token":
            raise InvalidCronTokenError()

    # FastAPI inspects the actual function signature for header binding.
    # Easier: register the dep wrapper that pulls the header itself.
    from fastapi import Header

    def fake_require(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer test-token":
            raise InvalidCronTokenError()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_jobs_cron_token] = fake_require

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_schedule_sweep_requires_cron_token(cron_client):
    resp = await cron_client.post(URL)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_schedule_sweep_rejects_wrong_token(cron_client):
    """A wrong bearer must 401 — schedule-sweep is wired to machine-only
    access deliberately, no JWT fallback."""
    resp = await cron_client.post(URL, headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_schedule_sweep_creates_job_and_sets_banner(cron_client, db_session):
    before = datetime.now(timezone.utc)
    resp = await cron_client.post(URL + "?delay_minutes=20", headers=GOOD_HEADER)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "job_uuid" in body
    assert "scheduled_at" in body

    scheduled_at = datetime.fromisoformat(body["scheduled_at"])
    delta = (scheduled_at - before).total_seconds()
    assert 19 * 60 <= delta <= 21 * 60

    # Banner pre-warning timestamp set after the commit.
    sched = maintenance.get_scheduled_at()
    assert sched is not None

    result = await db_session.execute(
        select(Job).where(Job.uuid == body["job_uuid"])
    )
    job = result.scalars().first()
    assert job is not None
    assert job.kind is JobKind.update_sweep
    assert job.status is JobStatus.queued
    assert job.not_before_at is not None


@pytest.mark.asyncio
async def test_schedule_sweep_negative_delay_rejected(cron_client):
    resp = await cron_client.post(URL + "?delay_minutes=-1", headers=GOOD_HEADER)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_schedule_sweep_allowlisted_during_maintenance(cron_client):
    """A cron retry while a sweep is already running must not 503 the
    cron itself — otherwise the next night's sweep never gets scheduled."""
    maintenance.set_maintenance(True)
    try:
        resp = await cron_client.post(URL + "?delay_minutes=5", headers=GOOD_HEADER)
    finally:
        maintenance.set_maintenance(False)
    assert resp.status_code == 200
