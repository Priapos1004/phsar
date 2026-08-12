from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_user_or_admin
from app.daos.job_dao import JobDAO
from app.models.users import Users
from app.schemas.job_schema import JobResponse, ScrapeJobRequest
from app.services import job_submission_service

router = APIRouter(prefix="/jobs", tags=["jobs"])
dao = JobDAO()


@router.post("/scrape", response_model=JobResponse)
async def enqueue_scrape(
    request: ScrapeJobRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Users = Depends(require_user_or_admin),
):
    return await job_submission_service.enqueue_user_scrape(db, current_user, request)


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
    return await job_submission_service.get_job_for_user(db, job_uuid, current_user)
