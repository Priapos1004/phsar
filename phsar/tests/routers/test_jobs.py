"""HTTP tests for /jobs router.

The dispatcher's actual MAL fetch is not exercised here — those go through
the JobWorker tests in tests/services/test_job_worker.py with fake
dispatchers. These tests cover only the enqueue/list/get endpoints, the
per-user cap, ownership checks, and the dedupe window.

Queries use a unique prefix per test invocation so the global dedupe check
doesn't trip on data left over from prior runs of the real app against
this DB.
"""

import uuid
from uuid import UUID

from app.core.config import settings
from app.core.job_versions import JOB_KIND_VERSIONS
from app.daos.job_dao import JobDAO
from app.models.job import JobKind, JobStatus
from app.models.users import RoleType

dao = JobDAO()


def _q(suffix: str = "") -> str:
    """Build a unique scrape query that won't collide with whatever's
    already in the dedupe window in the dev/CI database."""
    return f"test-{uuid.uuid4().hex[:8]}{suffix}"


async def test_enqueue_scrape_creates_queued_job(client, user_auth_headers, db_session):
    query = _q()
    resp = await client.post(
        "/jobs/scrape",
        json={"query": query},
        headers=user_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == JobStatus.queued.value
    assert data["kind"] == JobKind.user_scrape.value
    assert data["payload"] == {"query": query}
    assert data["items_done"] == 0
    # Bumping the registry without updating this assertion is the loud
    # signal that the API is now exposing a new result_summary shape.
    assert data["version"] == JOB_KIND_VERSIONS[JobKind.user_scrape]


async def test_enqueue_scrape_blocks_restricted_user(client, restricted_user_auth_headers):
    resp = await client.post(
        "/jobs/scrape",
        json={"query": _q()},
        headers=restricted_user_auth_headers,
    )
    assert resp.status_code == 403


async def test_enqueue_scrape_enforces_per_user_cap(client, user_auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "JOBS_PER_USER_LIMIT", 2)
    for _ in range(2):
        ok = await client.post(
            "/jobs/scrape",
            json={"query": _q()},
            headers=user_auth_headers,
        )
        assert ok.status_code == 200

    over = await client.post(
        "/jobs/scrape",
        json={"query": _q()},
        headers=user_auth_headers,
    )
    assert over.status_code == 409
    assert "active scrape jobs" in over.json()["detail"]


async def test_enqueue_scrape_cap_excludes_finished_jobs(client, user_auth_headers, db_session, monkeypatch):
    """A succeeded job from a previous scrape doesn't block the next enqueue —
    only queued + running count toward the cap."""
    monkeypatch.setattr(settings, "JOBS_PER_USER_LIMIT", 1)

    first = await client.post("/jobs/scrape", json={"query": _q("-older")}, headers=user_auth_headers)
    assert first.status_code == 200

    job = await dao.get_by_uuid(db_session, UUID(first.json()["uuid"]))
    job.status = JobStatus.succeeded
    await db_session.flush()

    second = await client.post("/jobs/scrape", json={"query": _q("-newer")}, headers=user_auth_headers)
    assert second.status_code == 200


async def test_enqueue_scrape_enforces_daily_cap(client, user_auth_headers, db_session, monkeypatch):
    """Daily cap counts succeeded jobs — finished work still occupies the
    24h slot, otherwise a fast turnover would defeat the volume limit."""
    monkeypatch.setattr(settings, "JOBS_DAILY_LIMIT", 3)

    for _ in range(3):
        ok = await client.post("/jobs/scrape", json={"query": _q()}, headers=user_auth_headers)
        assert ok.status_code == 200
        job = await dao.get_by_uuid(db_session, UUID(ok.json()["uuid"]))
        job.status = JobStatus.succeeded
        await db_session.flush()

    over = await client.post("/jobs/scrape", json={"query": _q()}, headers=user_auth_headers)
    assert over.status_code == 429
    assert "daily limit" in over.json()["detail"].lower()


async def test_enqueue_scrape_daily_cap_exempts_admin(client, admin_auth_headers, db_session, monkeypatch):
    """Admins are trusted operators, so the daily cap doesn't apply — submitting past
    the limit still succeeds (the concurrent cap + dedup still bound them)."""
    monkeypatch.setattr(settings, "JOBS_DAILY_LIMIT", 3)

    # One past the cap; mark each succeeded so the concurrent cap stays clear.
    for _ in range(settings.JOBS_DAILY_LIMIT + 1):
        ok = await client.post("/jobs/scrape", json={"query": _q()}, headers=admin_auth_headers)
        assert ok.status_code == 200, ok.text
        job = await dao.get_by_uuid(db_session, UUID(ok.json()["uuid"]))
        job.status = JobStatus.succeeded
        await db_session.flush()


async def test_enqueue_scrape_blocks_duplicate_recent_query(client, user_auth_headers):
    """Re-running the same query right after a previous run is rejected — the
    BFS would just see every mal_id in the excluded set and fail."""
    query = _q()
    first = await client.post(
        "/jobs/scrape", json={"query": query}, headers=user_auth_headers,
    )
    assert first.status_code == 200

    dup = await client.post(
        "/jobs/scrape", json={"query": query}, headers=user_auth_headers,
    )
    assert dup.status_code == 409
    assert "already" in dup.json()["detail"].lower()


async def test_enqueue_scrape_dedupe_is_case_insensitive(client, user_auth_headers):
    """The user typing the same query with different casing/whitespace
    should be detected as a duplicate."""
    base = _q()
    first = await client.post(
        "/jobs/scrape", json={"query": base.upper()}, headers=user_auth_headers,
    )
    assert first.status_code == 200

    dup = await client.post(
        "/jobs/scrape", json={"query": f"  {base.lower()}  "}, headers=user_auth_headers,
    )
    assert dup.status_code == 409


async def test_enqueue_scrape_allows_retry_after_failed_job(
    client, user_auth_headers, db_session,
):
    """A failed job (e.g. MAL outage) should NOT lock the query out — the
    user must be able to retry."""
    query = _q()
    first = await client.post(
        "/jobs/scrape", json={"query": query}, headers=user_auth_headers,
    )
    assert first.status_code == 200

    job = await dao.get_by_uuid(db_session, UUID(first.json()["uuid"]))
    job.status = JobStatus.failed
    await db_session.flush()

    retry = await client.post(
        "/jobs/scrape", json={"query": query}, headers=user_auth_headers,
    )
    assert retry.status_code == 200


async def test_enqueue_scrape_validates_payload(client, user_auth_headers):
    resp = await client.post(
        "/jobs/scrape",
        json={"query": ""},
        headers=user_auth_headers,
    )
    assert resp.status_code == 422


async def test_enqueue_scrape_rejects_short_query(client, user_auth_headers):
    """Queries below the 4-char minimum are ambiguous on MAL and waste a job slot."""
    resp = await client.post(
        "/jobs/scrape",
        json={"query": "fma"},
        headers=user_auth_headers,
    )
    assert resp.status_code == 422


async def test_enqueue_scrape_accepts_optional_mal_id(client, user_auth_headers):
    """Callers can opt into the seed-mal_id path that the seasonal sweep
    uses (skips MAL's fuzzy q= lookup). Without mal_id the existing
    fuzzy path is preserved."""
    query = _q()
    resp = await client.post(
        "/jobs/scrape",
        json={"query": query, "mal_id": 12345},
        headers=user_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["payload"] == {"query": query, "mal_id": 12345}


async def test_enqueue_scrape_rejects_non_positive_mal_id(client, user_auth_headers):
    """gt=0 — anything else is a malformed payload, fail fast at the
    edge instead of letting it land in a Job row that'll error inside
    the dispatcher much later."""
    resp = await client.post(
        "/jobs/scrape",
        json={"query": _q(), "mal_id": 0},
        headers=user_auth_headers,
    )
    assert resp.status_code == 422


async def test_list_my_jobs_returns_only_my_jobs(client, user_auth_headers):
    a, b = _q("-alpha"), _q("-bravo")
    await client.post("/jobs/scrape", json={"query": a}, headers=user_auth_headers)
    await client.post("/jobs/scrape", json={"query": b}, headers=user_auth_headers)

    resp = await client.get("/jobs/mine", headers=user_auth_headers)
    assert resp.status_code == 200
    jobs = resp.json()
    assert len(jobs) == 2
    assert {j["payload"]["query"] for j in jobs} == {a, b}


async def test_get_job_owner_can_read(client, user_auth_headers):
    create_resp = await client.post(
        "/jobs/scrape",
        json={"query": _q()},
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
        json={"query": _q()},
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
        json={"query": _q()},
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
