"""Tag service — the v0.15.0 watchlist tag layer.

Pins the confirmed design decisions: an immutable per-user default tag (always
present, never renamable/recolorable/deletable but empty-able), unique tag
names, a per-user cap, and delete-with-reassign vs delete-with-cascade.
"""

import pytest

from app.exceptions import (
    DefaultTagImmutableError,
    DuplicateTagNameError,
    TagLimitError,
    TagNotFoundError,
)
from app.models.anime import Anime
from app.models.media import Media
from app.models.watchlist import Watchlist
from app.schemas.tag_schema import TagCreate, TagUpdate
from app.services import tag_service
from tests._helpers import make_user, media_kwargs


# Seeds are NEGATIVE so they can't collide with the dev DB's real catalog on the
# globally-unique mal_id (real MAL ids are positive) — the suite-wide convention.
async def _make_media(db, mal_seed: int, count: int = 1) -> list[Media]:
    anime = Anime(mal_id=mal_seed, title=f"A{mal_seed}")
    db.add(anime)
    await db.flush()
    media = [Media(**media_kwargs(anime.id, mal_seed + i + 1)) for i in range(count)]
    db.add_all(media)
    await db.flush()
    return media


async def _watchlist(db, user_id: int, tag_id: int, media: list[Media]) -> None:
    db.add_all([
        Watchlist(user_id=user_id, media_id=m.id, tag_id=tag_id, priority=3) for m in media
    ])
    await db.flush()


async def _tag_id(db, tag_out, user_id: int) -> int:
    """Resolve a TagOut's DB id (TagOut carries the uuid, not the int PK)."""
    return (await tag_service.tag_dao.get_by_uuid_and_user(db, tag_out.uuid, user_id)).id


# --- Default tag ---

async def test_create_default_tag_idempotent(db_session):
    user = await make_user(db_session)
    first = await tag_service.create_default_tag(db_session, user.id)
    second = await tag_service.create_default_tag(db_session, user.id)

    assert first.id == second.id
    assert first.is_default is True
    assert first.name == tag_service.DEFAULT_TAG_NAME
    assert first.color == tag_service.DEFAULT_TAG_COLOR


async def test_update_default_tag_blocked(db_session):
    user = await make_user(db_session)
    default = await tag_service.create_default_tag(db_session, user.id)

    with pytest.raises(DefaultTagImmutableError):
        await tag_service.update_tag(db_session, user.id, default.uuid, TagUpdate(name="Renamed"))


async def test_delete_default_tag_blocked(db_session):
    user = await make_user(db_session)
    default = await tag_service.create_default_tag(db_session, user.id)

    with pytest.raises(DefaultTagImmutableError):
        await tag_service.delete_tag(db_session, user.id, default.uuid, reassign_entries=False)


async def test_empty_default_tag_keeps_tag(db_session):
    """The default tag can't be deleted, but it CAN be emptied — its only bulk clear."""
    user = await make_user(db_session)
    default = await tag_service.create_default_tag(db_session, user.id)
    media = await _make_media(db_session, -70100, count=2)
    await _watchlist(db_session, user.id, default.id, media)

    removed = await tag_service.empty_tag(db_session, user.id, default.uuid)

    assert removed == 2
    assert await tag_service.tag_dao.get_default_for_user(db_session, user.id) is not None


# --- Create / list ---

async def test_create_tag_and_list_counts(db_session):
    user = await make_user(db_session)
    await tag_service.create_default_tag(db_session, user.id)
    custom = await tag_service.create_tag(db_session, user.id, TagCreate(name="Films", color="#123ABC"))

    # Two media under one anime + one under another → 3 entries, 2 anime.
    a1 = await _make_media(db_session, -70200, count=2)
    a2 = await _make_media(db_session, -70300, count=1)
    await _watchlist(db_session, user.id, await _tag_id(db_session, custom, user.id), a1 + a2)

    tags = await tag_service.list_tags(db_session, user.id)

    # Default first, then alphabetical.
    assert [t.name for t in tags] == [tag_service.DEFAULT_TAG_NAME, "Films"]
    films = tags[1]
    assert films.color == "#123abc"  # normalized lowercase
    assert films.entry_count == 3
    assert films.anime_count == 2


async def test_create_tag_duplicate_name(db_session):
    user = await make_user(db_session)
    await tag_service.create_tag(db_session, user.id, TagCreate(name="Dup", color="#000000"))
    with pytest.raises(DuplicateTagNameError):
        await tag_service.create_tag(db_session, user.id, TagCreate(name="Dup", color="#111111"))


async def test_create_tag_limit(db_session, monkeypatch):
    user = await make_user(db_session)
    await tag_service.create_default_tag(db_session, user.id)  # counts toward the cap
    monkeypatch.setattr(tag_service, "TAGS_PER_USER_LIMIT", 2)

    await tag_service.create_tag(db_session, user.id, TagCreate(name="One", color="#000000"))
    with pytest.raises(TagLimitError):
        await tag_service.create_tag(db_session, user.id, TagCreate(name="Two", color="#000000"))


# --- Update ---

async def test_update_tag_rename_recolor(db_session):
    user = await make_user(db_session)
    tag = await tag_service.create_tag(db_session, user.id, TagCreate(name="Old", color="#000000"))
    updated = await tag_service.update_tag(
        db_session, user.id, tag.uuid, TagUpdate(name="New", color="#ABCDEF")
    )
    assert updated.name == "New"
    assert updated.color == "#abcdef"


async def test_update_tag_duplicate_name(db_session):
    user = await make_user(db_session)
    await tag_service.create_tag(db_session, user.id, TagCreate(name="Taken", color="#000000"))
    other = await tag_service.create_tag(db_session, user.id, TagCreate(name="Other", color="#000000"))
    with pytest.raises(DuplicateTagNameError):
        await tag_service.update_tag(db_session, user.id, other.uuid, TagUpdate(name="Taken"))


async def test_update_tag_not_found(db_session):
    user = await make_user(db_session)
    import uuid as uuidlib
    with pytest.raises(TagNotFoundError):
        await tag_service.update_tag(db_session, user.id, uuidlib.uuid4(), TagUpdate(name="X"))


# --- Delete: reassign vs cascade ---

async def test_delete_tag_cascade_removes_entries(db_session):
    user = await make_user(db_session)
    await tag_service.create_default_tag(db_session, user.id)
    tag = await tag_service.create_tag(db_session, user.id, TagCreate(name="Temp", color="#000000"))
    media = await _make_media(db_session, -70400, count=2)
    await _watchlist(db_session, user.id, await _tag_id(db_session, tag, user.id), media)

    affected = await tag_service.delete_tag(db_session, user.id, tag.uuid, reassign_entries=False)

    assert affected == 2
    remaining = await tag_service.watchlist_dao.counts_by_tag(db_session, user.id)
    assert remaining == {}  # entries gone, no default entries either


async def test_delete_tag_reassign_moves_entries_to_default(db_session):
    user = await make_user(db_session)
    default = await tag_service.create_default_tag(db_session, user.id)
    tag = await tag_service.create_tag(db_session, user.id, TagCreate(name="Temp", color="#000000"))
    media = await _make_media(db_session, -70500, count=2)
    await _watchlist(db_session, user.id, await _tag_id(db_session, tag, user.id), media)

    affected = await tag_service.delete_tag(db_session, user.id, tag.uuid, reassign_entries=True)

    assert affected == 2
    counts = await tag_service.watchlist_dao.counts_by_tag(db_session, user.id)
    # All entries now sit under the default tag.
    assert counts == {default.id: (2, 1)}
