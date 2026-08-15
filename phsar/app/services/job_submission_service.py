"""User-facing job submission: enqueueing a scrape, and owner-scoped reads.

Sits between `routers/jobs.py` and `JobDAO` because enqueueing is not a
fetch-and-return. The admin side of the same table lives in `admin_service`.
"""

import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.job_versions import make_job
from app.daos.job_dao import JobDAO
from app.exceptions import (
    DailyJobLimitExceededError,
    DuplicateScrapeQueryError,
    InsufficientPermissionsError,
    JobNotFoundError,
    JobQueueLimitExceededError,
)
from app.models.job import Job, JobKind, JobStatus
from app.models.users import RoleType, Users
from app.schemas.job_schema import ScrapeJobRequest
from app.services.job_worker import job_worker

logger = logging.getLogger(__name__)

job_dao = JobDAO()

# A bare 5–6 digit query is a direct MAL id, not a title. MAL's fuzzy `q=`
# search fails to surface some shows by ANY title string (e.g. "Zenshu",
# id 58502 — its search index returns only unrelated "…Zenshuu" anthologies),
# and no anime is titled a pure 5–6 digit number, so such a query is
# unambiguously an id. 5–6 digits covers every current + near-future MAL id
# (they're ~60k now); shorter/older ids are reliably findable by title search.
# The leading digit must be non-zero: it keeps a leading-zero string ("00001")
# from collapsing to an old low id we mean to exclude, and rules out the all-zero
# "00000" → mal_id=0 that would otherwise slip past the schema's gt=0 guard.
_MAL_ID_QUERY = re.compile(r"[1-9]\d{4,5}")


async def enqueue_user_scrape(
    db: AsyncSession, current_user: Users, request: ScrapeJobRequest,
) -> Job:
    """Commits, because the job row must be durable before `notify()`
    points a worker at it."""
    active = await job_dao.count_active_for_user(db, current_user.id)
    if active >= settings.JOBS_PER_USER_LIMIT:
        raise JobQueueLimitExceededError(settings.JOBS_PER_USER_LIMIT)

    # The daily cap is an anti-abuse ceiling for regular/restricted users; admins are
    # trusted operators (catalog seeding/fixing), so it doesn't apply to them. The
    # concurrent cap above + dedup below still bound an admin's load.
    if current_user.role != RoleType.Admin:
        daily = await job_dao.count_user_scrapes_in_window(db, current_user.id)
        if daily >= settings.JOBS_DAILY_LIMIT:
            raise DailyJobLimitExceededError(settings.JOBS_DAILY_LIMIT)

    # Dedupe across all users: re-running an already-scraped query just
    # fails with AnimeNotFoundError because the BFS sees every mal_id in
    # the excluded set. Failed jobs aren't deduped — those may be transient.
    recent = await job_dao.find_recent_scrape_for_query(
        db, request.query, hours=settings.JOBS_DEDUPE_HOURS,
    )
    if recent is not None:
        age = datetime.now(timezone.utc) - recent.created_at
        raise DuplicateScrapeQueryError(
            request.query,
            recent.status,
            int(age.total_seconds() // 3600),
        )

    payload: dict = {"query": request.query}
    # An explicit client mal_id wins; otherwise see _MAL_ID_QUERY. Either way
    # the seed path is the same machinery the seasonal sweep uses.
    seed_mal_id = request.mal_id
    stripped_query = request.query.strip()
    if seed_mal_id is None and _MAL_ID_QUERY.fullmatch(stripped_query):
        seed_mal_id = int(stripped_query)
    if seed_mal_id is not None:
        payload["mal_id"] = seed_mal_id
    job = make_job(
        JobKind.user_scrape,
        status=JobStatus.queued,
        requested_by_user_id=current_user.id,
        payload=payload,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    job_worker.notify()
    logger.info("Enqueued user_scrape job %s for user %s", job.uuid, current_user.username)
    return job


async def get_job_for_user(db: AsyncSession, job_uuid: UUID, current_user: Users) -> Job:
    """Fetch one job the caller is entitled to see. 404 before the ownership
    check is safe: an unknown uuid and someone else's uuid are the same answer
    either way, so the order leaks nothing."""
    job = await job_dao.get_by_uuid(db, job_uuid)
    if job is None:
        raise JobNotFoundError(str(job_uuid))
    if job.requested_by_user_id != current_user.id and current_user.role != RoleType.Admin:
        raise InsufficientPermissionsError()
    return job
