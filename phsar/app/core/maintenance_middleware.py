"""ASGI middleware that 503s every non-allowlisted request during a
maintenance window.

Pure ASGI (not `@app.middleware("http")` / BaseHTTPMiddleware) so the
short-circuit response goes through CORSMiddleware's wrapped `send`
cleanly. Registration order in `main.create_app` puts CORS *outside*
this gate so cross-origin 503s still carry Access-Control-Allow-Origin —
without that, the browser rejects the response with a TypeError and the
frontend's catch falls into the generic "unexpected error" path instead
of the maintenance-banner branch.

Allowlist:
  /, /health: keep Coolify's liveness probe alive so the container
    doesn't restart mid-operation.
  /maintenance/status: the banner needs truthful state during the window —
    without it the user sees /login?maintenance=1 forever.
  /admin/jobs/schedule-sweep: a cron retry while a sweep is already
    running must not 503 the cron itself, otherwise tomorrow's sweep
    never gets scheduled.
"""

from fastapi.responses import JSONResponse

from app.core.maintenance import is_maintenance_active


class MaintenanceGateMiddleware:
    _ALLOWED_PATHS = frozenset(
        {"/", "/health", "/maintenance/status", "/admin/jobs/schedule-sweep"}
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
