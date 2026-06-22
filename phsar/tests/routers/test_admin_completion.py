import pytest

from app.models.anime import Anime
from app.models.media import Media
from tests._helpers import media_kwargs


@pytest.fixture
async def completion_anime(db_session):
    """A minimal anime + media for story-complete marking."""
    anime = Anime(mal_id=313131, title="Completion Test Anime")
    db_session.add(anime)
    await db_session.flush()
    db_session.add(Media(**media_kwargs(anime.id, 313131, title="Completion Test Media")))
    await db_session.flush()
    return anime


async def test_default_not_finished(client, admin_auth_headers, completion_anime):
    detail = await client.get(f"/media/anime/{completion_anime.uuid}", headers=admin_auth_headers)
    assert detail.json()["is_finished"] is False


# NOTE: the test harness binds the app session to a connection without
# savepoint-join, so API commits persist to the dev DB; `list_finished` is a
# *global* query (admin sees every marked anime), so assertions here are
# membership-based rather than asserting the whole list.


def _uuids(listing):
    return [a["uuid"] for a in listing.json()]


async def test_mark_and_list_finished(client, admin_auth_headers, completion_anime):
    uuid = str(completion_anime.uuid)
    mark = await client.post(f"/admin/finished-anime/{uuid}", headers=admin_auth_headers)
    assert mark.status_code == 204

    listing = await client.get("/admin/finished-anime", headers=admin_auth_headers)
    assert listing.status_code == 200
    assert uuid in _uuids(listing)
    # The item carries the audit fields the Completion tab renders
    item = next(a for a in listing.json() if a["uuid"] == uuid)
    assert item["title"] == "Completion Test Anime"
    assert item["marked_by_username"] is not None
    assert item["marked_at"] is not None

    detail = await client.get(f"/media/anime/{uuid}", headers=admin_auth_headers)
    assert detail.json()["is_finished"] is True


async def test_mark_is_idempotent(client, admin_auth_headers, completion_anime):
    uuid = str(completion_anime.uuid)
    await client.post(f"/admin/finished-anime/{uuid}", headers=admin_auth_headers)
    await client.post(f"/admin/finished-anime/{uuid}", headers=admin_auth_headers)
    listing = await client.get("/admin/finished-anime", headers=admin_auth_headers)
    assert _uuids(listing).count(uuid) == 1


async def test_unmark_finished(client, admin_auth_headers, completion_anime):
    uuid = str(completion_anime.uuid)
    await client.post(f"/admin/finished-anime/{uuid}", headers=admin_auth_headers)
    unmark = await client.delete(f"/admin/finished-anime/{uuid}", headers=admin_auth_headers)
    assert unmark.status_code == 204

    listing = await client.get("/admin/finished-anime", headers=admin_auth_headers)
    assert uuid not in _uuids(listing)
    detail = await client.get(f"/media/anime/{uuid}", headers=admin_auth_headers)
    assert detail.json()["is_finished"] is False


async def test_mark_requires_admin(client, user_auth_headers, completion_anime):
    resp = await client.post(
        f"/admin/finished-anime/{completion_anime.uuid}", headers=user_auth_headers
    )
    assert resp.status_code == 403


async def test_mark_unknown_anime_404(client, admin_auth_headers):
    resp = await client.post(
        "/admin/finished-anime/00000000-0000-0000-0000-000000000000", headers=admin_auth_headers
    )
    assert resp.status_code == 404
