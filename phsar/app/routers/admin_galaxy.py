"""Admin galaxy endpoints: rebuild the map, and give a sector or region a hand name.
Mounted under `/admin` by the parent router; router-level admin dep."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db, require_roles
from app.models.users import RoleType
from app.schemas import admin_schema, galaxy_schema
from app.services import galaxy_service

require_admin = require_roles(RoleType.Admin)

router = APIRouter(prefix="/galaxy", dependencies=[Depends(require_admin)])


@router.post(
    "/rebuild",
    response_model=admin_schema.JobEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rebuild_galaxy(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Refit the map now; the bell tracks the job."""
    return await galaxy_service.enqueue_rebuild(db, requested_by_user_id=current_user.id)


@router.patch("/groups/{group_uuid}", response_model=galaxy_schema.GalaxyGroupOut)
async def rename_galaxy_group(
    group_uuid: UUID,
    data: galaxy_schema.GalaxyGroupRename,
    db: AsyncSession = Depends(get_db),
):
    return await galaxy_service.rename_group(db, group_uuid, data.name)
