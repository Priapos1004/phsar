"""Watchlist service — the v0.15.0 entry layer.

Pins: one entry per (user, media); tag + priority required; bulk note lands on the
chronologically-first main media only (the mirror of bulk rating's last-main note);
bulk delete; the wide items projection; the media-tags icon set (carries the tag
color); and that a watchlist write never touches the spoiler cache.
"""

import uuid as uuidlib

import pytest

from app.exceptions import MediaNotFoundError, TagNotFoundError, WatchlistNotFoundError
from app.models.anime import Anime
from app.models.media import Media, RelationType, SeasonType
from app.models.user_visible_media import UserVisibleMedia
from app.schemas.tag_schema import TagCreate
from app.schemas.watchlist_schema import WatchlistBulkCreate, WatchlistCreate
from app.services import tag_service, watchlist_service
from tests._helpers import make_user, media_kwargs


async def _watchlisted_uuids(db, user_id) -> set:
    res = await watchlist_service.get_watchlisted_media_tags(db, user_id)
    return {e.media_uuid for e in res.entries}


async def _setup(db, media_count=1, mal_seed=-80000):
    """A user with their default tag + one anime with `media_count` media.

    Negative mal_seed so fixtures can't collide with the dev DB's real catalog on
    the globally-unique mal_id (the suite-wide convention)."""
    user = await make_user(db)
    default = await tag_service.create_default_tag(db, user.id)
    anime = Anime(mal_id=mal_seed, title=f"A{mal_seed}")
    db.add(anime)
    await db.flush()
    media = [Media(**media_kwargs(anime.id, mal_seed + i + 1)) for i in range(media_count)]
    db.add_all(media)
    await db.flush()
    return user, default, media


# --- Single upsert ---

async def test_upsert_creates_entry(db_session):
    user, default, media = await _setup(db_session)
    out = await watchlist_service.upsert_watchlist(
        db_session, user.id, media[0].uuid,
        WatchlistCreate(tag_uuid=default.uuid, priority=1, note="soon"),
    )
    assert out.priority == 1
    assert out.note == "soon"
    assert out.tag.uuid == default.uuid
    assert out.media_uuid == media[0].uuid


async def test_upsert_updates_in_place(db_session):
    user, default, media = await _setup(db_session)
    custom = await tag_service.create_tag(
        db_session, user.id, TagCreate(name="Films", color="#000000"),
    )
    await watchlist_service.upsert_watchlist(
        db_session, user.id, media[0].uuid, WatchlistCreate(tag_uuid=default.uuid, priority=3),
    )
    updated = await watchlist_service.upsert_watchlist(
        db_session, user.id, media[0].uuid,
        WatchlistCreate(tag_uuid=custom.uuid, priority=1, note="moved"),
    )
    # Still one entry (upsert, not insert), with the new values.
    assert updated.priority == 1
    assert updated.note == "moved"
    assert updated.tag.uuid == custom.uuid
    assert await _watchlisted_uuids(db_session, user.id) == {media[0].uuid}


async def test_upsert_defaults_priority_to_3(db_session):
    user, default, media = await _setup(db_session)
    out = await watchlist_service.upsert_watchlist(
        db_session, user.id, media[0].uuid, WatchlistCreate(tag_uuid=default.uuid),
    )
    assert out.priority == 3


async def test_media_tags_carry_tag_color(db_session):
    """The icon-state set carries the entry's tag (uuid/name/color) so the bookmark
    can render in the tag's color everywhere."""
    user, _default, media = await _setup(db_session)
    custom = await tag_service.create_tag(db_session, user.id, TagCreate(name="Films", color="#123ABC"))
    await watchlist_service.upsert_watchlist(
        db_session, user.id, media[0].uuid, WatchlistCreate(tag_uuid=custom.uuid),
    )
    res = await watchlist_service.get_watchlisted_media_tags(db_session, user.id)
    assert len(res.entries) == 1
    entry = res.entries[0]
    assert entry.media_uuid == media[0].uuid
    assert entry.anime_uuid == media[0].anime.uuid
    assert entry.tag_uuid == custom.uuid
    assert entry.tag_name == "Films"
    assert entry.tag_color == "#123abc"


async def test_upsert_unknown_tag_raises(db_session):
    user, _default, media = await _setup(db_session)
    with pytest.raises(TagNotFoundError):
        await watchlist_service.upsert_watchlist(
            db_session, user.id, media[0].uuid, WatchlistCreate(tag_uuid=uuidlib.uuid4()),
        )


