import logging
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db, require_user_or_admin
from app.daos.job_dao import JobDAO
from app.exceptions import (
    DuplicateScrapeQueryError,
    InsufficientPermissionsError,
    JobNotFoundError,
    JobQueueLimitExceededError,
)
from app.models.job import Job, JobKind, JobStatus
from app.models.users import RoleType, Users
from app.schemas.job_schema import JobResponse, ScrapeJobRequest
from app.services.job_worker import job_worker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])
dao = JobDAO()


@router.post("/scrape", response_model=JobResponse)
async def enqueue_scrape(
    request: ScrapeJobRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(require_user_or_admin),
):
    active = await dao.count_active_for_user(db, current_user.id)
    if active >= settings.JOBS_PER_USER_LIMIT:
        raise JobQueueLimitExceededError(settings.JOBS_PER_USER_LIMIT)

    # Dedupe across all users: re-running an already-scraped query just
    # fails with AnimeNotFoundError because the BFS sees every mal_id in
    # the excluded set. Failed jobs aren't deduped — those may be transient.
    recent = await dao.find_recent_scrape_for_query(
        db, request.query, hours=settings.JOBS_DEDUPE_HOURS,
    )
    if recent is not None:
        age = datetime.now(timezone.utc) - recent.created_at
        raise DuplicateScrapeQueryError(
            request.query,
            recent.status,
            int(age.total_seconds() // 3600),
        )

    job = Job(
        kind=JobKind.user_scrape,
        status=JobStatus.queued,
        requested_by_user_id=current_user.id,
        payload={"query": request.query},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    job_worker.notify()
    logger.info("Enqueued user_scrape job %s for user %s", job.uuid, current_user.username)
    return job


@router.get("/mine", response_model=list[JobResponse])
async def list_my_jobs(
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    return await dao.list_for_user(db, current_user.id)


@router.get("/{job_uuid}", response_model=JobResponse)
async def get_job(
    job_uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    job = await dao.get_by_uuid(db, job_uuid)
    if job is None:
        raise JobNotFoundError(str(job_uuid))
    is_admin = current_user.role == RoleType.Admin
    if job.requested_by_user_id != current_user.id and not is_admin:
        raise InsufficientPermissionsError()
    return job
