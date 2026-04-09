import csv
import io
import json
from enum import Enum

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_user_or_admin
from app.schemas.user_settings_schema import UserSettingsOut, UserSettingsUpdate
from app.services import export_service, user_settings_service

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


# --- Data Export ---


@router.get("/export")
async def export_user_data(
    format: ExportFormat = Query(default=ExportFormat.json),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_user_or_admin),
):
    """Download all user data (ratings + watchlist) as JSON or CSV."""
    data = await export_service.fetch_export_data(db, current_user.id)
    filename = f"phsar_export_{current_user.username}"

    if format == ExportFormat.json:
        content = json.dumps(data, ensure_ascii=False, indent=2)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}.json"},
        )

    # CSV: ratings section then watchlist section
    output = io.StringIO()

    if data["ratings"]:
        writer = csv.DictWriter(output, fieldnames=data["ratings"][0].keys())
        writer.writeheader()
        writer.writerows(data["ratings"])

    if data["watchlist"]:
        if data["ratings"]:
            output.write("\n")
        watchlist_rows = [
            {**w, "tags": ";".join(w["tags"])} for w in data["watchlist"]
        ]
        writer = csv.DictWriter(output, fieldnames=watchlist_rows[0].keys())
        writer.writeheader()
        writer.writerows(watchlist_rows)

    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}.csv"},
    )
