"""Single-worker FIFO job runner.

One asyncio task drains the jobs table sequentially. MAL has a global
~3 req/s rate limit so concurrent scrape jobs would just fragment bandwidth
and fight over deduped inserts; serializing keeps the model simple. The
worker uses an asyncio.Event for sub-second pickup when an enqueue happens,
with a wall-clock fallback timeout in case a notify() is missed (e.g., a
queue insert that misses the in-process event because of a race).

Dispatcher functions per JobKind are registered via register_dispatcher().
Subsequent commits add user_scrape, update_sweep, seasonal_sweep dispatchers.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker
from app.core.maintenance import (
    get_scheduled_at,
    is_maintenance_active,
    set_maintenance,
    set_scheduled_at,
)
from app.daos.job_dao import JobDAO
from app.exceptions import (
    BackupDiskSpaceError,
    BackupIntegrityError,
    PermanentPhsarError,
    TransientUpstreamError,
)
from app.models.job import Job, JobKind

logger = logging.getLogger(__name__)

# Wall-clock fallback for the rare case that a notify() is lost to a race.
# Short enough that an empty queue picks up an orphaned signal within a minute.
_FALLBACK_POLL_SECONDS = 60.0

# Tighter poll while maintenance is active. dispatch_one short-circuits to
# False during maintenance and clearing the flag (in restore's finally) does
# not fire notify() — without this, a job queued during the window can sit
# up to _FALLBACK_POLL_SECONDS past the lift.
_MAINTENANCE_POLL_SECONDS = 2.0

# Sweeps run inside the maintenance window — the worker brackets them with
# the in-memory flag flip so the HTTP middleware returns 503 to everything
# except the allowlist for the duration. user_scrape jobs are concurrent-safe
# with normal traffic and don't need the bracket.
_MAINTENANCE_KINDS: frozenset[JobKind] = frozenset(
    {JobKind.update_sweep, JobKind.seasonal_sweep}
)

# Error categories stamped on result_summary["error_category"] for the
# frontend bell to render friendly copy. Only categories with a clear
# end-user message live here; everything else falls through to the raw
# exception string (which is already useful for AnimeNotFoundError,
# MalIdAlreadyExistsError, etc.).
ERROR_CATEGORY_UPSTREAM_OUTAGE = "upstream_outage"
ERROR_CATEGORY_BACKUP_DISK_FULL = "backup_disk_full"
ERROR_CATEGORY_BACKUP_CORRUPT = "backup_corrupt"


def classify_error(exc: BaseException) -> str | None:
    """Translate a dispatcher exception into a coarse error category for
    the bell. Returns None when the raw exception message is already
    user-friendly (custom domain errors carry their own copy)."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500:
        return ERROR_CATEGORY_UPSTREAM_OUTAGE
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return ERROR_CATEGORY_UPSTREAM_OUTAGE
    if isinstance(exc, TransientUpstreamError):
        return ERROR_CATEGORY_UPSTREAM_OUTAGE
    # Backup failure modes get their own categories so the bell can
    # render an actionable hint ("free disk space and retry" / "pg_dump
    # produced a corrupt archive — check Postgres logs") instead of the
    # raw stderr tail. retryable stays at the default (True) because
    # both modes are fixable: an admin can free space, or a transient
    # connection drop during pg_dump can resolve on its own.
    if isinstance(exc, BackupDiskSpaceError):
        return ERROR_CATEGORY_BACKUP_DISK_FULL
    if isinstance(exc, BackupIntegrityError):
        return ERROR_CATEGORY_BACKUP_CORRUPT
    return None


JobDispatcher = Callable[[AsyncSession, Job], Awaitable[dict | None]]


