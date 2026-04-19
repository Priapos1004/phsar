from app.core.dependencies import get_db
from app.main import create_app


async def test_health_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["db"] == "ok"
    assert "version" in payload


async def test_health_db_down():
    app = create_app()

    async def broken_db():
        class _BrokenSession:
            async def execute(self, *_args, **_kwargs):
                raise RuntimeError("db unavailable")
        yield _BrokenSession()

    app.dependency_overrides[get_db] = broken_db

    from httpx import ASGITransport, AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["db"] == "error"
