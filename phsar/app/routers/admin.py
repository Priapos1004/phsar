from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_backup_cron_token, require_roles
from app.models.users import RoleType
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


@router.get("/backups", response_model=list[backup_schema.BackupMetadata])
async def list_backups(current_user=Depends(require_admin)):
    return await backup_service.list_backups()


@router.post("/backups", response_model=backup_schema.BackupMetadata)
async def create_backup(
    data: backup_schema.BackupCreateRequest | None = None,
    current_user=Depends(require_admin),
):
    label = data.label if data else None
    return await backup_service.create_backup(
        source=backup_schema.BackupSource.manual, label=label,
    )


@router.get("/backups/{filename}")
async def download_backup(filename: str, current_user=Depends(require_admin)):
    path = await backup_service.resolve_backup_path(filename)
    return FileResponse(
        path=path,
        media_type="application/octet-stream",
        filename=filename,
    )


@router.delete("/backups/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(filename: str, current_user=Depends(require_admin)):
    await backup_service.delete_backup(filename)


@router.post("/backups/{filename}/restore", response_model=backup_schema.BackupMetadata)
async def restore_backup(
    filename: str,
    data: backup_schema.BackupRestoreRequest,
    current_user=Depends(require_admin),
):
    return await backup_service.restore_backup(
        filename=filename, confirm=data.confirm, caller_username=current_user.username,
    )


@router.post("/backups/upload", response_model=backup_schema.BackupMetadata)
async def upload_backup(file: UploadFile, current_user=Depends(require_admin)):
    return await backup_service.save_uploaded_backup(file)


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
