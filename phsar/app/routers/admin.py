"""Admin router root — mounts the focused sub-routers under `/admin`.

This file owns the registration-token CRUD and the backups CRUD (list /
create / download / delete / restore / upload). Cron-authed scheduler
endpoints live in `admin_jobs.py` (mounted as a sub-router) and merge-
candidate review lives in `admin_merge.py`.

The split keeps each surface under ~150 lines so future agents don't
scroll past three unrelated admin concerns to find the fourth.
"""

from uuid import UUID

from fastapi import APIRouter, Body, Depends, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_roles
from app.models.users import RoleType
from app.routers.admin_jobs import enqueue_backup_job
from app.routers.admin_jobs import router as admin_jobs_router
from app.routers.admin_merge import router as admin_merge_router
from app.routers.admin_split import router as admin_split_router
from app.schemas import admin_schema, auth_schema, backup_schema
from app.services import admin_service, auth_service, backup_service

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
