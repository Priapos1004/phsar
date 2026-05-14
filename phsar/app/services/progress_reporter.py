"""Progress writer for long-running jobs.

Each update opens its own short-lived session so the frontend's bell can
see mid-flight progress without waiting for the dispatcher's main work tx
to commit. Updates throttle to MIN_INTERVAL_SECONDS so a tight BFS or save
loop doesn't open hundreds of sessions per second; stage-change updates
pass force=True to bypass the throttle.

Lives at the service layer (not inside scrape_dispatcher) so jikan_scraper
and save_service can import it without depending on the dispatcher module.
"""

import logging
import time

from app.core.db import async_session_maker
from app.daos.job_dao import JobDAO

logger = logging.getLogger(__name__)
job_dao = JobDAO()

_DEFAULT_MIN_INTERVAL_SECONDS = 0.5


class ProgressReporter:
    def __init__(self, job_id: int, min_interval_s: float = _DEFAULT_MIN_INTERVAL_SECONDS):
        self._job_id = job_id
        self._min_interval = min_interval_s
        self._last_at: float = 0.0

    async def update(
        self,
        stage: str | None = None,
        items_done: int | None = None,
        items_total: int | None = None,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        if not force and now - self._last_at < self._min_interval:
            return
        self._last_at = now
        async with async_session_maker() as session:
            job = await job_dao.get_by_id(session, self._job_id)
            if job is None:
                logger.debug("Progress update for missing job %s — ignored", self._job_id)
                return
            await job_dao.mark_progress(
                session, job, stage=stage, items_done=items_done, items_total=items_total,
            )
            await session.commit()
