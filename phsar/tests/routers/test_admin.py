import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.anime import Anime
from app.models.job import Job, JobKind, JobStatus
from app.models.media import Media
from app.models.media_studio import MediaStudio
from app.models.merge_candidate import MergeCandidate, MergeCandidateStatus
from app.models.studio import Studio
from app.models.users import RoleType, Users
from tests._helpers import media_kwargs
from tests.routers.conftest import CRON_AUTH_HEADER

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


@pytest.fixture
async def unflagged_pair(db_session):
    """Two anime sharing a studio with near-identical titles, but no
    pre-existing merge_candidate row — the backfill endpoint's target."""
    studio = Studio(name="Backfill Endpoint Studio")
    db_session.add(studio)
    await db_session.flush()

    a = Anime(mal_id=80201, title="Backfill Endpoint Show")
    b = Anime(mal_id=80202, title="Backfill Endpoint Show Season 2")
    db_session.add_all([a, b])
    await db_session.flush()

    media_a = Media(**media_kwargs(a.id, 802011, title="Backfill Endpoint Show"))
    media_b = Media(**media_kwargs(b.id, 802021, title="Backfill Endpoint Show Season 2"))
    db_session.add_all([media_a, media_b])
    await db_session.flush()

    db_session.add_all([
        MediaStudio(media_id=media_a.id, studio_id=studio.id),
        MediaStudio(media_id=media_b.id, studio_id=studio.id),
    ])
    await db_session.flush()
    return {"a_id": a.id, "b_id": b.id}


