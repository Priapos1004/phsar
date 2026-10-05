"""POST /admin/jobs/schedule-upcoming — cron-token-gated next-season sweep.

Sibling of test_admin_seasonal.py; the endpoint reuses the seasonal dispatcher
against the following season so next-quarter shows surface early. schedule-nightly
fires it on its own days, but the standalone endpoint stays for ad-hoc triggers
and is the one that had no coverage.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app.models.job import Job, JobKind
from tests.routers.conftest import CRON_AUTH_HEADER as GOOD_HEADER

URL = "/admin/jobs/schedule-upcoming"


async def test_schedule_upcoming_requires_cron_token(cron_client):
    resp = await cron_client.post(URL)
    assert resp.status_code == 401


async def test_schedule_upcoming_rejects_wrong_token(cron_client):
    resp = await cron_client.post(URL, headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


async def test_schedule_upcoming_enqueues_an_upcoming_sweep(
    cron_client, db_session,
):
    before = datetime.now(timezone.utc)
    resp = await cron_client.post(f"{URL}?delay_minutes=20", headers=GOOD_HEADER)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    job = (await db_session.execute(
        select(Job).where(Job.uuid == body["job_uuid"])
    )).scalars().first()
    assert job is not None

    # The kind is the whole point: seasonal and upcoming share a dispatcher,
    # so a wrong kind here scrapes the current season twice and never the next.
    assert job.kind == JobKind.upcoming_sweep

    delta = (datetime.fromisoformat(body["scheduled_at"]) - before).total_seconds()
    assert 19 * 60 <= delta <= 21 * 60


async def test_schedule_upcoming_rejects_out_of_range_delay(cron_client):
    for bad in (-1, 1441):
        resp = await cron_client.post(
            f"{URL}?delay_minutes={bad}", headers=GOOD_HEADER,
        )
        assert resp.status_code == 422, f"delay_minutes={bad} should be rejected"
