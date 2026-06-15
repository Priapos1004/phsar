"""JobWorker integration tests.

The worker creates fresh sessions per job via async_session_maker, which
sidesteps the rolled-back db_session fixture. Tests below let the worker
write to the real DB and clean up explicitly via a tracked-job-ids fixture.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core import maintenance
from app.core.db import async_session_maker
from app.daos.job_dao import JobDAO
from app.models.job import Job, JobKind, JobStatus
from app.services import job_worker as job_worker_module
from app.services.job_worker import JobWorker

dao = JobDAO()


async def _enqueue(payload: dict | None = None, kind: JobKind = JobKind.user_scrape) -> int:
    """Insert a queued job and return its id. Real commit so the worker's
    fresh sessions can see it."""
    async with async_session_maker() as s:
        job = Job(kind=kind, status=JobStatus.queued, payload=payload or {})
        s.add(job)
        await s.flush()
        await s.commit()
        return job.id


async def _get(job_id: int) -> Job | None:
    async with async_session_maker() as s:
        return await dao.get_by_id(s, job_id)


@pytest.mark.asyncio
async def test_dispatch_one_runs_registered_handler(tracked_jobs):
    captured = []

    async def fake_dispatcher(session, job):
        captured.append(job.id)
        return {"ran": True}

    worker = JobWorker()
    worker.register_dispatcher(JobKind.user_scrape, fake_dispatcher)

    job_id = await _enqueue()
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True
    assert captured == [job_id]

    refreshed = await _get(job_id)
    assert refreshed.status is JobStatus.succeeded
    assert refreshed.result_summary == {"ran": True}
    assert refreshed.finished_at is not None


@pytest.mark.asyncio
async def test_dispatch_one_returns_false_when_queue_empty():
    worker = JobWorker()
    ran = await worker.dispatch_one()
    assert ran is False


@pytest.mark.asyncio
async def test_unregistered_kind_marks_job_failed(tracked_jobs):
    """A queued job for an unhandled kind doesn't crash the loop — it fails
    cleanly so the worker drains the queue and doesn't get stuck."""
    worker = JobWorker()
    job_id = await _enqueue()
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    refreshed = await _get(job_id)
    assert refreshed.status is JobStatus.failed
    assert "No dispatcher registered" in refreshed.error_message


@pytest.mark.asyncio
async def test_dispatcher_exception_marks_job_failed(tracked_jobs):
    """A handler that raises shouldn't poison the worker. The job records
    the exception text and the loop continues."""

    async def boom(session, job):
        raise RuntimeError("simulated failure")

    worker = JobWorker()
    worker.register_dispatcher(JobKind.user_scrape, boom)

    job_id = await _enqueue()
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    refreshed = await _get(job_id)
    assert refreshed.status is JobStatus.failed
    assert "simulated failure" in refreshed.error_message
    # Generic exceptions default to retryable so the bell still offers a
    # retry button — the failure could be a transient bug or DB hiccup.
    assert (refreshed.result_summary or {}).get("retryable") is True


@pytest.mark.asyncio
async def test_post_dispatch_failure_marks_job_failed(tracked_jobs):
    """Invariant: when mark_succeeded's flush raises (e.g. result_summary
    contains a type that JSON can't serialize), the work session is left
    in PendingRollback. The worker must still write a `failed` status
    record instead of letting the exception escape — otherwise a touch
    of `job.uuid` on the poisoned session re-raises and the row sits in
    `running` until reap_orphans fires at next startup."""

    class _NotSerializable:
        pass

    async def returns_bad_summary(session, job):
        return {"junk": _NotSerializable()}

    worker = JobWorker()
    worker.register_dispatcher(JobKind.user_scrape, returns_bad_summary)

    job_id = await _enqueue()
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    refreshed = await _get(job_id)
    assert refreshed.status is JobStatus.failed
    # Content check guards against a regression where some other error
    # masks the intended crash signature — the bell shouldn't render an
    # empty / wrong message.
    assert "not JSON serializable" in refreshed.error_message


@pytest.mark.asyncio
async def test_permanent_phsar_error_marks_job_not_retryable(tracked_jobs):
    """Errors that subclass PermanentPhsarError stamp retryable=False on
    the job so the bell hides its retry button — same input + same MAL =
    same failure, retrying is futile."""
    from app.exceptions import AnimeNotFoundError

    async def boom(session, job):
        raise AnimeNotFoundError("missing show")

    worker = JobWorker()
    worker.register_dispatcher(JobKind.user_scrape, boom)

    job_id = await _enqueue()
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    refreshed = await _get(job_id)
    assert refreshed.status is JobStatus.failed
    assert (refreshed.result_summary or {}).get("retryable") is False