async def test_upsert_unknown_media_raises(db_session):
    user, default, _media = await _setup(db_session)
    with pytest.raises(MediaNotFoundError):
        await watchlist_service.upsert_watchlist(
            db_session, user.id, uuidlib.uuid4(), WatchlistCreate(tag_uuid=default.uuid),
        )


async def test_upsert_does_not_touch_spoiler_cache(db_session):
    """A watchlist entry is 'want to watch', not 'watched' — neither the single nor
    the bulk write may create spoiler-visibility rows (guards a future maintainer who
    copies recompute_visibility_for_anime in from rating_service)."""
    user, default, media = await _setup(db_session, media_count=2)
    await watchlist_service.upsert_watchlist(
        db_session, user.id, media[0].uuid, WatchlistCreate(tag_uuid=default.uuid),
    )
    await watchlist_service.bulk_upsert_watchlist(
        db_session, user.id,
        WatchlistBulkCreate(media_uuids=[m.uuid for m in media], tag_uuid=default.uuid),
    )

    rows = (await db_session.execute(
        UserVisibleMedia.__table__.select().where(UserVisibleMedia.user_id == user.id)
    )).all()
    assert rows == []


# --- Delete / get ---

async def test_delete_watchlist(db_session):
    user, default, media = await _setup(db_session)
    await watchlist_service.upsert_watchlist(
        db_session, user.id, media[0].uuid, WatchlistCreate(tag_uuid=default.uuid),
    )
    await watchlist_service.delete_watchlist(db_session, user.id, media[0].uuid)
    assert await _watchlisted_uuids(db_session, user.id) == set()


async def test_delete_absent_raises(db_session):
    user, _default, media = await _setup(db_session)
    with pytest.raises(WatchlistNotFoundError):
        await watchlist_service.delete_watchlist(db_session, user.id, media[0].uuid)


async def test_get_for_anime(db_session):
    user, default, media = await _setup(db_session, media_count=2)
    for m in media:
        await watchlist_service.upsert_watchlist(
            db_session, user.id, m.uuid, WatchlistCreate(tag_uuid=default.uuid),
        )
    anime_uuid = media[0].anime.uuid
    entries = await watchlist_service.get_watchlist_for_anime(db_session, user.id, anime_uuid)
    assert len(entries) == 2


# --- Bulk ---

async def test_bulk_upsert_note_on_first_main_invariant_to_order(db_session):
    """Bulk note lands on the chronologically-FIRST main media (mirror of bulk rating's
    last-main), invariant to request order; priority still applies to every entry, and
    every non-target entry's note is cleared."""
    user = await make_user(db_session)
    default = await tag_service.create_default_tag(db_session, user.id)
    anime = Anime(mal_id=-80100, title="A-80100")
    db_session.add(anime)
    await db_session.flush()

    # winner = the earliest-season main; a later main + an earlier-season side story
    # (which must NOT win — it isn't main) bracket it.
    winner = Media(**media_kwargs(
        anime.id, -80101, title="Earliest Main",
        relation_type=RelationType.Main,
        anime_season_name=SeasonType.Winter, anime_season_year=2020,
    ))
    later_main = Media(**media_kwargs(
        anime.id, -80102, title="Later Main",
        relation_type=RelationType.Main,
        anime_season_name=SeasonType.Spring, anime_season_year=2022,
    ))
    earlier_side = Media(**media_kwargs(
        anime.id, -80103, title="Earlier Side Story",
        relation_type=RelationType.SideStory,
        anime_season_name=SeasonType.Fall, anime_season_year=2019,
    ))
    db_session.add_all([winner, later_main, earlier_side])
    await db_session.flush()

    # Scramble the order so the target can't coincide with "first submitted".
    submit = [later_main, earlier_side, winner]
    out = await watchlist_service.bulk_upsert_watchlist(
        db_session, user.id,
        WatchlistBulkCreate(
            media_uuids=[m.uuid for m in submit], tag_uuid=default.uuid, priority=2, note="start here",
        ),
    )
    assert len(out) == 3
    assert all(o.priority == 2 for o in out)  # priority applies to all
    by_uuid = {o.media_uuid: o for o in out}
    assert by_uuid[winner.uuid].note == "start here"
    assert by_uuid[later_main.uuid].note is None
    assert by_uuid[earlier_side.uuid].note is None


