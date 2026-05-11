import uuid

import pytest
from fastapi import Header
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.dependencies import get_db, require_backup_cron_token
from app.exceptions import InvalidCronTokenError
from app.main import create_app
from app.models.anime import Anime
from app.models.job import Job, JobKind, JobStatus
from app.models.media import Media
from app.models.media_studio import MediaStudio
from app.models.merge_candidate import MergeCandidate, MergeCandidateStatus
from app.models.studio import Studio
from app.models.users import RoleType
from tests._helpers import media_kwargs

TOKENS_URL = "/admin/registration-tokens"
MERGE_URL = "/admin/merge-candidates"
BACKUPS_URL = "/admin/backups"
AUTO_BACKUP_URL = "/admin/backups/auto"


@pytest.mark.asyncio
async def test_create_token(client, admin_auth_headers):
    resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value},
        headers=admin_auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["role"] == RoleType.User.value
    assert data["expires_on"] is not None


@pytest.mark.asyncio
async def test_create_token_with_expiry(client, admin_auth_headers):
    resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value, "expires_in_days": 30},
        headers=admin_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == RoleType.User.value


@pytest.mark.asyncio
async def test_create_token_invalid_expiry(client, admin_auth_headers):
    resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value, "expires_in_days": 15},
        headers=admin_auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_token_requires_admin(client, user_auth_headers):
    resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value},
        headers=user_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_token_restricted_user_forbidden(client, restricted_user_auth_headers):
    resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value},
        headers=restricted_user_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_tokens(client, admin_auth_headers):
    # Create two tokens
    await client.post(TOKENS_URL, json={"role": RoleType.User.value}, headers=admin_auth_headers)
    await client.post(TOKENS_URL, json={"role": RoleType.RestrictedUser.value}, headers=admin_auth_headers)

    resp = await client.get(TOKENS_URL, headers=admin_auth_headers)
    assert resp.status_code == 200
    tokens = resp.json()
    assert len(tokens) >= 2

    # Verify structure of first token
    t = tokens[0]
    assert "uuid" in t
    assert "token" in t
    assert "status" in t
    assert t["status"] in ("active", "used", "expired")


@pytest.mark.asyncio
async def test_list_tokens_requires_admin(client, user_auth_headers):
    resp = await client.get(TOKENS_URL, headers=user_auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_tokens_shows_used_status(client, admin_auth_headers):
    # Create a token and use it to register a user
    create_resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value},
        headers=admin_auth_headers,
    )
    reg_token = create_resp.json()["token"]

    await client.post("/auth/register", json={
        "username": "usedtokenuser",
        "password": "testpassword",
        "registration_token": reg_token,
    })

    # List and find the used token
    list_resp = await client.get(TOKENS_URL, headers=admin_auth_headers)
    tokens = list_resp.json()
    used = [t for t in tokens if t["token"] == reg_token]
    assert len(used) == 1
    assert used[0]["status"] == "used"
    assert used[0]["used_by"] == "usedtokenuser"


@pytest.mark.asyncio
async def test_delete_unused_token(client, admin_auth_headers):
    # Create a token
    create_resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value},
        headers=admin_auth_headers,
    )
    token_str = create_resp.json()["token"]

    # Find its uuid
    list_resp = await client.get(TOKENS_URL, headers=admin_auth_headers)
    token_entry = next(t for t in list_resp.json() if t["token"] == token_str)

    # Delete it
    del_resp = await client.delete(f"{TOKENS_URL}/{token_entry['uuid']}", headers=admin_auth_headers)
    assert del_resp.status_code == 204

    # Verify it's gone
    list_resp2 = await client.get(TOKENS_URL, headers=admin_auth_headers)
    uuids = [t["uuid"] for t in list_resp2.json()]
    assert token_entry["uuid"] not in uuids


@pytest.mark.asyncio
async def test_delete_used_token_fails(client, admin_auth_headers):
    # Create and use a token
    create_resp = await client.post(
        TOKENS_URL,
        json={"role": RoleType.User.value},
        headers=admin_auth_headers,
    )
    reg_token = create_resp.json()["token"]

    await client.post("/auth/register", json={
        "username": "useddeluser",
        "password": "testpassword",
        "registration_token": reg_token,
    })

    # Find its uuid
    list_resp = await client.get(TOKENS_URL, headers=admin_auth_headers)
    token_entry = next(t for t in list_resp.json() if t["token"] == reg_token)

    # Attempt delete — should fail
    del_resp = await client.delete(f"{TOKENS_URL}/{token_entry['uuid']}", headers=admin_auth_headers)
    assert del_resp.status_code == 400


