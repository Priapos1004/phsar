import uuid

import pytest
from sqlalchemy import select

from app.models.anime import Anime
from app.models.media import Media
from app.models.media_studio import MediaStudio
from app.models.merge_candidate import MergeCandidate, MergeCandidateStatus
from app.models.studio import Studio
from app.models.users import RoleType
from tests._helpers import media_kwargs

TOKENS_URL = "/admin/registration-tokens"
MERGE_URL = "/admin/merge-candidates"


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
