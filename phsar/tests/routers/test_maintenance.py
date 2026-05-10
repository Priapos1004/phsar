"""GET /maintenance/status + middleware allowlist tests.

`reset_maintenance_state` (autouse, top-level conftest) clears the module
globals around every test, so we can flip them inline without leaking.
"""

from datetime import datetime, timezone

from app.core import maintenance


async def test_status_default_is_idle(client):
    res = await client.get("/maintenance/status")
    assert res.status_code == 200
    body = res.json()
    assert body == {"active": False, "scheduled_at": None}


async def test_status_reflects_module_globals(client):
    when = datetime(2026, 5, 11, 3, 0, 0, tzinfo=timezone.utc)
    maintenance.set_scheduled_at(when)
    maintenance.set_maintenance(True)

    res = await client.get("/maintenance/status")
    assert res.status_code == 200
    body = res.json()
    assert body["active"] is True
    # FastAPI serializes datetime with the same isoformat — strip Z handling
    # to keep the assertion liberal across pydantic versions.
    assert body["scheduled_at"].startswith("2026-05-11T03:00:00")


async def test_status_endpoint_reachable_during_maintenance(client):
    """The endpoint must stay reachable while the flag is on so the banner
    can keep polling — otherwise users hit /login?maintenance=1 with no
    countdown and no way to know when service resumes."""
    maintenance.set_maintenance(True)

    res = await client.get("/maintenance/status")
    assert res.status_code == 200


async def test_other_endpoints_503_during_maintenance(client):
    """Sanity: the gate still fires for non-allowlisted paths. /jobs/mine is
    a normal user endpoint that should be 503'd while a sweep is running."""
    maintenance.set_maintenance(True)

    res = await client.get("/jobs/mine")
    assert res.status_code == 503
    body = res.json()
    assert body.get("maintenance") is True


async def test_503_carries_cors_headers_for_cross_origin_requests(client):
    """Cross-origin 503s must include Access-Control-Allow-Origin or the
    browser blocks the response and fetch() rejects with a TypeError —
    pushing the frontend's catch into the generic "unexpected error"
    branch instead of the maintenance-banner branch.

    Regression test for the middleware-order bug: registering the
    maintenance gate AFTER CORSMiddleware (via add_middleware) put the
    gate OUTSIDE CORS — so 503 short-circuits never reached CORS's
    response-header injection.
    """
    maintenance.set_maintenance(True)

    res = await client.post(
        "/auth/login",
        data={"username": "x", "password": "x"},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "http://localhost:5173",
        },
    )
    assert res.status_code == 503
    assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"
