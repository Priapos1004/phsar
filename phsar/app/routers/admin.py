from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Body, Depends, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_db,
    require_backup_cron_token,
    require_jobs_cron_token,
    require_roles,
)
from app.core.maintenance import set_scheduled_at
from app.exceptions import InvalidScheduleDelayError
from app.models.job import Job, JobKind, JobStatus
from app.models.users import RoleType
from app.schemas import admin_schema, auth_schema, backup_schema
from app.services import (
    admin_service,
    auth_service,
    backup_service,
    merge_candidate_service,
)
from app.services.job_worker import job_worker

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


@router.get(
    "/merge-candidates",
    response_model=list[admin_schema.MergeCandidateListItem],
)
async def list_merge_candidates(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    return await merge_candidate_service.list_pending(db)


@router.post(
    "/merge-candidates/{uuid}/merge",
    response_model=admin_schema.MergeResult,
)
async def merge_anime_candidate(
    uuid: UUID,
    data: admin_schema.MergeRequest = Body(default_factory=admin_schema.MergeRequest),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    surviving_uuid = await merge_candidate_service.merge(db, uuid, keep_uuid=data.keep_uuid)
    return admin_schema.MergeResult(surviving_anime_uuid=surviving_uuid)


@router.post(
    "/merge-candidates/{uuid}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def dismiss_anime_candidate(
    uuid: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    await merge_candidate_service.dismiss(db, uuid)


# Sits on the parent router so it doesn't inherit the JWT admin dep —
# same reason as /backups/auto below (cron-only auth, no user context).
@router.post(
    "/jobs/schedule-sweep",
    response_model=admin_schema.ScheduledSweepResponse,
    dependencies=[Depends(require_jobs_cron_token)],
)
async def schedule_sweep(
    delay_minutes: int = 20,
    db: AsyncSession = Depends(get_db),
):
    if delay_minutes < 0:
        raise InvalidScheduleDelayError(delay_minutes)

    not_before = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
    job = Job(
        kind=JobKind.update_sweep,
        status=JobStatus.queued,
        payload={},
        not_before_at=not_before,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    # Set the banner timestamp *after* the commit so a failed insert
    # doesn't leave a phantom countdown on the frontend.
    set_scheduled_at(not_before)
    # notify() is harmless: the worker re-checks not_before_at and sleeps
    # if the timestamp is still in the future. The 60s wakeup fallback
    # would catch it anyway.
    job_worker.notify()
    return admin_schema.ScheduledSweepResponse(
        job_uuid=job.uuid, scheduled_at=not_before,
    )


# Cron-authed endpoint — stays on the parent router so it doesn't inherit the
# JWT admin dep from the backups sub-router (router-level dependencies are
# additive; the only way to exclude the admin check is to not be under it).
@router.post(
    "/backups/auto",
    response_model=backup_schema.BackupMetadata,
    dependencies=[Depends(require_backup_cron_token)],
)
async def auto_backup():
    """Cron-triggered backup. Creates a dump tagged as `cron` and applies retention."""
    metadata = await backup_service.create_backup(source=backup_schema.BackupSource.cron)
    await backup_service.apply_retention()
    return metadata


# Router-level admin dep — only `restore` actually reads the caller's username,
# so everything else drops the per-endpoint Depends(require_admin).
backups_router = APIRouter(prefix="/backups", dependencies=[Depends(require_admin)])


@backups_router.get("", response_model=list[backup_schema.BackupMetadata])
async def list_backups():
    return await backup_service.list_backups()


@backups_router.post("", response_model=backup_schema.BackupMetadata)
async def create_backup(data: backup_schema.BackupCreateRequest | None = None):
    label = data.label if data else None
    return await backup_service.create_backup(
        source=backup_schema.BackupSource.manual, label=label,
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
        filename=filename, confirm=data.confirm, caller_username=current_user.username,
    )


@backups_router.post("/upload", response_model=backup_schema.BackupMetadata)
async def upload_backup(file: UploadFile):
    return await backup_service.save_uploaded_backup(file)


router.include_router(backups_router)
