"""Admin router root — mounts the focused sub-routers under `/admin`.

This file owns the registration-token CRUD and the backups CRUD (list /
create / download / delete / restore / upload). Cron-authed scheduler
endpoints live in `admin_jobs.py` (mounted as a sub-router) and merge-
candidate review lives in `admin_merge.py`.

The split keeps each surface under ~150 lines so future agents don't
scroll past three unrelated admin concerns to find the fourth.
"""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_roles
from app.models.job import JobKind, JobStatus
from app.models.users import RoleType
from app.routers.admin_jobs import enqueue_backup_job
from app.routers.admin_jobs import router as admin_jobs_router
from app.routers.admin_merge import router as admin_merge_router
from app.routers.admin_split import router as admin_split_router
from app.schemas import admin_schema, auth_schema, backup_schema, job_schema
from app.services import (
    admin_service,
    admin_stats_service,
    auth_service,
    backup_service,
)

router = APIRouter(prefix="/admin", tags=["admin"])

require_admin = require_roles(RoleType.Admin)


@router.get("/registration-tokens", response_model=list[admin_schema.RegistrationTokenListItem])
async def list_registration_tokens(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    return await admin_service.list_registration_tokens(db)


@router.post("/registration-tokens", response_model=auth_schema.RegistrationTokenResponse)
async def create_registration_token(
    data: admin_schema.RegistrationTokenCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    new_token = await auth_service.create_registration_token(
        data.role, current_user, db, expires_in_days=data.expires_in_days.value,
    )
    return auth_schema.RegistrationTokenResponse(
        token=new_token.token,
        role=new_token.role,
        created_by=current_user.username,
        expires_on=new_token.expires_on,
    )


@router.delete("/registration-tokens/{uuid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registration_token(
    uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    await admin_service.delete_registration_token(db, uuid)


@router.get("/stats/overview", response_model=admin_schema.AdminOverviewStats)
async def get_stats_overview(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Aggregate stats for the admin Overview tab. Catalog totals,
    7-day job health by kind, and 7-day activity counters."""
    return await admin_stats_service.get_overview_stats(db)


@router.get("/curation/pending-counts", response_model=admin_schema.CurationPendingCounts)
async def get_curation_pending_counts(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Pending merge + split candidate counts for the admin bell's
    pinned reminder. The bell polls this each tick (admin-only, so a
    regular user's bell isn't paying for these queries) — separate
    endpoint from the list ones because the list calls eager-load
    anime + media + sidecars for the curation cards, way more than
    the bell needs."""
    return await admin_stats_service.get_curation_pending_counts(db)


@router.get("/jobs", response_model=job_schema.AdminJobsPage)
async def list_jobs(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
    status: JobStatus | None = Query(default=None),
    kind: JobKind | None = Query(default=None),
    user_id: int | None = Query(default=None, ge=1),
    created_after: datetime | None = Query(default=None),
    created_before: datetime | None = Query(default=None),
    parent_uuid: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Paginated all-jobs list for the admin Jobs Log tab. Newest-first
    by created_at. The frontend renders this directly — no client-side
    re-sort. `limit` capped at 500 so an admin expanding a full seasonal
    sweep (≈hundreds of children) can do it in one fetch without paging.

    Without `parent_uuid`, returns only root rows (parent_job_id IS NULL)
    so the main list doesn't drown in seasonal-sweep children. Set
    `parent_uuid` to expand a single seasonal_sweep row."""
    return await admin_service.list_jobs_paginated(
        db,
        status=status, kind=kind, user_id=user_id,
        created_after=created_after, created_before=created_before,
        parent_uuid=parent_uuid,
        limit=limit, offset=offset,
    )


# Router-level admin dep — only `restore` actually reads the caller's username,
# so everything else drops the per-endpoint Depends(require_admin).
backups_router = APIRouter(prefix="/backups", dependencies=[Depends(require_admin)])


@backups_router.get("", response_model=list[backup_schema.BackupMetadata])
async def list_backups():
    return await backup_service.list_backups()


@backups_router.post(
    "",
    response_model=admin_schema.JobEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_backup(
    data: backup_schema.BackupCreateRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Manual backup. Enqueues a `backup` job attributed to the admin;
    the dispatcher runs pg_dump asynchronously while the admin keeps
    working. The bell tracks progress + surfaces the final filename so
    the BackupsCard can refresh its dump list on completion."""
    label = data.label if data else None
    return await enqueue_backup_job(
        db,
        backup_schema.BackupSource.manual,
        label=label,
        requested_by_user_id=current_user.id,
    )


@backups_router.get("/{filename}")
async def download_backup(filename: str):
    path = backup_service.get_backup_path(filename)
    return FileResponse(
        path=path,
        media_type="application/octet-stream",
        filename=filename,
    )


@backups_router.delete("/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(filename: str):
    await backup_service.delete_backup(filename)


@backups_router.post("/{filename}/restore", response_model=backup_schema.BackupMetadata)
async def restore_backup(
    filename: str,
    data: backup_schema.BackupRestoreRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    # Release this request's pooled connection before the service disposes the
    # whole pool; otherwise get_db's cleanup tries to rollback on a closed conn.
    await db.close()
    return await backup_service.restore_backup(
        filename=filename, confirm=data.confirm,
        caller_username=current_user.username, caller_user_id=current_user.id,
    )


@backups_router.post("/upload", response_model=backup_schema.BackupMetadata)
async def upload_backup(file: UploadFile):
    return await backup_service.save_uploaded_backup(file)


router.include_router(backups_router)
router.include_router(admin_jobs_router)
router.include_router(admin_merge_router)
router.include_router(admin_split_router)
