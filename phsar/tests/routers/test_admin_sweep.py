"""POST /admin/jobs/schedule-sweep — cron-token-gated sweep scheduler.

The endpoint inserts an `update_sweep` job with a future `not_before_at`
and bumps the maintenance banner schedule. Tests pin the auth surface,
the schema, and the maintenance-allowlist.

`cron_client` + `CRON_AUTH_HEADER` come from tests/routers/conftest.py;
the require_jobs_cron_token dep is bound once at module load from
settings.JOBS_CRON_TOKEN (empty in test env), so the fixture overrides
it with a literal-token check.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core import maintenance
from app.models.job import Job, JobKind, JobStatus
from tests.routers.conftest import CRON_AUTH_HEADER as GOOD_HEADER

URL = "/admin/jobs/schedule-sweep"


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
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_schedule_sweep_excessive_delay_rejected(cron_client):
    """Defense-in-depth: an enormous delay would otherwise blow up
    timedelta() with OverflowError -> 500. 1440 minutes = 24h ceiling."""
    resp = await cron_client.post(URL + "?delay_minutes=10000", headers=GOOD_HEADER)
    assert resp.status_code == 422


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
