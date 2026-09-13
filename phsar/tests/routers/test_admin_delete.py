"""Delete-candidate endpoint contract: role gating and the confirm gate.

Service-level lifecycle coverage lives in
`tests/services/test_delete_candidate_service.py`. What this file pins is the
part only the router owns — that every endpoint is admin-only, and that the
destructive one refuses without a matching username even for an admin.

The gating assertions matter more here than on the sibling curation routers:
`admin_delete.py` binds `require_admin` once on the APIRouter, so a handler
added with a plain `@router.post(...)` inherits it — but the two endpoints that
need `current_user` re-declare the dependency, and getting that wrong is how an
endpoint ends up authenticated but not admin-gated.
"""

import pytest
from sqlalchemy import select

from app.models.anime import Anime
from app.models.delete_candidate import DeleteCandidate, DeleteCandidateStatus
from app.models.media import Media
from tests._helpers import media_kwargs

DELETE_URL = "/admin/delete-candidates"


async def _seed_candidate(db_session, mal_id: int = -9600) -> DeleteCandidate:
    anime = Anime(mal_id=mal_id, title=f"A{mal_id}")
    db_session.add(anime)
    await db_session.flush()
    media = Media(**media_kwargs(anime.id, mal_id, title=f"M{mal_id}"))
    db_session.add(media)
    await db_session.flush()
    candidate = DeleteCandidate(
        media_id=media.id,
        mal_id=media.mal_id,
        title=media.title,
        detected_by="sweep_404",
        status=DeleteCandidateStatus.pending,
    )
    db_session.add(candidate)
    await db_session.flush()
    return candidate


@pytest.mark.asyncio
async def test_list_returns_pending_candidates(client, admin_auth_headers, db_session):
    candidate = await _seed_candidate(db_session, mal_id=-9601)

    resp = await client.get(DELETE_URL, headers=admin_auth_headers)

    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["uuid"] == str(candidate.uuid))
    assert row["mal_id"] == -9601
    assert row["detected_by"] == "sweep_404"
    assert row["rating_count"] == 0
    assert row["watchlist_count"] == 0
    assert row["dismissed_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", DELETE_URL, None),
        ("get", f"{DELETE_URL}/dismissed", None),
        ("post", f"{DELETE_URL}/backfill", {}),
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


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["dismiss", "remove", "delete"])
async def test_per_candidate_endpoints_require_admin(
    client, user_auth_headers, db_session, action,
):
    candidate = await _seed_candidate(db_session, mal_id=-9602)
    resp = await client.post(
        f"{DELETE_URL}/{candidate.uuid}/{action}",
        json={"confirm": "whatever"},
        headers=user_auth_headers,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_remove_refuses_a_confirm_that_is_not_the_admin_username(
    client, admin_auth_headers, db_session,
):
    """Admin rights alone are not enough — the destructive endpoint still wants
    the username typed, like backup restore."""
    candidate = await _seed_candidate(db_session, mal_id=-9603)

    resp = await client.post(
        f"{DELETE_URL}/{candidate.uuid}/remove",
        json={"confirm": "definitely-not-the-admin", "blacklist": False},
        headers=admin_auth_headers,
    )

    assert resp.status_code == 400
    await db_session.refresh(candidate)
    assert candidate.status == DeleteCandidateStatus.pending
    assert (
        await db_session.execute(select(Media).where(Media.mal_id == -9603))
    ).scalars().first() is not None


@pytest.mark.asyncio
async def test_dismiss_then_appears_in_the_dismissed_list(
    client, admin_auth_headers, db_session,
):
    candidate = await _seed_candidate(db_session, mal_id=-9604)

    assert (
        await client.post(
            f"{DELETE_URL}/{candidate.uuid}/dismiss", headers=admin_auth_headers,
        )
    ).status_code == 204

    listed = (
        await client.get(f"{DELETE_URL}/dismissed", headers=admin_auth_headers)
    ).json()
    row = next(r for r in listed if r["uuid"] == str(candidate.uuid))
    assert row["dismissed_at"] is not None

    # And it is gone from the live queue.
    pending = (await client.get(DELETE_URL, headers=admin_auth_headers)).json()
    assert all(r["uuid"] != str(candidate.uuid) for r in pending)


@pytest.mark.asyncio
async def test_resolving_twice_is_a_conflict(client, admin_auth_headers, db_session):
    candidate = await _seed_candidate(db_session, mal_id=-9605)
    await client.post(f"{DELETE_URL}/{candidate.uuid}/dismiss", headers=admin_auth_headers)

    resp = await client.post(
        f"{DELETE_URL}/{candidate.uuid}/dismiss", headers=admin_auth_headers,
    )
    assert resp.status_code == 409
