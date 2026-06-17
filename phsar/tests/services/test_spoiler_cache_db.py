"""DB-backed tests for the scoped spoiler-cache recompute.

`test_spoiler_service.py` covers the pure frontier function; these pin the
DB wiring of `refresh_spoiler_cache_for_anime_ids`: it touches only the
named anime and skips restricted users.
"""

import pytest

from app.models.anime import Anime
from app.models.media import Media
from app.models.user_visible_media import UserVisibleMedia
from app.models.users import RoleType, Users
from app.services.spoiler_service import (
    get_visible_media_ids,
    refresh_spoiler_cache_for_anime_ids,
)
from tests._helpers import media_kwargs


async def _anime_with_two_mains(db, anime_mal: int, m1_mal: int, m2_mal: int) -> Anime:
    anime = Anime(mal_id=anime_mal, title=f"A{anime_mal}")
    db.add(anime)
    await db.flush()
    db.add(Media(**media_kwargs(anime.id, m1_mal, title="S1")))
    db.add(Media(**media_kwargs(anime.id, m2_mal, title="S2")))
    await db.flush()
    return anime


@pytest.fixture
async def two_users(db_session):
    normal = Users(username="sc_normal", hashed_password="x", role=RoleType.User)
    restricted = Users(
        username="sc_guest", hashed_password="x", role=RoleType.RestrictedUser,
    )
    db_session.add_all([normal, restricted])
    await db_session.flush()
    return normal, restricted


async def test_scoped_recompute_only_touches_named_anime(db_session, two_users):
    normal, _ = two_users
    a = await _anime_with_two_mains(db_session, -50001, -50011, -50012)
    b = await _anime_with_two_mains(db_session, -50002, -50021, -50022)

    await refresh_spoiler_cache_for_anime_ids(db_session, [a.id])

    # No ratings → only the first anchor (lowest mal_id main) of A is visible,
    # and B was never computed (out of scope).
    visible = await get_visible_media_ids(db_session, normal.id)
    a_media = {m.id async for m in _media_of(db_session, a.id)}
    b_media = {m.id async for m in _media_of(db_session, b.id)}
    assert visible & a_media  # A computed
    assert not (visible & b_media)  # B untouched


async def test_scoped_recompute_leaves_other_anime_rows_intact(db_session, two_users):
    normal, _ = two_users
    a = await _anime_with_two_mains(db_session, -50101, -50111, -50112)
    b = await _anime_with_two_mains(db_session, -50102, -50121, -50122)

    # Seed a pre-existing visibility row for B; recomputing A must not delete it.
    b_first = await _first_media_id(db_session, b.id)
    db_session.add(UserVisibleMedia(user_id=normal.id, media_id=b_first))
    await db_session.flush()

    await refresh_spoiler_cache_for_anime_ids(db_session, [a.id])

    visible = await get_visible_media_ids(db_session, normal.id)
    assert b_first in visible  # B's row survived the scoped A recompute


async def test_scoped_recompute_skips_restricted_users(db_session, two_users):
    _, restricted = two_users
    a = await _anime_with_two_mains(db_session, -50201, -50211, -50212)

    await refresh_spoiler_cache_for_anime_ids(db_session, [a.id])

    # Restricted users are excluded from the recompute query entirely.
    assert await get_visible_media_ids(db_session, restricted.id) == set()


async def test_scoped_recompute_empty_ids_is_noop(db_session, two_users):
    normal, _ = two_users
    await refresh_spoiler_cache_for_anime_ids(db_session, [])
    assert await get_visible_media_ids(db_session, normal.id) == set()


async def test_purge_restricted_user_cache_removes_only_guest_rows(db_session, two_users):
    """Startup purge deletes a restricted user's stale cache rows (created
    before they were excluded) but leaves normal users' rows intact."""
    from app.seeders.user_seeder import purge_restricted_user_spoiler_cache

    normal, restricted = two_users
    a = await _anime_with_two_mains(db_session, -50301, -50311, -50312)
    media_ids = [m.id async for m in _media_of(db_session, a.id)]
    # Seed cache rows for both users directly (simulating pre-v0.14.7 state).
    for mid in media_ids:
        db_session.add(UserVisibleMedia(user_id=normal.id, media_id=mid))
        db_session.add(UserVisibleMedia(user_id=restricted.id, media_id=mid))
    await db_session.flush()

    await purge_restricted_user_spoiler_cache(db_session)

    assert await get_visible_media_ids(db_session, restricted.id) == set()
    assert await get_visible_media_ids(db_session, normal.id) == set(media_ids)


async def test_purge_resets_legacy_restricted_spoiler_level_to_off(db_session, two_users):
    """A user demoted to restricted while holding `hide` keeps that value
    (the update path only blocks new changes); the startup purge resets it to
    off so the empty-cache hide-read can't blank their catalogue. A normal
    user's non-off value is left untouched."""
    from app.models.user_settings import SpoilerLevel, UserSettings
    from app.seeders.user_seeder import purge_restricted_user_spoiler_cache

    normal, restricted = two_users
    db_session.add(UserSettings(user_id=restricted.id, spoiler_level=SpoilerLevel.hide))
    db_session.add(UserSettings(user_id=normal.id, spoiler_level=SpoilerLevel.hide))
    await db_session.flush()

    await purge_restricted_user_spoiler_cache(db_session)

    from sqlalchemy import select
    rows = {
        r.user_id: r.spoiler_level
        for r in (await db_session.execute(select(UserSettings))).scalars().all()
    }
    assert rows[restricted.id] == SpoilerLevel.off
    assert rows[normal.id] == SpoilerLevel.hide


# --- helpers -------------------------------------------------------------

async def _media_of(db, anime_id: int):
    from sqlalchemy import select
    result = await db.execute(select(Media).where(Media.anime_id == anime_id))
    for m in result.scalars().all():
        yield m


async def _first_media_id(db, anime_id: int) -> int:
    from sqlalchemy import select
    result = await db.execute(
        select(Media.id).where(Media.anime_id == anime_id).order_by(Media.mal_id)
    )
    return result.scalars().first()