@pytest.mark.asyncio
async def test_delete_invalid_uuid_format(client, admin_auth_headers):
    resp = await client.delete(f"{TOKENS_URL}/not-a-uuid", headers=admin_auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_nonexistent_token(client, admin_auth_headers):
    resp = await client.delete(f"{TOKENS_URL}/{uuid.uuid4()}", headers=admin_auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_token_requires_admin(client, user_auth_headers):
    resp = await client.delete(f"{TOKENS_URL}/{uuid.uuid4()}", headers=user_auth_headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Merge candidates
# ---------------------------------------------------------------------------


@pytest.fixture
async def merge_pair(db_session):
    """Two anime sharing a studio, plus a pending merge candidate row."""
    studio = Studio(name="Merge Test Studio")
    db_session.add(studio)
    await db_session.flush()

    a = Anime(mal_id=80101, title="Merge Test")
    b = Anime(mal_id=80102, title="Merge Test 2")
    db_session.add_all([a, b])
    await db_session.flush()

    media_a = Media(**media_kwargs(a.id, 801011))
    media_b = Media(**media_kwargs(b.id, 801021))
    db_session.add_all([media_a, media_b])
    await db_session.flush()

    db_session.add_all([
        MediaStudio(media_id=media_a.id, studio_id=studio.id),
        MediaStudio(media_id=media_b.id, studio_id=studio.id),
    ])
    await db_session.flush()

    a_id, b_id = sorted((a.id, b.id))
    candidate = MergeCandidate(
        anime_a_id=a_id,
        anime_b_id=b_id,
        similarity_score=0.95,
        detected_by="title_studio",
        status=MergeCandidateStatus.pending,
    )
    db_session.add(candidate)
    await db_session.flush()
    return {"a_id": a_id, "b_id": b_id, "candidate_uuid": str(candidate.uuid)}


@pytest.mark.asyncio
async def test_list_merge_candidates_admin(client, admin_auth_headers, merge_pair):
    resp = await client.get(MERGE_URL, headers=admin_auth_headers)
    assert resp.status_code == 200
    items = resp.json()
    found = [c for c in items if c["uuid"] == merge_pair["candidate_uuid"]]
    assert len(found) == 1
    payload = found[0]
    assert payload["similarity_score"] == 0.95
    assert payload["detected_by"] == "title_studio"
    assert payload["anime_a"]["media_count"] == 1
    assert "Merge Test Studio" in payload["anime_a"]["studios"]


@pytest.mark.asyncio
async def test_list_merge_candidates_requires_admin(client, user_auth_headers):
    resp = await client.get(MERGE_URL, headers=user_auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_dismiss_merge_candidate(client, admin_auth_headers, merge_pair, db_session):
    resp = await client.post(
        f"{MERGE_URL}/{merge_pair['candidate_uuid']}/dismiss",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 204

    row = (await db_session.execute(
        select(MergeCandidate).where(MergeCandidate.anime_a_id == merge_pair["a_id"])
    )).scalars().first()
    assert row.status == MergeCandidateStatus.dismissed


@pytest.mark.asyncio
async def test_dismiss_already_resolved_returns_409(client, admin_auth_headers, merge_pair, db_session):
    row = (await db_session.execute(
        select(MergeCandidate).where(MergeCandidate.anime_a_id == merge_pair["a_id"])
    )).scalars().first()
    row.status = MergeCandidateStatus.dismissed
    await db_session.flush()

    resp = await client.post(
        f"{MERGE_URL}/{merge_pair['candidate_uuid']}/dismiss",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_merge_candidate_reparents_media(client, admin_auth_headers, merge_pair, db_session):
    resp = await client.post(
        f"{MERGE_URL}/{merge_pair['candidate_uuid']}/merge",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "surviving_anime_uuid" in body

    # Anime B is gone; its media now points at A.
    surviving = (await db_session.execute(
        select(Anime).where(Anime.id == merge_pair["a_id"])
    )).scalars().first()
    deleted = (await db_session.execute(
        select(Anime).where(Anime.id == merge_pair["b_id"])
    )).scalars().first()
    assert surviving is not None
    assert deleted is None

    media_under_a = (await db_session.execute(
        select(Media).where(Media.anime_id == merge_pair["a_id"])
    )).scalars().all()
    assert len(media_under_a) == 2  # A's original media + re-parented from B

    # Candidate row was cascaded away by the FK on anime_b_id when B
    # was deleted — no audit row survives the merge.
    row = (await db_session.execute(
        select(MergeCandidate).where(MergeCandidate.anime_a_id == merge_pair["a_id"])
    )).scalars().first()
    assert row is None


@pytest.mark.asyncio
async def test_merge_endpoint_requires_admin(client, user_auth_headers, merge_pair):
    resp = await client.post(
        f"{MERGE_URL}/{merge_pair['candidate_uuid']}/merge",
        headers=user_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_merge_unknown_uuid_returns_404(client, admin_auth_headers):
    resp = await client.post(
        f"{MERGE_URL}/{uuid.uuid4()}/merge",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Async backups — both endpoints now enqueue a `backup` job and return 202
# instead of blocking on pg_dump in the request thread. These tests pin the
# enqueue contract; the dispatcher's behavior is exercised in
# tests/services/test_backup_jobs.py.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_backup_returns_202_with_job_uuid(
    client, admin_auth_headers, db_session,
):
    """Manual POST /admin/backups enqueues a backup job attributed to the
    calling admin and returns 202 + job_uuid. The dispatcher does the
    real pg_dump asynchronously — the request returns immediately so
    the bell + toast can take over."""
    resp = await client.post(BACKUPS_URL, headers=admin_auth_headers)
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert "job_uuid" in body

    job = (await db_session.execute(
        select(Job).where(Job.uuid == body["job_uuid"])
    )).scalars().first()
    assert job is not None
    assert job.kind is JobKind.backup
    assert job.status is JobStatus.queued
    assert job.payload == {"source": "manual"}
    # Manual backups attribute to the admin user so they surface in
    # *their* bell only — multi-admin deployments avoid cross-admin
    # bell clutter.
    assert job.requested_by_user_id is not None


@pytest.mark.asyncio
async def test_create_backup_with_label_carries_label_in_payload(
    client, admin_auth_headers, db_session,
):
    """The dispatcher passes the optional `label` through to
    backup_service.create_backup, which appends it to the dump filename.
    Pin the payload contract here so the dispatcher can rely on the
    field being present when given."""
    resp = await client.post(
        BACKUPS_URL,
        json={"label": "pre-migration"},
        headers=admin_auth_headers,
    )
    assert resp.status_code == 202, resp.text

    job = (await db_session.execute(
        select(Job).where(Job.uuid == resp.json()["job_uuid"])
    )).scalars().first()
    assert job is not None
    assert job.payload == {"source": "manual", "label": "pre-migration"}


@pytest.mark.asyncio
async def test_create_backup_requires_admin(client, user_auth_headers):
    """Regular users can't enqueue backups — same auth surface as
    pre-async. The 403 here is what stops a regular user from
    DoS'ing the worker queue with backup jobs."""
    resp = await client.post(BACKUPS_URL, headers=user_auth_headers)
    assert resp.status_code == 403


@pytest.fixture
async def cron_backup_client(db_session):
    """Mirrors test_admin_sweep's cron_client: override the cron-token
    dep with a literal-token check so we don't depend on
    settings.BACKUP_CRON_TOKEN being set in the test env."""
    app = create_app()

    async def override_get_db():
        yield db_session

    def fake_require(authorization: str | None = Header(default=None)) -> None:
        if authorization != "Bearer test-backup-token":
            raise InvalidCronTokenError()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_backup_cron_token] = fake_require

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_backup_auto_returns_202_with_job_uuid(
    cron_backup_client, db_session,
):
    """Cron-authed POST /admin/backups/auto enqueues a `cron`-source
    backup job (no user attribution) and returns 202 + job_uuid.
    The dispatcher applies retention after the dump so the
    14-daily/8-Sunday/most-recent-known-good contract is preserved."""
    resp = await cron_backup_client.post(
        AUTO_BACKUP_URL,
        headers={"Authorization": "Bearer test-backup-token"},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert "job_uuid" in body

    job = (await db_session.execute(
        select(Job).where(Job.uuid == body["job_uuid"])
    )).scalars().first()
    assert job is not None
    assert job.kind is JobKind.backup
    assert job.status is JobStatus.queued
    assert job.payload == {"source": "cron"}
    # System job — invisible to every user's bell. The dump list IS the
    # audit log for scheduled backups.
    assert job.requested_by_user_id is None


@pytest.mark.asyncio
async def test_backup_auto_requires_cron_token(cron_backup_client):
    """No bearer → 401. Wrong bearer → 401. Same fail-closed pattern
    as schedule-sweep."""
    resp = await cron_backup_client.post(AUTO_BACKUP_URL)
    assert resp.status_code == 401

    resp = await cron_backup_client.post(
        AUTO_BACKUP_URL, headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401
