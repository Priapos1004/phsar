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

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker
from app.core.maintenance import get_scheduled_at, set_maintenance, set_scheduled_at
from app.daos.job_dao import JobDAO
from app.exceptions import PermanentPhsarError
from app.models.job import Job, JobKind

logger = logging.getLogger(__name__)

# Wall-clock fallback for the rare case that a notify() is lost to a race.
# Short enough that an empty queue picks up an orphaned signal within a minute.
_FALLBACK_POLL_SECONDS = 60.0

# Sweeps run inside the maintenance window — the worker brackets them with
# the in-memory flag flip so the HTTP middleware returns 503 to everything
# except the allowlist for the duration. user_scrape jobs are concurrent-safe
# with normal traffic and don't need the bracket.
_MAINTENANCE_KINDS: frozenset[JobKind] = frozenset(
    {JobKind.update_sweep, JobKind.seasonal_sweep}
)

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
        await asyncio.gather(self._task, return_exceptions=True)
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
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=_FALLBACK_POLL_SECONDS)
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
        async with async_session_maker() as claim_session:
            job = await self._dao.claim_next_queued(claim_session)
            if job is None:
                return False
            await claim_session.commit()
            job_id = job.id
            kind = job.kind

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
                    logger.exception("Job %s (%s) failed", job.uuid, kind.value)
                    await work_session.rollback()
                    failure = exc
        finally:
            if in_maintenance:
                set_maintenance(False)
                # Only clear the pre-warning if it points at the window we just
                # exited. A Coolify cron retry can fire mid-sweep (the
                # schedule-sweep endpoint is allowlisted) and set a *future*
                # `_scheduled_at` for the next window; clobbering that here
                # would lose the next sweep's banner countdown.
                scheduled = get_scheduled_at()
                if scheduled is None or scheduled <= datetime.now(timezone.utc):
                    set_scheduled_at(None)

        retryable = not isinstance(failure, PermanentPhsarError)
        async with async_session_maker() as fail_session:
            failing = await self._dao.get_by_id(fail_session, job_id)
            if failing is not None:
                await self._dao.mark_failed(
                    fail_session,
                    failing,
                    str(failure) or type(failure).__name__,
                    retryable=retryable,
                )
                await fail_session.commit()
        return True


# Module-level singleton for the app's lifespan to use. Tests instantiate
# their own JobWorker() so they can register isolated fake dispatchers.
job_worker = JobWorker()
