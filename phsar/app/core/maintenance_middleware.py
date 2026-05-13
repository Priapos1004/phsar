"""ASGI middleware that 503s every non-allowlisted request during a
maintenance window.

Pure ASGI (not `@app.middleware("http")` / BaseHTTPMiddleware) so the
short-circuit response goes through CORSMiddleware's wrapped `send`
cleanly. Registration order in `main.create_app` puts CORS *outside*
this gate so cross-origin 503s still carry Access-Control-Allow-Origin —
without that, the browser rejects the response with a TypeError and the
frontend's catch falls into the generic "unexpected error" path instead
of the maintenance-banner branch.

The allowlist (`_ALLOWED_PATHS` below) covers Coolify's liveness probe,
the public maintenance-status endpoint, and the cron-scheduler routes —
those last must stay reachable during a window or a cron retry could
fail to schedule the next maintenance.
"""

from fastapi.responses import JSONResponse

from app.core.maintenance import is_maintenance_active


class MaintenanceGateMiddleware:
    _ALLOWED_PATHS = frozenset(
        {
            "/",
            "/health",
            "/maintenance/status",
            "/admin/jobs/schedule-sweep",
            "/admin/jobs/schedule-seasonal",
            "/admin/jobs/schedule-nightly",
        }
    )

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] == "http"
            and is_maintenance_active()
            and scope["path"] not in self._ALLOWED_PATHS
        ):
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": "Maintenance in progress. Please try again in a moment.",
                    "maintenance": True,
                },
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