@pytest.mark.asyncio
async def test_rerun_merge_detection_flags_unflagged_pair(
    client, admin_auth_headers, unflagged_pair, db_session,
):
    resp = await client.post(f"{MERGE_URL}/backfill", headers=admin_auth_headers)
    assert resp.status_code == 200
    assert resp.json()["inserted"] >= 1

    a_id, b_id = sorted((unflagged_pair["a_id"], unflagged_pair["b_id"]))
    rows = (await db_session.execute(
        select(MergeCandidate).where(
            MergeCandidate.anime_a_id == a_id,
            MergeCandidate.anime_b_id == b_id,
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == MergeCandidateStatus.pending


@pytest.mark.asyncio
async def test_rerun_merge_detection_idempotent(
    client, admin_auth_headers, unflagged_pair,
):
    first = await client.post(f"{MERGE_URL}/backfill", headers=admin_auth_headers)
    second = await client.post(f"{MERGE_URL}/backfill", headers=admin_auth_headers)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["inserted"] == 0


@pytest.mark.asyncio
async def test_rerun_merge_detection_requires_admin(client, user_auth_headers):
    resp = await client.post(f"{MERGE_URL}/backfill", headers=user_auth_headers)
    assert resp.status_code == 403


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


@pytest.mark.asyncio
async def test_backup_auto_returns_202_with_job_uuid(
    cron_client, db_session,
):
    """Cron-authed POST /admin/backups/auto enqueues a `cron`-source
    backup job (no user attribution) and returns 202 + job_uuid.
    The dispatcher applies retention after the dump so the
    14-daily/8-Sunday/most-recent-known-good contract is preserved."""
    resp = await cron_client.post(AUTO_BACKUP_URL, headers=CRON_AUTH_HEADER)
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
async def test_backup_auto_requires_cron_token(cron_client):
    """No bearer → 401. Wrong bearer → 401. Same fail-closed pattern
    as schedule-sweep."""
    resp = await cron_client.post(AUTO_BACKUP_URL)
    assert resp.status_code == 401

    resp = await cron_client.post(
        AUTO_BACKUP_URL, headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401


STATS_URL = "/admin/stats/overview"


@pytest.mark.asyncio
async def test_stats_overview_returns_shape(client, admin_auth_headers):
    """Endpoint returns the full nested shape — catalog totals, jobs_7d
    per kind, activity_7d counters. Numbers depend on whatever the
    rolled-back test DB contains, so this test only asserts the
    structure + that every JobKind appears in jobs_7d.by_kind."""
    resp = await client.get(STATS_URL, headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert set(data.keys()) == {"catalog", "jobs_7d", "activity_7d"}
    assert set(data["catalog"].keys()) == {
        "anime_count", "media_count", "anime_added_7d", "media_added_7d",
    }
    assert set(data["activity_7d"].keys()) == {
        "active_users", "new_ratings", "scrapes_submitted",
    }
    kinds_returned = {row["kind"] for row in data["jobs_7d"]["by_kind"]}
    assert kinds_returned == {k.value for k in JobKind}


def _user_scrape_row(resp_json: dict) -> dict:
    return next(
        row for row in resp_json["jobs_7d"]["by_kind"]
        if row["kind"] == JobKind.user_scrape.value
    )


async def _admin_user_id(db_session) -> int:
    """The Job Health user_scrape row excludes system-attributed rows
    (requested_by_user_id NULL), so seeded test jobs need a real user
    to count. The admin is seeded at lifespan startup."""
    row = (await db_session.execute(
        select(Users).where(Users.username == settings.ADMIN_USERNAME)
    )).scalars().one()
    return row.id


@pytest.mark.asyncio
async def test_stats_overview_reflects_seeded_jobs(client, admin_auth_headers, db_session):
    """Seed one succeeded user_scrape + one permanently-failed user_scrape
    and verify the per-kind counters move accordingly. Failed-with-
    retryable=False should bump `failed` but NOT `retryable_failed`."""
    before = _user_scrape_row(
        (await client.get(STATS_URL, headers=admin_auth_headers)).json()
    )
    admin_id = await _admin_user_id(db_session)

    succeeded = Job(
        kind=JobKind.user_scrape, status=JobStatus.succeeded,
        payload={"query": "stats-test-succeeded"},
        result_summary={"retryable": True},
        requested_by_user_id=admin_id,
    )
    failed_permanent = Job(
        kind=JobKind.user_scrape, status=JobStatus.failed,
        payload={"query": "stats-test-failed"},
        result_summary={"retryable": False},
        requested_by_user_id=admin_id,
    )
    db_session.add_all([succeeded, failed_permanent])
    await db_session.flush()

    after = _user_scrape_row(
        (await client.get(STATS_URL, headers=admin_auth_headers)).json()
    )
    assert after["succeeded"] - before["succeeded"] == 1
    assert after["failed"] - before["failed"] == 1
    # Permanently-failed must NOT bump retryable_failed — that's the
    # whole point of the PermanentPhsarError marker.
    assert after["retryable_failed"] - before["retryable_failed"] == 0


@pytest.mark.asyncio
async def test_stats_overview_excludes_system_user_scrapes(client, admin_auth_headers, db_session):
    """user_scrape rows with requested_by_user_id NULL (seasonal-sweep
    children) shouldn't bump the User scrape row in Job Health — that
    surface is for user-submitted activity. Cover both branches: a
    succeeded system row shouldn't bump `succeeded`, and a failed one
    shouldn't bump `failed` (a Music/PV-filtered child would otherwise
    pollute the success rate)."""
    before = _user_scrape_row(
        (await client.get(STATS_URL, headers=admin_auth_headers)).json()
    )

    db_session.add_all([
        Job(
            kind=JobKind.user_scrape, status=JobStatus.succeeded,
            payload={"query": "system-test-ok", "mal_id": -99001},
            requested_by_user_id=None,
        ),
        Job(
            kind=JobKind.user_scrape, status=JobStatus.failed,
            payload={"query": "system-test-fail", "mal_id": -99002},
            result_summary={"retryable": False},
            requested_by_user_id=None,
        ),
    ])
    await db_session.flush()

    after = _user_scrape_row(
        (await client.get(STATS_URL, headers=admin_auth_headers)).json()
    )
    assert after["succeeded"] - before["succeeded"] == 0
    assert after["failed"] - before["failed"] == 0
    assert after["retryable_failed"] - before["retryable_failed"] == 0


@pytest.mark.asyncio
async def test_stats_overview_requires_admin(client, user_auth_headers):
    resp = await client.get(STATS_URL, headers=user_auth_headers)
    assert resp.status_code == 403


JOBS_LOG_URL = "/admin/jobs"


@pytest.mark.asyncio
async def test_admin_jobs_log_returns_paginated_shape(client, admin_auth_headers, db_session):
    """Seed two jobs and verify the page payload carries items + total +
    limit + offset, with each row flattening requested_by to a username
    string (or null for system jobs)."""
    user_job = Job(
        kind=JobKind.user_scrape, status=JobStatus.succeeded,
        payload={"query": "jobs-log-test-user"},
    )
    system_job = Job(
        kind=JobKind.update_sweep, status=JobStatus.succeeded,
        payload={"source": "cron"},
        requested_by_user_id=None,
    )
    db_session.add_all([user_job, system_job])
    await db_session.flush()

    resp = await client.get(JOBS_LOG_URL, headers=admin_auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) == {"items", "total", "limit", "offset"}
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert data["total"] >= 2

    # Every row carries the flattened username field (null for system jobs).
    for row in data["items"]:
        assert "requested_by_username" in row
        assert "uuid" in row
        assert "kind" in row


@pytest.mark.asyncio
async def test_admin_jobs_log_filters_by_kind(client, admin_auth_headers, db_session):
    """kind filter narrows the result; status filter compose-able with kind."""
    seed = Job(
        kind=JobKind.backup, status=JobStatus.succeeded,
        payload={"source": "manual"},
    )
    db_session.add(seed)
    await db_session.flush()

    resp = await client.get(
        f"{JOBS_LOG_URL}?kind=backup",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 200
    assert all(row["kind"] == "backup" for row in resp.json()["items"])


@pytest.mark.asyncio
async def test_admin_jobs_log_respects_limit_and_offset(client, admin_auth_headers, db_session):
    """A small limit truncates the page; non-zero offset skips."""
    # Seed 3 jobs so there's something to page through even on an empty DB.
    for i in range(3):
        db_session.add(Job(
            kind=JobKind.user_scrape, status=JobStatus.succeeded,
            payload={"query": f"jobs-log-page-{i}"},
        ))
    await db_session.flush()

    page1 = (await client.get(f"{JOBS_LOG_URL}?limit=1", headers=admin_auth_headers)).json()
    page2 = (await client.get(f"{JOBS_LOG_URL}?limit=1&offset=1", headers=admin_auth_headers)).json()
    # Floor `total` at the seeded 3 so the offset-advances assertion below
    # can't pass vacuously against unrelated rows from earlier tests.
    assert page1["total"] >= 3
    assert len(page1["items"]) == 1
    assert len(page2["items"]) == 1
    assert page1["items"][0]["uuid"] != page2["items"][0]["uuid"]


@pytest.mark.asyncio
async def test_admin_jobs_log_requires_admin(client, user_auth_headers):
    resp = await client.get(JOBS_LOG_URL, headers=user_auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_jobs_log_hides_children_by_default(client, admin_auth_headers, db_session):
    """The default unfiltered view excludes rows with a non-null
    parent_job_id, so seasonal-sweep children don't flood the list.
    `?parent_uuid=<sweep>` returns just that sweep's children."""
    parent = Job(kind=JobKind.seasonal_sweep, status=JobStatus.succeeded)
    db_session.add(parent)
    await db_session.flush()
    children = [
        Job(
            kind=JobKind.user_scrape, status=JobStatus.succeeded,
            payload={"query": f"clustered-child-{i}"},
            parent_job_id=parent.id,
        )
        for i in range(3)
    ]
    db_session.add_all(children)
    await db_session.flush()

    default = (await client.get(JOBS_LOG_URL, headers=admin_auth_headers)).json()
    default_uuids = {row["uuid"] for row in default["items"]}
    child_uuids = {str(c.uuid) for c in children}
    assert child_uuids.isdisjoint(default_uuids)
    assert str(parent.uuid) in default_uuids

    expanded = (await client.get(
        f"{JOBS_LOG_URL}?parent_uuid={parent.uuid}", headers=admin_auth_headers,
    )).json()
    assert expanded["total"] == 3
    assert {row["uuid"] for row in expanded["items"]} == child_uuids
    for row in expanded["items"]:
        assert row["parent_job_uuid"] == str(parent.uuid)


@pytest.mark.asyncio
async def test_admin_jobs_log_unknown_parent_returns_empty(client, admin_auth_headers):
    """A stale `?parent_uuid` (parent deleted between page load and
    click) returns an empty page rather than 404 — the surrounding
    view shouldn't break."""
    resp = await client.get(
        f"{JOBS_LOG_URL}?parent_uuid={uuid.uuid4()}", headers=admin_auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}
