from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_roles
from app.models.users import RoleType
from app.schemas import admin_schema, auth_schema
from app.services import admin_service, auth_service

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
