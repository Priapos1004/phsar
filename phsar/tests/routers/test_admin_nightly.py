"""POST /admin/jobs/schedule-nightly — combined daily cron entry point.

The endpoint enqueues three things from one call:
  - a `backup` job (no `not_before_at`, runs immediately)
  - an `update_sweep` job with `not_before_at = now + delay_minutes`
  - on Sundays UTC only, a `seasonal_sweep` job with the same delay

Tests pin the auth surface, the schema, the Sunday/weekday branch, and
the maintenance-allowlist that keeps a cron retry mid-window from 503ing.
The clock is monkey-patched on the router module so the Sunday branch is
reachable without waiting for an actual Sunday.

Auth uses the shared JOBS_CRON_TOKEN — the same bearer the two individual
sweep schedulers AND /backups/auto consume after the v0.14.0 token
consolidation.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core import maintenance
from app.models.job import Job, JobKind, JobStatus
from app.routers import admin as admin_router
from tests.routers.conftest import CRON_AUTH_HEADER as GOOD_HEADER

URL = "/admin/jobs/schedule-nightly"

# Pinned weekday-fixed timestamps so the test doesn't drift with the calendar.
# Both are exact midnight UTC so any delay_minutes math stays clean.
SUNDAY_FIXED = datetime(2026, 5, 17, 0, 0, 0, tzinfo=timezone.utc)  # weekday() == 6
MONDAY_FIXED = datetime(2026, 5, 18, 0, 0, 0, tzinfo=timezone.utc)  # weekday() == 0


@pytest.fixture
def freeze_admin_clock(monkeypatch):
    """Returns a setter that pins the wall clock the admin router sees.

    The endpoint reads `datetime.now(timezone.utc)` to pick the Sunday
    branch and to derive `not_before_at`. Monkey-patching the module-
    level `datetime` is the smallest seam — wrapping the call in an
    injectable helper just for tests would add production complexity
    for no operational benefit."""

    def _set(frozen: datetime):
        class _Pinned:
            @classmethod
            def now(cls, tz=None):
                return frozen.astimezone(tz) if tz is not None else frozen

        monkeypatch.setattr(admin_router, "datetime", _Pinned)

    return _set


@pytest.mark.asyncio
async def test_schedule_nightly_requires_cron_token(cron_client):
    resp = await cron_client.post(URL)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_schedule_nightly_rejects_wrong_token(cron_client):
    resp = await cron_client.post(URL, headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_schedule_nightly_weekday_enqueues_backup_and_sweep_only(
    cron_client, db_session, freeze_admin_clock,
):
    """Monday → backup + update_sweep only; seasonal_sweep_uuid is null.

    Backup is enqueued without `not_before_at` so the worker drains it
    first; update_sweep gets the delay so the banner has time to warm up
    before maintenance actually opens."""
    freeze_admin_clock(MONDAY_FIXED)

    resp = await cron_client.post(URL + "?delay_minutes=20", headers=GOOD_HEADER)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "backup_uuid" in body
    assert "update_sweep_uuid" in body
    assert body["seasonal_sweep_uuid"] is None

    scheduled_at = datetime.fromisoformat(body["scheduled_at"])
    assert (scheduled_at - MONDAY_FIXED).total_seconds() == pytest.approx(20 * 60)

    backup = (await db_session.execute(
        select(Job).where(Job.uuid == body["backup_uuid"])
    )).scalars().first()
    assert backup is not None
    assert backup.kind is JobKind.backup
    assert backup.status is JobStatus.queued
    assert backup.not_before_at is None  # runs immediately
    assert backup.payload == {"source": "cron"}
    assert backup.requested_by_user_id is None

    sweep = (await db_session.execute(
        select(Job).where(Job.uuid == body["update_sweep_uuid"])
    )).scalars().first()
    assert sweep is not None
    assert sweep.kind is JobKind.update_sweep
    assert sweep.status is JobStatus.queued
    assert sweep.not_before_at is not None
    assert sweep.requested_by_user_id is None

    # The null seasonal_sweep_uuid in the response body is itself the
    # contract that the endpoint did not enqueue one. A "no rows of this
    # kind exist anywhere" DB check would be misleading — pg sequences
    # don't roll back and prior test runs may have left rows behind.

    # Banner pointer set so the frontend countdown shows.
    assert maintenance.get_scheduled_at() is not None


@pytest.mark.asyncio
async def test_schedule_nightly_sunday_also_enqueues_seasonal(
    cron_client, db_session, freeze_admin_clock,
):
    """Sunday UTC → all three jobs enqueued; the seasonal piggybacks on
    the same maintenance window as update_sweep so the weekly catalog
    pickup doesn't open its own banner."""
    freeze_admin_clock(SUNDAY_FIXED)

    resp = await cron_client.post(URL + "?delay_minutes=20", headers=GOOD_HEADER)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["seasonal_sweep_uuid"] is not None

    seasonal = (await db_session.execute(
        select(Job).where(Job.uuid == body["seasonal_sweep_uuid"])
    )).scalars().first()
    assert seasonal is not None
    assert seasonal.kind is JobKind.seasonal_sweep
    assert seasonal.status is JobStatus.queued
    assert seasonal.not_before_at is not None
    assert seasonal.requested_by_user_id is None

    # Both sweeps share the same not_before_at so the banner countdown
    # only needs one timestamp.
    sweep = (await db_session.execute(
        select(Job).where(Job.uuid == body["update_sweep_uuid"])
    )).scalars().first()
    assert seasonal.not_before_at == sweep.not_before_at


@pytest.mark.asyncio
async def test_schedule_nightly_zero_delay_runs_sweep_immediately(
    cron_client, db_session, freeze_admin_clock,
):
    """delay_minutes=0 is valid (lower bound is ge=0). The sweep's
    not_before_at equals `now` so the worker picks it up on the next
    iteration after backup completes."""
    freeze_admin_clock(MONDAY_FIXED)

    resp = await cron_client.post(URL + "?delay_minutes=0", headers=GOOD_HEADER)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    sweep = (await db_session.execute(
        select(Job).where(Job.uuid == body["update_sweep_uuid"])
    )).scalars().first()
    assert sweep.not_before_at == MONDAY_FIXED


@pytest.mark.asyncio
async def test_schedule_nightly_negative_delay_rejected(cron_client):
    resp = await cron_client.post(URL + "?delay_minutes=-1", headers=GOOD_HEADER)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_schedule_nightly_excessive_delay_rejected(cron_client):
    """1440 minutes = 24h ceiling, same as the individual sweep
    schedulers — a misconfigured cron passing an enormous int would
    blow up timedelta() with OverflowError without the cap."""
    resp = await cron_client.post(URL + "?delay_minutes=10000", headers=GOOD_HEADER)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_schedule_nightly_allowlisted_during_maintenance(
    cron_client, freeze_admin_clock,
):
    """A cron retry that lands while the previous night's sweep is still
    running must still authenticate — the maintenance middleware lets
    the schedule endpoints through so the next night gets queued instead
    of silently dropped."""
    freeze_admin_clock(MONDAY_FIXED)
    maintenance.set_maintenance(True)
    try:
        resp = await cron_client.post(URL + "?delay_minutes=5", headers=GOOD_HEADER)
    finally:
        maintenance.set_maintenance(False)
    assert resp.status_code == 200
