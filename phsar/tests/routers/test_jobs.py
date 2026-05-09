"""HTTP tests for /jobs router.

The dispatcher's actual MAL fetch is not exercised here — those go through
the JobWorker tests in tests/services/test_job_worker.py with fake
dispatchers. These tests cover only the enqueue/list/get endpoints, the
per-user cap, and ownership checks.
"""

from app.core.config import settings
from app.daos.job_dao import JobDAO
from app.models.job import JobKind, JobStatus
from app.models.users import RoleType

dao = JobDAO()


async def test_enqueue_scrape_creates_queued_job(client, user_auth_headers, db_session):
    resp = await client.post(
        "/jobs/scrape",
        json={"query": "naruto"},
        headers=user_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == JobStatus.queued.value
    assert data["kind"] == JobKind.user_scrape.value
    assert data["payload"] == {"query": "naruto"}
    assert data["items_done"] == 0


async def test_enqueue_scrape_blocks_restricted_user(client, restricted_user_auth_headers):
    resp = await client.post(
        "/jobs/scrape",
        json={"query": "naruto"},
        headers=restricted_user_auth_headers,
    )
    assert resp.status_code == 403


async def test_enqueue_scrape_enforces_per_user_cap(client, user_auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "JOBS_PER_USER_LIMIT", 2)
    for i in range(2):
        ok = await client.post(
            "/jobs/scrape",
            json={"query": f"q{i}"},
            headers=user_auth_headers,
        )
        assert ok.status_code == 200

    over = await client.post(
        "/jobs/scrape",
        json={"query": "q-over"},
        headers=user_auth_headers,
    )
    assert over.status_code == 409
    assert "active scrape jobs" in over.json()["detail"]


async def test_enqueue_scrape_cap_excludes_finished_jobs(client, user_auth_headers, db_session, monkeypatch):
    """A succeeded job from a previous scrape doesn't block the next enqueue —
    only queued + running count toward the cap."""
    from uuid import UUID

    monkeypatch.setattr(settings, "JOBS_PER_USER_LIMIT", 1)

    first = await client.post("/jobs/scrape", json={"query": "old"}, headers=user_auth_headers)
    assert first.status_code == 200

    job = await dao.get_by_uuid(db_session, UUID(first.json()["uuid"]))
    job.status = JobStatus.succeeded
    await db_session.flush()

    second = await client.post("/jobs/scrape", json={"query": "new"}, headers=user_auth_headers)
    assert second.status_code == 200


async def test_enqueue_scrape_validates_payload(client, user_auth_headers):
    resp = await client.post(
        "/jobs/scrape",
        json={"query": ""},
        headers=user_auth_headers,
    )
    assert resp.status_code == 422


async def test_list_my_jobs_returns_only_my_jobs(client, user_auth_headers):
    await client.post("/jobs/scrape", json={"query": "a"}, headers=user_auth_headers)
    await client.post("/jobs/scrape", json={"query": "b"}, headers=user_auth_headers)

    resp = await client.get("/jobs/mine", headers=user_auth_headers)
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) == 2
    assert {j["payload"]["query"] for j in jobs} == {"a", "b"}


async def test_get_job_owner_can_read(client, user_auth_headers):
    create_resp = await client.post(
        "/jobs/scrape",
        json={"query": "x"},
        headers=user_auth_headers,
    )
    uuid_ = create_resp.json()["uuid"]

    resp = await client.get(f"/jobs/{uuid_}", headers=user_auth_headers)
    assert resp.status_code == 200
    assert resp.json()["uuid"] == uuid_


async def test_get_job_other_user_blocked(client, user_auth_headers, create_user_with_role):
    """A different normal user cannot read someone else's job."""
    create_resp = await client.post(
        "/jobs/scrape",
        json={"query": "x"},
        headers=user_auth_headers,
    )
    uuid_ = create_resp.json()["uuid"]

    other_token = await create_user_with_role(
        username="otheruser", password="otherpass", role=RoleType.User,
    )
    resp = await client.get(
        f"/jobs/{uuid_}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 403


async def test_get_job_admin_can_read_any(client, user_auth_headers, admin_auth_headers):
    create_resp = await client.post(
        "/jobs/scrape",
        json={"query": "x"},
        headers=user_auth_headers,
    )
    uuid_ = create_resp.json()["uuid"]

    resp = await client.get(f"/jobs/{uuid_}", headers=admin_auth_headers)
    assert resp.status_code == 200


async def test_get_job_unknown_uuid_404(client, user_auth_headers):
    resp = await client.get(
        "/jobs/00000000-0000-0000-0000-000000000000",
        headers=user_auth_headers,
    )
    assert resp.status_code == 404
