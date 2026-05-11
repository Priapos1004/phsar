"""POST /admin/jobs/schedule-seasonal — cron-token-gated seasonal scheduler.

Mirrors test_admin_sweep.py exactly: the endpoint inserts a
seasonal_sweep Job row with a future not_before_at and bumps the
maintenance banner schedule. Tests pin auth, schema, and the
maintenance-allowlist for the cron retry case.
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

URL = "/admin/jobs/schedule-seasonal"
GOOD_HEADER = {"Authorization": "Bearer test-token"}


@pytest.fixture
async def cron_client(db_session):
    app = create_app()

    async def override_get_db():
        yield db_session

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
async def test_schedule_seasonal_requires_cron_token(cron_client):
    resp = await cron_client.post(URL)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_schedule_seasonal_rejects_wrong_token(cron_client):
    resp = await cron_client.post(URL, headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_schedule_seasonal_creates_job_and_sets_banner(cron_client, db_session):
    before = datetime.now(timezone.utc)
    resp = await cron_client.post(URL + "?delay_minutes=20", headers=GOOD_HEADER)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "job_uuid" in body
    assert "scheduled_at" in body

    scheduled_at = datetime.fromisoformat(body["scheduled_at"])
    delta = (scheduled_at - before).total_seconds()
    assert 19 * 60 <= delta <= 21 * 60

    sched = maintenance.get_scheduled_at()
    assert sched is not None

    result = await db_session.execute(
        select(Job).where(Job.uuid == body["job_uuid"])
    )
    job = result.scalars().first()
    assert job is not None
    assert job.kind is JobKind.seasonal_sweep
    assert job.status is JobStatus.queued
    assert job.not_before_at is not None


@pytest.mark.asyncio
async def test_schedule_seasonal_negative_delay_rejected(cron_client):
    resp = await cron_client.post(URL + "?delay_minutes=-1", headers=GOOD_HEADER)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_schedule_seasonal_excessive_delay_rejected(cron_client):
    resp = await cron_client.post(URL + "?delay_minutes=10000", headers=GOOD_HEADER)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_schedule_seasonal_allowlisted_during_maintenance(cron_client):
    """Cron retry while another sweep is mid-flight must not 503 the
    cron itself — otherwise the next seasonal window never enqueues."""
    maintenance.set_maintenance(True)
    try:
        resp = await cron_client.post(URL + "?delay_minutes=5", headers=GOOD_HEADER)
    finally:
        maintenance.set_maintenance(False)
    assert resp.status_code == 200
