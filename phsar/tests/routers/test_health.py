from httpx import ASGITransport, AsyncClient

from app import main
from app.main import create_app


async def test_health_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["db"] == "ok"
    assert "version" in payload


async def test_health_db_down(monkeypatch):
    class _BrokenSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("db unavailable")

    monkeypatch.setattr(main, "async_session_maker", lambda: _BrokenSession())

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["db"] == "error"
