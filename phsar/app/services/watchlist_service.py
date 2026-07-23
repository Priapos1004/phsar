import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.tag_dao import TagDAO
from app.daos.watchlist_dao import WatchlistDAO
from app.exceptions import TagNotFoundError, WatchlistNotFoundError
from app.models.tag import Tag
from app.models.watchlist import Watchlist
from app.schemas.watchlist_schema import (
    TagMini,
    WatchlistBulkCreate,
    WatchlistCreate,
    WatchlistItem,
    WatchlistMediaTag,
    WatchlistMediaTags,
    WatchlistOut,
)
from app.services import media_service
from app.services.filter_service import select_note_target_index

logger = logging.getLogger(__name__)

watchlist_dao = WatchlistDAO()
tag_dao = TagDAO()

# NOTE: unlike rating_service, nothing here recomputes the spoiler frontier — a
# watchlist entry is "want to watch", not "watched", so it must not affect
# spoiler visibility. (Regression-pinned in test_watchlist_service.)


def _to_out(w: Watchlist) -> WatchlistOut:
    return WatchlistOut(
        uuid=w.uuid,
        priority=w.priority,
        note=w.note,
        tag=TagMini.model_validate(w.tag),
        media_uuid=w.media.uuid,
        media_title=w.media.title,
        media_cover_image=w.media.cover_image,
        anime_uuid=w.media.anime.uuid,
        anime_title=w.media.anime.title,
        created_at=w.created_at,
        modified_at=w.modified_at,
    )


def _to_item(w: Watchlist) -> WatchlistItem:
    # Requires the WIDE loader: reads m.media_genre/media_studio (both lazy="raise"), which
    # only WatchlistDAO.get_all_for_items eager-loads — the lighter lookup loaders would
    # MissingGreenlet-crash here. Its sole caller (get_watchlist_items) uses that loader.
    m = w.media
    a = m.anime
    return WatchlistItem(
        uuid=w.uuid,
        media_uuid=m.uuid,
        anime_uuid=a.uuid,
        media_title=m.title,
        media_name_eng=m.name_eng,
        media_name_jap=m.name_jap,
        anime_title=a.title,
        anime_name_eng=a.name_eng,
        anime_name_jap=a.name_jap,
        media_cover_image=m.cover_image,
        anime_cover_image=a.cover_image,
        priority=w.priority,
        note=w.note,
        tag_uuid=w.tag.uuid,
        tag_name=w.tag.name,
        tag_color=w.tag.color,
        relation_type=m.relation_type.value,
        anime_season_name=m.anime_season_name.value if m.anime_season_name else None,
        anime_season_year=m.anime_season_year,
        mal_id=m.mal_id,
        genres=[mg.genre.name for mg in m.media_genre],
        studios=[ms.studio.name for ms in m.media_studio],
        episodes=m.episodes,
        duration_seconds=m.duration_seconds,
        created_at=w.created_at,
        modified_at=w.modified_at,
    )


async def _resolve_tag(db: AsyncSession, user_id: int, tag_uuid: UUID) -> Tag:
    tag = await tag_dao.get_by_uuid_and_user(db, tag_uuid, user_id)
    if not tag:
        raise TagNotFoundError(str(tag_uuid))
    return tag


def _apply_fields(entry: Watchlist, data: WatchlistCreate | WatchlistBulkCreate, tag_id: int) -> None:
    """The single site that maps request fields onto an entry — used by both the
    create and update paths so a new field can't be wired into one and not the other."""
    entry.priority = data.priority
    entry.note = data.note
    entry.tag_id = tag_id


def _new_entry(user_id: int, media_id: int, tag_id: int, data: WatchlistCreate | WatchlistBulkCreate) -> Watchlist:
    entry = Watchlist(user_id=user_id, media_id=media_id)
    _apply_fields(entry, data, tag_id)
    return entry