@pytest.mark.asyncio
async def test_unregistered_kind_marks_job_not_retryable(tracked_jobs):
    """Missing dispatcher is a broken config, not a transient issue —
    same as PermanentPhsarError it shouldn't tempt the user with retry."""
    worker = JobWorker()  # no dispatchers registered

    job_id = await _enqueue()
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    refreshed = await _get(job_id)
    assert refreshed.status is JobStatus.failed
    assert (refreshed.result_summary or {}).get("retryable") is False


@pytest.mark.asyncio
async def test_sweep_kind_brackets_maintenance_flag(tracked_jobs):
    """Sweep dispatchers run inside the maintenance window — the worker
    flips the flag on before the dispatcher and off after, regardless of
    success/failure. Verifies the success path here."""
    captured_active: list[bool] = []

    async def fake_sweep(session, job):
        captured_active.append(maintenance.is_maintenance_active())
        return None

    worker = JobWorker()
    worker.register_dispatcher(JobKind.update_sweep, fake_sweep)

    # Pre-warning schedule — the worker should clear it once the job runs.
    maintenance.set_scheduled_at(datetime.now(timezone.utc))

    job_id = await _enqueue(kind=JobKind.update_sweep)
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    # Inside the dispatcher: flag was True.
    assert captured_active == [True]
    # After dispatch_one returns: both cleared.
    assert maintenance.is_maintenance_active() is False
    assert maintenance.get_scheduled_at() is None


@pytest.mark.asyncio
async def test_sweep_kind_clears_flag_on_dispatcher_failure(tracked_jobs):
    """A dispatcher crash must NOT leave the flag stuck — otherwise every
    endpoint sits behind a 503 until the next process restart."""

    async def boom(session, job):
        raise RuntimeError("sweep blew up")

    worker = JobWorker()
    worker.register_dispatcher(JobKind.update_sweep, boom)

    job_id = await _enqueue(kind=JobKind.update_sweep)
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    assert maintenance.is_maintenance_active() is False
    assert maintenance.get_scheduled_at() is None

    refreshed = await _get(job_id)
    assert refreshed.status is JobStatus.failed


@pytest.mark.asyncio
async def test_sweep_finally_preserves_future_scheduled_at(tracked_jobs):
    """A Coolify cron retry can hit /admin/jobs/schedule-sweep mid-sweep
    (allowlisted) and write a *future* `_scheduled_at` for the next
    window. The worker's finally must not clobber it — otherwise the
    next sweep fires with no banner pre-warning."""
    next_window = datetime.now(timezone.utc) + timedelta(minutes=20)

    async def fake_sweep(session, job):
        # Simulate the cron-retry race: a freshly-set future timestamp
        # appears while *this* sweep is still running.
        maintenance.set_scheduled_at(next_window)
        return None

    worker = JobWorker()
    worker.register_dispatcher(JobKind.update_sweep, fake_sweep)

    job_id = await _enqueue(kind=JobKind.update_sweep)
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    assert maintenance.is_maintenance_active() is False
    assert maintenance.get_scheduled_at() == next_window


@pytest.mark.asyncio
async def test_dispatch_one_skips_claim_when_maintenance_active(tracked_jobs):
    """Externally-active maintenance (restore) must idle the worker so it
    doesn't claim against a pool about to be disposed. The queued job
    survives untouched and runs on the next dispatch after the flag lifts."""
    captured: list[int] = []

    async def fake_dispatcher(session, job):
        captured.append(job.id)
        return None

    worker = JobWorker()
    worker.register_dispatcher(JobKind.user_scrape, fake_dispatcher)

    job_id = await _enqueue(kind=JobKind.user_scrape)
    tracked_jobs.append(job_id)

    maintenance.set_maintenance(True)
    try:
        ran = await worker.dispatch_one()
    finally:
        maintenance.set_maintenance(False)

    assert ran is False
    assert captured == []

    # Job stays queued for the next dispatch cycle after maintenance lifts.
    refreshed = await _get(job_id)
    assert refreshed.status is JobStatus.queued

    # Sanity: with the flag cleared, the same worker picks the job up.
    ran_after = await worker.dispatch_one()
    assert ran_after is True
    assert captured == [job_id]


