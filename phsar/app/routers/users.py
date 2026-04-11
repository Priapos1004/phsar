import json
from datetime import date
from enum import Enum

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_user_or_admin
from app.schemas.auth_schema import DeleteAccountRequest
from app.schemas.user_settings_schema import UserSettingsOut, UserSettingsUpdate
from app.services import auth_service, export_service, user_settings_service

router = APIRouter(prefix="/users", tags=["users"])


class ExportFormat(str, Enum):
    json = "json"
    csv = "csv"


# --- Settings ---


@router.get("/settings", response_model=UserSettingsOut)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await user_settings_service.get_settings(db, current_user.id)


@router.put("/settings", response_model=UserSettingsOut)
async def update_settings(
    data: UserSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    return await user_settings_service.update_settings(db, current_user.id, data)


# --- Account Deletion ---


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    data: DeleteAccountRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    await auth_service.delete_account(current_user, data.password, db)


# --- Data Export ---


@router.get("/export")
async def export_user_data(
    format: ExportFormat = Query(default=ExportFormat.json),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    """Download all user data as flat media-level rows (JSON or CSV)."""
    settings = await user_settings_service.get_settings(db, current_user.id)
    rows = await export_service.fetch_export_data(
        db, current_user.id, settings.name_language
    )
    today = date.today().strftime("%Y_%m_%d")
    filename = f"phsar_export_{current_user.username}_{today}"

    if format == ExportFormat.json:
        content = json.dumps(rows, ensure_ascii=False, indent=2)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )

    return Response(
        content=export_service.serialize_csv(rows),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )
