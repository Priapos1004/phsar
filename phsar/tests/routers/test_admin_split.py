"""Endpoint tests for the admin split-candidate queue (`app/routers/admin_split.py`).

The split itself — new anime rows, re-parented media, preserved ratings — is pinned
in tests/services/test_split_candidate_service.py, and detection in
test_relation_classifier.py. This file covers only what sits above the service: the
router-level admin gate, and the serialization each handler returns.
"""

import uuid

import pytest
from sqlalchemy import select

from app.models.anime import Anime
from app.models.media import Media, RelationType
from app.models.media_relation_edges import MediaRelationEdges
from app.models.split_candidate import SplitCandidate, SplitCandidateStatus
from tests._helpers import media_kwargs, split_cluster

SPLIT_URL = "/admin/split-candidates"


@pytest.fixture
async def split_candidate(db_session):
    """An anime holding two disjoint main chains, plus its pending candidate:
    a main anchor with an offshoot pair hanging off it by spin-off.
    """
    source = Anime(mal_id=82001, title="Split Router Source")
    db_session.add(source)
    await db_session.flush()

    anchor = Media(**media_kwargs(
        source.id, 820011, title="Source S1",
        relation_type=RelationType.Main, episodes=13, duration_seconds=1440,
    ))
    off_s1 = Media(**media_kwargs(
        source.id, 820021, title="Offshoot S1",
        relation_type=RelationType.SideStory, episodes=13, duration_seconds=1440,
    ))
    off_s2 = Media(**media_kwargs(
        source.id, 820022, title="Offshoot S2",
        relation_type=RelationType.SideStory, episodes=13, duration_seconds=1440,
    ))
    db_session.add_all([anchor, off_s1, off_s2])
    await db_session.flush()

    db_session.add_all([
        MediaRelationEdges(media_id=anchor.id, edges=[[820021, "spin-off"]]),
        MediaRelationEdges(media_id=off_s1.id, edges=[
            [820011, "parent_story"], [820022, "sequel"],
        ]),
        MediaRelationEdges(media_id=off_s2.id, edges=[[820021, "prequel"]]),
    ])

    candidate = SplitCandidate(
        anime_id=source.id,
        clusters=[split_cluster(820021, [820021, 820022],
                                [[820011, 820021, "spin-off"]])],
        status=SplitCandidateStatus.pending,
        detected_by="scrape",
    )
    db_session.add(candidate)
    await db_session.flush()

    return {
        "anime_id": source.id,
        "anchor_id": anchor.id,
        "offshoot_ids": [off_s1.id, off_s2.id],
        "candidate_uuid": str(candidate.uuid),
    }


# ---------------------------------------------------------------------------
# The gate. One `dependencies=[Depends(require_admin)]` on the router covers every
# route, so these walk the routes rather than repeating a test per handler — and
# they take no fixture, because the gate rejects before the uuid is ever resolved.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", SPLIT_URL, None),
        ("get", f"{SPLIT_URL}/dismissed", None),
        ("post", f"{SPLIT_URL}/backfill", {}),
    ],
)
async def test_collection_endpoints_require_admin(
    client, user_auth_headers, method, path, body,
):
    call = getattr(client, method)
    resp = await call(path, headers=user_auth_headers) if body is None else await call(
        path, json=body, headers=user_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.parametrize("action", ["split", "dismiss", "delete"])
async def test_per_candidate_endpoints_require_admin(client, user_auth_headers, action):
    resp = await client.post(
        f"{SPLIT_URL}/{uuid.uuid4()}/{action}", json={}, headers=user_auth_headers,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Serialization and status mapping
# ---------------------------------------------------------------------------


async def test_list_split_candidates_admin(client, admin_auth_headers, split_candidate):
    resp = await client.get(SPLIT_URL, headers=admin_auth_headers)
    assert resp.status_code == 200

    found = [c for c in resp.json() if c["uuid"] == split_candidate["candidate_uuid"]]
    assert len(found) == 1
    payload = found[0]
    assert payload["detected_by"] == "scrape"
    assert payload["source_anime"]["media_count"] == 3
    assert len(payload["clusters"]) == 1


async def test_dismiss_split_candidate(
    client, admin_auth_headers, split_candidate, db_session,
):
    resp = await client.post(
        f"{SPLIT_URL}/{split_candidate['candidate_uuid']}/dismiss",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 204

    row = (await db_session.execute(
        select(SplitCandidate).where(
            SplitCandidate.anime_id == split_candidate["anime_id"]
        )
    )).scalars().first()
    assert row.status == SplitCandidateStatus.dismissed


async def test_dismiss_already_resolved_returns_409(
    client, admin_auth_headers, split_candidate, db_session,
):
    row = (await db_session.execute(
        select(SplitCandidate).where(
            SplitCandidate.anime_id == split_candidate["anime_id"]
        )
    )).scalars().first()
    row.status = SplitCandidateStatus.dismissed
    await db_session.flush()

    resp = await client.post(
        f"{SPLIT_URL}/{split_candidate['candidate_uuid']}/dismiss",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 409


async def test_dismissed_listing_stamps_dismissed_at(
    client, admin_auth_headers, split_candidate,
):
    await client.post(
        f"{SPLIT_URL}/{split_candidate['candidate_uuid']}/dismiss",
        headers=admin_auth_headers,
    )

    resp = await client.get(f"{SPLIT_URL}/dismissed", headers=admin_auth_headers)
    assert resp.status_code == 200
    found = [c for c in resp.json() if c["uuid"] == split_candidate["candidate_uuid"]]
    assert len(found) == 1
    # Only this list populates it; the pending queue leaves it null.
    assert found[0]["dismissed_at"] is not None


async def test_delete_decision_lets_it_resurface(
    client, admin_auth_headers, split_candidate, db_session,
):
    await client.post(
        f"{SPLIT_URL}/{split_candidate['candidate_uuid']}/dismiss",
        headers=admin_auth_headers,
    )

    resp = await client.post(
        f"{SPLIT_URL}/{split_candidate['candidate_uuid']}/delete",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 204

    row = (await db_session.execute(
        select(SplitCandidate).where(
            SplitCandidate.anime_id == split_candidate["anime_id"]
        )
    )).scalars().first()
    assert row is None


async def test_split_returns_one_new_anime_uuid_per_cluster(
    client, admin_auth_headers, split_candidate,
):
    """Re-parenting is the service's contract and is pinned there; what the route
    owns is turning the `(surviving, new)` tuple into the response body."""
    resp = await client.post(
        f"{SPLIT_URL}/{split_candidate['candidate_uuid']}/split",
        headers=admin_auth_headers,
    )
    assert resp.status_code == 200

    body = resp.json()
    assert len(body["new_anime_uuids"]) == 1
    assert uuid.UUID(body["new_anime_uuids"][0])
    assert uuid.UUID(body["surviving_anime_uuid"])


async def test_split_unknown_uuid_returns_404(client, admin_auth_headers):
    resp = await client.post(
        f"{SPLIT_URL}/{uuid.uuid4()}/split", headers=admin_auth_headers,
    )
    assert resp.status_code == 404