class JobWorker:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._wakeup = asyncio.Event()
        self._stop = asyncio.Event()
        self._dispatchers: dict[JobKind, JobDispatcher] = {}
        self._dao = JobDAO()

    def register_dispatcher(self, kind: JobKind, dispatcher: JobDispatcher) -> None:
        self._dispatchers[kind] = dispatcher

    def notify(self) -> None:
        """Signal that a new job is queued. Safe to call from any coroutine."""
        self._wakeup.set()

    async def start(self) -> None:
        if self._task is not None:
            return
        # Fail fast if a future refactor reverses the lifespan order — without
        # dispatchers, every queued job would just be marked failed.
        assert self._dispatchers, "register_dispatcher must be called before start()"
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="job_worker")
        logger.info("JobWorker started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        self._wakeup.set()  # break out of the wait
        # Bound the wait so a job mid-BFS (httpx 120s read timeout + tenacity
        # backoff = several minutes) can't stall lifespan shutdown. On timeout
        # the task is cancelled — its finally clauses (maintenance-clear) still
        # run, but the in-flight `running` row is left for reap_orphans to flip
        # on the next startup.
        try:
            await asyncio.wait_for(self._task, timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning(
                "JobWorker stop() exceeded 10s; cancelling in-flight job"
            )
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("JobWorker task raised during shutdown")
        self._task = None
        logger.info("JobWorker stopped")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                ran = await self.dispatch_one()
            except Exception:
                logger.exception("JobWorker dispatch loop crashed; sleeping before retry")
                await asyncio.sleep(5)
                continue
            if ran:
                continue
            # Race: a notify() between dispatch_one returning False and clear()
            # would be lost. The wait_for timeout below catches it within a minute.
            self._wakeup.clear()
            timeout = (
                _MAINTENANCE_POLL_SECONDS if is_maintenance_active()
                else _FALLBACK_POLL_SECONDS
            )
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass

    async def dispatch_one(self) -> bool:
        """Claim and run one job. Returns True if a job was processed.

        Two sessions: a short one to claim+commit the row state transition
        (so other workers / future processes see it as `running` immediately)
        and a separate work session that may stay open for minutes. Holding a
        single transaction across the whole scrape would block every other
        write on the jobs table and accumulate identity-map state.
        """
        # Restore disposes the pool + terminates sessions mid-flight; claiming
        # any job in that window either dies on the killed session or (for
        # backup) writes a silently-incomplete dump. Sweep-induced maintenance
        # is a no-op here — `_run` is already inside dispatch_one running the
        # sweep, so it can't re-enter.
        if is_maintenance_active():
            return False
        async with async_session_maker() as claim_session:
            job = await self._dao.claim_next_queued(claim_session)
            if job is None:
                return False
            await claim_session.commit()
            job_id = job.id
            kind = job.kind
            # Pre-capture so the failure logger / fail_session block never
            # touches an ORM `job` attribute after a poisoned flush. A
            # mark_succeeded flush crash (e.g. the v0.14.5 datetime-in-
            # JSONB bug) leaves the work session in PendingRollback, and a
            # subsequent `job.uuid` read would trip the expired-attr
            # refresh and re-raise — losing the job to a stuck-`running`
            # row until next reap_orphans.
            job_uuid_str = str(job.uuid)

        # Run the dispatcher in its own session and capture any failure for
        # a separate fail-record session. Two sequential sessions instead of
        # nested ones — concurrent sessions on a small asyncpg pool deadlock.
        failure: Exception | None = None
        in_maintenance = kind in _MAINTENANCE_KINDS
        # Flip the flag *before* the work session opens so the middleware
        # sees the same window as the running job. Try/finally guarantees
        # it clears even on dispatcher crash — a stuck flag would lock every
        # endpoint behind a 503 until restart.
        if in_maintenance:
            set_maintenance(True)
        try:
            # Outer catch-all so any failure between claim and the
            # fail_session block — including bugs in our own session
            # plumbing — routes through the explicit `failed` write
            # below. Without it, an exception leaking out of dispatch_one
            # would only get cleaned up by reap_orphans on next startup.
            try:
                async with async_session_maker() as work_session:
                    job = await self._dao.get_by_id(work_session, job_id)
                    if job is None:
                        logger.warning("Job %s vanished after claim", job_id)
                        return True
                    dispatcher = self._dispatchers.get(kind)
                    if dispatcher is None:
                        # Missing dispatcher is a broken config — retry produces the
                        # same outcome until a redeploy, so don't tempt the bell.
                        await self._dao.mark_failed(
                            work_session,
                            job,
                            f"No dispatcher registered for kind {kind.value!r}",
                            retryable=False,
                        )
                        await work_session.commit()
                        return True
                    try:
                        result_summary = await dispatcher(work_session, job)
                        await self._dao.mark_succeeded(work_session, job, result_summary)
                        await work_session.commit()
                        return True
                    except Exception as exc:
                        failure = exc
                        logger.exception("Job %s (%s) failed", job_uuid_str, kind.value)
                        # Rollback can itself raise (PendingRollback after
                        # a flush error sometimes deadlocks the cleanup);
                        # swallow so the fail_session block still runs.
                        try:
                            await work_session.rollback()
                        except Exception:
                            logger.exception(
                                "Rollback of work session for job %s failed",
                                job_uuid_str,
                            )
            except Exception as exc:
                if failure is None:
                    failure = exc
                logger.exception(
                    "Unexpected worker error processing job %s (%s)",
                    job_uuid_str, kind.value,
                )
        finally:
            if in_maintenance:
                # Wrap the flag-clear in try/except so a hypothetical raise can
                # never escape the finally and skip the mark_failed block below
                # — that would leak a `running` row until next reap_orphans.
                try:
                    set_maintenance(False)
                    # Only clear the pre-warning if it points at the window we
                    # just exited. A Coolify cron retry can fire mid-sweep (the
                    # schedule-sweep endpoint is allowlisted) and set a *future*
                    # `_scheduled_at` for the next window; clobbering that here
                    # would lose the next sweep's banner countdown.
                    scheduled = get_scheduled_at()
                    if scheduled is None or scheduled <= datetime.now(timezone.utc):
                        set_scheduled_at(None)
                except Exception:
                    logger.exception("Failed to clear maintenance flag in worker finally")

        if failure is None:
            return True

        retryable = not isinstance(failure, PermanentPhsarError)
        error_category = classify_error(failure)
        try:
            async with async_session_maker() as fail_session:
                failing = await self._dao.get_by_id(fail_session, job_id)
                if failing is not None:
                    await self._dao.mark_failed(
                        fail_session,
                        failing,
                        str(failure) or type(failure).__name__,
                        retryable=retryable,
                        error_category=error_category,
                    )
                    await fail_session.commit()
        except Exception:
            logger.exception(
                "Failed to write failure record for job %s; row will be "
                "reaped by reap_orphans on next startup",
                job_uuid_str,
            )
        return True


# Module-level singleton for the app's lifespan to use. Tests instantiate
# their own JobWorker() so they can register isolated fake dispatchers.
job_worker = JobWorker()