async def upsert_watchlist(
    db: AsyncSession, user_id: int, media_uuid: UUID, data: WatchlistCreate
) -> WatchlistOut:
    """Create or update the user's watchlist entry for a media (one per user+media).

    Idempotent under a concurrent add (same media from two tabs / a client retry): the
    loser of the unique_user_media race rolls back and re-applies its fields as an update
    instead of surfacing a raw IntegrityError as a 500 — mirrors tag_service's backstop.
    """
    media = (await media_service.resolve_media_uuids(db, [media_uuid]))[0]
    tag = await _resolve_tag(db, user_id, data.tag_uuid)
    # Capture ids as plain values now: a rollback below expires ORM attrs, and re-reading
    # media.id/tag.id afterwards would trigger a lazy refresh that raises in async context.
    media_id, tag_id = media.id, tag.id

    existing = await watchlist_dao.get_by_user_and_media(db, user_id, media_id)
    if existing:
        _apply_fields(existing, data, tag_id)
        entry_uuid = existing.uuid
        await db.commit()
    else:
        try:
            # create() flushes the INSERT, so a competing write that already committed
            # the same (user, media) surfaces the unique violation here, not at commit.
            entry = _new_entry(user_id, media_id, tag_id, data)
            await watchlist_dao.create(db, entry)  # flush → uuid
            entry_uuid = entry.uuid
            await db.commit()
        except IntegrityError as e:
            await db.rollback()
            if "unique_user_media_watchlist" not in str(e.orig):
                raise
            # Lost the race — the row now exists; apply our fields as an update.
            existing = await watchlist_dao.get_by_user_and_media(db, user_id, media_id)
            _apply_fields(existing, data, tag_id)
            entry_uuid = existing.uuid
            await db.commit()

    fresh = await watchlist_dao.get_by_uuid_and_user(db, entry_uuid, user_id)
    return _to_out(fresh)


async def get_watchlist_for_media(db: AsyncSession, user_id: int, media_uuid: UUID) -> WatchlistOut:
    entry = await watchlist_dao.get_by_media_uuid_and_user(db, media_uuid, user_id)
    if not entry:
        raise WatchlistNotFoundError(str(media_uuid))
    return _to_out(entry)


async def get_watchlist_for_anime(db: AsyncSession, user_id: int, anime_uuid: UUID) -> list[WatchlistOut]:
    entries = await watchlist_dao.get_by_user_and_anime_uuid(db, user_id, anime_uuid)
    return [_to_out(e) for e in entries]


async def delete_watchlist(db: AsyncSession, user_id: int, media_uuid: UUID) -> None:
    """Remove the user's watchlist entry for a media. Keyed on media_uuid (not the
    entry uuid) so the media-page bookmark toggle can call it with what it has."""
    media = (await media_service.resolve_media_uuids(db, [media_uuid]))[0]
    entry = await watchlist_dao.get_by_user_and_media(db, user_id, media.id)
    if not entry:
        raise WatchlistNotFoundError(str(media_uuid))
    await watchlist_dao.delete(db, entry)
    await db.commit()


async def _bulk_write(
    db: AsyncSession, user_id: int, media_ids: list[int], tag_id: int,
    note_index: int, data: WatchlistBulkCreate,
) -> list[UUID]:
    """One batch upsert pass over media_ids, committing. Drives off plain ints (not ORM
    Media objects) so it's safe to re-run after a rollback, whose expired attrs would
    otherwise raise on access. Returns the entry uuids in media_ids order."""
    existing = await watchlist_dao.get_by_user_and_media_ids(db, user_id, media_ids)
    existing_by_media = {e.media_id: e for e in existing}

    entries_in_order: list[Watchlist] = []
    for i, media_id in enumerate(media_ids):
        entry = existing_by_media.get(media_id)
        if entry:
            _apply_fields(entry, data, tag_id)
        else:
            entry = _new_entry(user_id, media_id, tag_id, data)
            db.add(entry)
        # _apply_fields set note = data.note; override so only the first main keeps it.
        entry.note = data.note if i == note_index else None
        entries_in_order.append(entry)

    # One flush for the whole batch (uuid is a Python-side default, populated on flush);
    # capture the uuids before commit expires the attrs.
    await db.flush()
    uuids_in_order = [e.uuid for e in entries_in_order]
    await db.commit()
    return uuids_in_order


