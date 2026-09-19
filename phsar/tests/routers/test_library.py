"""GET /library/recent — the 'recent additions' panel on /library/add.

A thin read calling AnimeDAO.list_recent directly, which `.claude/rules/backend.md`
allows for fetch-and-return with no branching. So the facts here are the router's
own: the auth choice, the Query bounds, and that the listing is newest-first.

The `(created_at DESC, id DESC)` tiebreak inside `recency_order` is pinned where
its absence does real damage — the paginated queries in test_job_dao.py and
test_watchlist_service.py. This endpoint is unpaginated and capped at 50, so a
third copy here would assert the helper rather than anything /library/recent owns.
"""

from datetime import datetime, timedelta, timezone

from app.models.anime import Anime

URL = "/library/recent"


async def test_recent_requires_authentication(client):
    resp = await client.get(URL)
    assert resp.status_code == 401


async def test_recent_returns_newest_first(client, user_auth_headers, db_session):
    """created_at is stamped explicitly. Left to `server_default=func.now()` the
    two rows would take the transaction-start time and tie exactly, and the
    assertion would be riding the id tiebreak instead of the sort column.
    """
    now = datetime.now(timezone.utc)
    older = Anime(mal_id=83001, title="Library Older", created_at=now - timedelta(days=2))
    newer = Anime(mal_id=83002, title="Library Newer", created_at=now - timedelta(days=1))
    db_session.add_all([older, newer])
    await db_session.flush()

    resp = await client.get(f"{URL}?limit=50", headers=user_auth_headers)
    assert resp.status_code == 200

    uuids = [row["uuid"] for row in resp.json()]
    assert str(newer.uuid) in uuids
    assert uuids.index(str(newer.uuid)) < uuids.index(str(older.uuid))


async def test_recent_rejects_out_of_range_limits(client, user_auth_headers):
    for bad in (0, 51):
        resp = await client.get(f"{URL}?limit={bad}", headers=user_auth_headers)
        assert resp.status_code == 422, f"limit={bad} should be rejected"


async def test_recent_is_open_to_a_restricted_guest(
    client, restricted_user_auth_headers,
):
    """Deliberately `get_current_user`, not `require_user_or_admin`: the rows are
    not caller-scoped, so an empty answer would not be a permission signal.
    """
    resp = await client.get(URL, headers=restricted_user_auth_headers)
    assert resp.status_code == 200