async def test_bulk_upsert_dedupes_duplicate_media(db_session):
    """A media_uuid repeated within one bulk request yields a single entry, not a
    unique_user_media violation (the schema validator counts length, it doesn't de-dupe)."""
    user, default, media = await _setup(db_session)
    out = await watchlist_service.bulk_upsert_watchlist(
        db_session, user.id,
        WatchlistBulkCreate(
            media_uuids=[media[0].uuid, media[0].uuid], tag_uuid=default.uuid, priority=2,
        ),
    )
    assert len(out) == 1
    assert out[0].media_uuid == media[0].uuid
    assert await _watchlisted_uuids(db_session, user.id) == {media[0].uuid}
    # NOTE: the cross-request concurrent-insert recovery branch (rollback → re-apply as
    # update) isn't unit-tested — the single-session fixture joins one transaction, so a
    # service-level rollback unwinds the whole test. Same limitation leaves tag_service's
    # _commit_or_raise_duplicate IntegrityError backstop untested; both are verified by review.


async def test_bulk_upsert_updates_existing(db_session):
    user, default, media = await _setup(db_session, media_count=2)
    await watchlist_service.upsert_watchlist(
        db_session, user.id, media[0].uuid, WatchlistCreate(tag_uuid=default.uuid, priority=1),
    )
    out = await watchlist_service.bulk_upsert_watchlist(
        db_session, user.id,
        WatchlistBulkCreate(media_uuids=[m.uuid for m in media], tag_uuid=default.uuid, priority=3),
    )
    assert len(out) == 2
    assert all(o.priority == 3 for o in out)  # existing one updated too
    assert await _watchlisted_uuids(db_session, user.id) == {m.uuid for m in media}


async def test_bulk_delete(db_session):
    user, default, media = await _setup(db_session, media_count=3)
    await watchlist_service.bulk_upsert_watchlist(
        db_session, user.id,
        WatchlistBulkCreate(media_uuids=[m.uuid for m in media], tag_uuid=default.uuid),
    )
    removed = await watchlist_service.bulk_delete_watchlist(
        db_session, user.id, [media[0].uuid, media[1].uuid],
    )
    assert removed == 2
    assert await _watchlisted_uuids(db_session, user.id) == {media[2].uuid}


# --- Items projection ---

async def test_get_items_projection(db_session):
    user, default, media = await _setup(db_session)
    await watchlist_service.upsert_watchlist(
        db_session, user.id, media[0].uuid,
        WatchlistCreate(tag_uuid=default.uuid, priority=2, note="n"),
    )
    items = await watchlist_service.get_watchlist_items(db_session, user.id)
    assert len(items) == 1
    item = items[0]
    assert item.media_uuid == media[0].uuid
    assert item.priority == 2
    assert item.note == "n"
    assert item.tag_uuid == default.uuid
    assert item.tag_name == tag_service.DEFAULT_TAG_NAME
    assert item.tag_color == tag_service.DEFAULT_TAG_COLOR
    assert item.mal_id == media[0].mal_id
    # The projection aggregates genres/studios with array_agg, which yields SQL
    # NULL — not an empty array — for a media with none. The DTO must normalize
    # that to [], or the Statistics subtab's tallies get a null in the list.
    assert item.genres == []
    assert item.studios == []
    # Media and Anime both have uuid/title/name_eng/name_jap/cover_image, so an
    # unlabelled column in the flat projection would silently collapse the pair.
    # Pin that the two grains stayed distinct.
    assert item.anime_uuid != item.media_uuid
    assert item.media_title == media[0].title


async def test_get_items_order_is_deterministic_under_modified_at_ties(db_session):
    """A bulk add stamps ONE modified_at across every selected media, so the
    overview's `ORDER BY modified_at DESC` ties across the whole batch. The
    consumer treats the incoming order as meaningful (it breaks its own full ties
    by relying on it), so the query needs a tiebreak — otherwise the same request
    can return tied rows in a different order on each call and the grid reshuffles
    under the user for no reason.

    Asserting repeat calls agree, rather than asserting one specific order, is
    the point: the property that matters is stability, and a hardcoded order
    would pass even with a nondeterministic query on a small enough fixture.
    """
    user, default, media = await _setup(db_session, media_count=6, mal_seed=-80600)
    await watchlist_service.bulk_upsert_watchlist(
        db_session, user.id,
        WatchlistBulkCreate(
            media_uuids=[m.uuid for m in media], tag_uuid=default.uuid, priority=2,
        ),
    )

    runs = [
        [i.media_uuid for i in await watchlist_service.get_watchlist_items(db_session, user.id)]
        for _ in range(4)
    ]
    assert len(runs[0]) == 6
    # All six share one modified_at, so this is entirely the tiebreak's doing.
    stamps = {
        i.modified_at
        for i in await watchlist_service.get_watchlist_items(db_session, user.id)
    }
    assert len(stamps) == 1, f"fixture no longer ties on modified_at: {stamps}"
    assert all(r == runs[0] for r in runs[1:]), f"order varied between calls: {runs}"