@pytest.mark.asyncio
async def test_run_loop_picks_up_job_quickly_after_maintenance_lift(
    tracked_jobs, monkeypatch
):
    """`set_maintenance(False)` in `restore_backup`'s finally does NOT
    fire `notify()`. Without a tighter timeout during maintenance, the
    worker would sleep up to `_FALLBACK_POLL_SECONDS` (60s) past the
    lift before claiming a job that was enqueued during the window.

    Tighten the maintenance poll for the test so the assertion happens
    in well under a second: if a future refactor drops the
    maintenance-aware timeout selection in `_run`, this test falls back
    to the 60s wall and the surrounding `wait_for(timeout=2.0)` trips.
    """
    monkeypatch.setattr(job_worker_module, "_MAINTENANCE_POLL_SECONDS", 0.05)

    claimed = asyncio.Event()
    captured: list[int] = []

    async def fake_dispatcher(session, job):
        captured.append(job.id)
        claimed.set()
        return None

    worker = JobWorker()
    worker.register_dispatcher(JobKind.user_scrape, fake_dispatcher)

    job_id = await _enqueue(kind=JobKind.user_scrape)
    tracked_jobs.append(job_id)

    maintenance.set_maintenance(True)
    await worker.start()
    try:
        # Yield until the worker has entered its maintenance-poll wait —
        # otherwise lifting the gate races dispatch_one and the test
        # never exercises the short-poll wake-up that is the regression
        # subject.
        await asyncio.sleep(0.1)
        # No notify() — the short poll is what wakes the worker.
        maintenance.set_maintenance(False)
        await asyncio.wait_for(claimed.wait(), timeout=2.0)
    finally:
        await worker.stop()

    assert captured == [job_id]


@pytest.mark.asyncio
async def test_user_scrape_does_not_flip_maintenance_flag(tracked_jobs):
    """user_scrape jobs run alongside normal traffic — they must NOT trip
    the maintenance gate, otherwise every concurrent user gets 503'd."""
    captured_active: list[bool] = []

    async def fake_dispatcher(session, job):
        captured_active.append(maintenance.is_maintenance_active())
        return None

    worker = JobWorker()
    worker.register_dispatcher(JobKind.user_scrape, fake_dispatcher)

    job_id = await _enqueue(kind=JobKind.user_scrape)
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    assert captured_active == [False]
    assert maintenance.is_maintenance_active() is False


@pytest.mark.asyncio
async def test_failure_stamps_upstream_outage_category_for_5xx(tracked_jobs):
    """A dispatcher raising httpx.HTTPStatusError(5xx) must surface as
    `error_category=upstream_outage` on result_summary so the bell can
    render friendly copy instead of the raw 'Server error 504 ...' line."""
    import httpx

    async def fake_dispatcher(session, job):
        request = httpx.Request("GET", "https://api.jikan.moe/v4/anime")
        response = httpx.Response(504, request=request, content=b"gateway timeout")
        raise httpx.HTTPStatusError("504 Gateway Time-out", request=request, response=response)

    worker = JobWorker()
    worker.register_dispatcher(JobKind.user_scrape, fake_dispatcher)

    job_id = await _enqueue(kind=JobKind.user_scrape)
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    refreshed = await _get(job_id)
    assert refreshed.status is JobStatus.failed
    assert refreshed.result_summary is not None
    assert refreshed.result_summary.get("error_category") == "upstream_outage"
    assert refreshed.result_summary.get("retryable") is True


@pytest.mark.asyncio
async def test_failure_omits_category_for_non_upstream_errors(tracked_jobs):
    """A generic RuntimeError shouldn't categorize — bell falls through to
    the raw error_message instead of mislabeling it as an outage."""

    async def boom(session, job):
        raise RuntimeError("something broke in our code, not MAL")

    worker = JobWorker()
    worker.register_dispatcher(JobKind.user_scrape, boom)

    job_id = await _enqueue(kind=JobKind.user_scrape)
    tracked_jobs.append(job_id)

    ran = await worker.dispatch_one()
    assert ran is True

    refreshed = await _get(job_id)
    assert refreshed.status is JobStatus.failed
    assert refreshed.result_summary is not None
    assert "error_category" not in refreshed.result_summary


@pytest.mark.asyncio
async def test_notify_wakes_idle_worker(tracked_jobs):
    """A queued job inserted while the worker is asleep gets picked up
    promptly after notify(). Verifies the asyncio.Event signaling path."""
    captured = asyncio.Event()

    async def fake_dispatcher(session, job):
        captured.set()
        return None

    worker = JobWorker()
    worker.register_dispatcher(JobKind.user_scrape, fake_dispatcher)
    await worker.start()
    try:
        job_id = await _enqueue()
        tracked_jobs.append(job_id)

        worker.notify()
        # Generous timeout: this only needs to outlast scheduler jitter on a
        # loaded CI runner, not measure latency. 2.0s flaked under contention.
        await asyncio.wait_for(captured.wait(), timeout=5.0)
    finally:
        await worker.stop()
