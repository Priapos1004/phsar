"""Public maintenance status endpoint.

The frontend's MaintenanceBanner polls this every 60s. It is intentionally
authless — the banner needs to be reachable from /login and /register too,
and during the actual maintenance window when JWTs may also be rejected.
The endpoint is allowlisted in the maintenance HTTP middleware so it keeps
returning truthful info while the rest of the API is gated behind 503.
"""

from fastapi import APIRouter

from app.core.maintenance import get_scheduled_at, is_maintenance_active
from app.schemas.maintenance_schema import MaintenanceStatus

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.get("/status", response_model=MaintenanceStatus)
async def maintenance_status() -> MaintenanceStatus:
    return MaintenanceStatus(
        active=is_maintenance_active(),
        scheduled_at=get_scheduled_at(),
    )
