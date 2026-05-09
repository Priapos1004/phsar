"""DAO-level tests for the jobs table.

Tests use the rolled-back db_session fixture, so each test starts from a
clean slate and nothing leaks across runs (apart from the autoincrement gap
that all rolled-back tests in this codebase produce).
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.daos.job_dao import JobDAO
from app.models.job import Job, JobKind, JobStatus
from app.models.users import RoleType, Users

dao = JobDAO()


async def _create_user(db_session, username: str = "jobtest_user") -> Users:
    user = Users(username=username, hashed_password="x", role=RoleType.User)
    db_session.add(user)
    await db_session.flush()
    return user


def _job(
    kind: JobKind = JobKind.user_scrape,
    status: JobStatus = JobStatus.queued,
    user_id: int | None = None,
    not_before_at: datetime | None = None,
    payload: dict | None = None,
) -> Job:
    return Job(
        kind=kind,
        status=status,
        requested_by_user_id=user_id,
        payload=payload or {},
        not_before_at=not_before_at,
    )


@pytest.mark.asyncio
async def test_claim_next_queued_picks_oldest(db_session):
    """FIFO: oldest queued job wins."""
    first = _job()
    second = _job()
    db_session.add_all([first, second])
    await db_session.flush()

    claimed = await dao.claim_next_queued(db_session)
    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status is JobStatus.running
    assert claimed.started_at is not None


@pytest.mark.asyncio
async def test_claim_next_queued_skips_running(db_session):
    """Already-running jobs aren't re-claimed."""
    db_session.add(_job(status=JobStatus.running))
    await db_session.flush()
    assert await dao.claim_next_queued(db_session) is None


@pytest.mark.asyncio
async def test_claim_next_queued_honors_not_before_at(db_session):
    """A queued job with not_before_at in the future is invisible to the
    claimer; the announce-then-run pattern depends on this."""
    future = datetime.now(timezone.utc) + timedelta(minutes=20)
    db_session.add(_job(not_before_at=future))
    await db_session.flush()
    assert await dao.claim_next_queued(db_session) is None


@pytest.mark.asyncio
async def test_claim_next_queued_picks_when_not_before_at_passed(db_session):
    """Once not_before_at is in the past, the job becomes claimable."""
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    job = _job(not_before_at=past)
    db_session.add(job)
    await db_session.flush()

    claimed = await dao.claim_next_queued(db_session)
    assert claimed is not None
    assert claimed.id == job.id


@pytest.mark.asyncio
async def test_count_active_for_user_counts_queued_and_running(db_session):
    """The per-user cap counts queued + running, not finished."""
    user = await _create_user(db_session)
    db_session.add_all([
        _job(status=JobStatus.queued, user_id=user.id),
        _job(status=JobStatus.running, user_id=user.id),
        _job(status=JobStatus.succeeded, user_id=user.id),  # not counted
        _job(status=JobStatus.failed, user_id=user.id),     # not counted
    ])
    await db_session.flush()

    assert await dao.count_active_for_user(db_session, user.id) == 2


@pytest.mark.asyncio
async def test_reap_orphans_marks_running_as_failed(db_session):
    """Startup reaper transitions every running job to failed with a
    breadcrumb message — the user retries from the bell."""
    db_session.add_all([
        _job(status=JobStatus.running),
        _job(status=JobStatus.running),
        _job(status=JobStatus.queued),     # untouched
        _job(status=JobStatus.succeeded),  # untouched
    ])
    await db_session.flush()

    reaped = await dao.reap_orphans(db_session)
    assert reaped == 2

    queued = await dao.claim_next_queued(db_session)
    assert queued is not None
    assert queued.status is JobStatus.running


@pytest.mark.asyncio
async def test_mark_succeeded_records_summary(db_session):
    job = _job()
    db_session.add(job)
    await db_session.flush()
    await dao.claim_next_queued(db_session)  # transitions to running

    await dao.mark_succeeded(db_session, job, {"anime_id": 42, "media_count": 7})

    assert job.status is JobStatus.succeeded
    assert job.finished_at is not None
    assert job.result_summary == {"anime_id": 42, "media_count": 7}


@pytest.mark.asyncio
async def test_mark_failed_truncates_long_error(db_session):
    """Defensive cap so a multi-MB stack trace doesn't blow up the row."""
    job = _job()
    db_session.add(job)
    await db_session.flush()
    await dao.claim_next_queued(db_session)

    huge = "x" * 5000
    await dao.mark_failed(db_session, job, huge)

    assert job.status is JobStatus.failed
    assert len(job.error_message) == 2000