async def bulk_upsert_watchlist(
    db: AsyncSession, user_id: int, data: WatchlistBulkCreate
) -> list[WatchlistOut]:
    """Add/update watchlist entries for multiple media at once. Priority + tag apply to
    every selected media; the note goes on the chronologically-FIRST 'main' media only
    (by the shared `chronological_media_key`), falling back to the first media overall if
    none are main. The mirror of bulk rating, which places its note on the *last* main —
    a watchlist note ("start here / heads up") belongs on the earliest season, a rating
    note ("my take") on the latest. Ordered by intrinsic media order, so it's invariant to
    request/click order. Every other entry has its note cleared to None.

    Idempotent like the single upsert: a repeated media_uuid in one request is de-duped
    (else two rows for one (user, media) would trip the constraint), and if a competing
    write inserts one of these media between our read and flush, the batch rolls back and
    re-runs once as an all-update pass."""
    resolved = await media_service.resolve_media_uuids(db, data.media_uuids)
    tag = await _resolve_tag(db, user_id, data.tag_uuid)
    # De-dupe within the request by media id, preserving first-seen order (a repeated
    # media_uuid would otherwise add two rows for one (user, media) and trip the
    # constraint). media_ids is captured as plain ints so the retry path never reads an
    # ORM attr that a rollback expired.
    deduped_media = list({m.id: m for m in resolved}.values())
    media_ids = [m.id for m in deduped_media]

    # Note target: the chronologically-FIRST main media (bulk rating uses the last).
    note_index = select_note_target_index(deduped_media, latest=False)

    try:
        uuids_in_order = await _bulk_write(db, user_id, media_ids, tag.id, note_index, data)
    except IntegrityError as e:
        await db.rollback()
        if "unique_user_media_watchlist" not in str(e.orig):
            raise
        # Lost the create race on ≥1 media — every row now exists, so a re-run applies as
        # updates. A single retry bounds it; a second concurrent loss is negligibly rare.
        uuids_in_order = await _bulk_write(db, user_id, media_ids, tag.id, note_index, data)

    fresh = await watchlist_dao.get_by_uuids_and_user(db, uuids_in_order, user_id)
    by_uuid = {f.uuid: f for f in fresh}
    return [_to_out(by_uuid[u]) for u in uuids_in_order]


async def bulk_delete_watchlist(db: AsyncSession, user_id: int, media_uuids: list[UUID]) -> int:
    """Remove watchlist entries for multiple media at once (the anime-card remove-all).
    Returns the count removed; silently skips media not on the watchlist."""
    media_list = await media_service.resolve_media_uuids(db, media_uuids)
    count = await watchlist_dao.bulk_delete_by_user_and_media_ids(
        db, user_id, [m.id for m in media_list]
    )
    await db.commit()
    return count


async def get_watchlist_items(db: AsyncSession, user_id: int) -> list[WatchlistItem]:
    """The wide one-fetch projection backing the overview page (list + grid)."""
    entries = await watchlist_dao.get_all_for_items(db, user_id)
    return [_to_item(e) for e in entries]


async def get_watchlisted_media_tags(db: AsyncSession, user_id: int) -> WatchlistMediaTags:
    """The set of watchlisted media + their tags — drives the bookmark icon states
    (present/absent) AND the per-tag color the bookmark renders in."""
    rows = await watchlist_dao.get_watchlisted_media_tags(db, user_id)
    return WatchlistMediaTags(entries=[
        WatchlistMediaTag(
            media_uuid=media_uuid, anime_uuid=anime_uuid,
            tag_uuid=tag_uuid, tag_name=tag_name, tag_color=tag_color,
        )
        for (media_uuid, anime_uuid, tag_uuid, tag_name, tag_color) in rows
    ])
