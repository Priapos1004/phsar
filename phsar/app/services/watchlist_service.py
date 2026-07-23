import logging
from uuid import UUID

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
    """Create or update the user's watchlist entry for a media (one per user+media)."""
    media = (await media_service.resolve_media_uuids(db, [media_uuid]))[0]
    tag = await _resolve_tag(db, user_id, data.tag_uuid)

    existing = await watchlist_dao.get_by_user_and_media(db, user_id, media.id)
    if existing:
        _apply_fields(existing, data, tag.id)
        entry_uuid = existing.uuid
    else:
        entry = _new_entry(user_id, media.id, tag.id, data)
        await watchlist_dao.create(db, entry)  # flush → uuid
        entry_uuid = entry.uuid

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


async def bulk_upsert_watchlist(
    db: AsyncSession, user_id: int, data: WatchlistBulkCreate
) -> list[WatchlistOut]:
    """Add/update watchlist entries for multiple media at once. Priority + tag apply to
    every selected media; the note goes on the chronologically-FIRST 'main' media only
    (by the shared `chronological_media_key`), falling back to the first media overall if
    none are main. The mirror of bulk rating, which places its note on the *last* main —
    a watchlist note ("start here / heads up") belongs on the earliest season, a rating
    note ("my take") on the latest. Ordered by intrinsic media order, so it's invariant to
    request/click order. Every other entry has its note cleared to None."""
    media_list = await media_service.resolve_media_uuids(db, data.media_uuids)
    tag = await _resolve_tag(db, user_id, data.tag_uuid)

    existing = await watchlist_dao.get_by_user_and_media_ids(db, user_id, [m.id for m in media_list])
    existing_by_media = {e.media_id: e for e in existing}

    # Note target: the chronologically-FIRST main media (bulk rating uses the last).
    note_index = select_note_target_index(media_list, latest=False)

    entries_in_order: list[Watchlist] = []
    for i, media in enumerate(media_list):
        entry = existing_by_media.get(media.id)
        if entry:
            _apply_fields(entry, data, tag.id)
        else:
            entry = _new_entry(user_id, media.id, tag.id, data)
            db.add(entry)
        # _apply_fields set note = data.note; override so only the first main keeps it.
        entry.note = data.note if i == note_index else None
        entries_in_order.append(entry)

    # One flush for the whole batch (uuid is a Python-side default, populated on flush);
    # no per-entry flush is needed since nothing consumes the id mid-loop (unlike ratings).
    await db.flush()
    uuids_in_order = [e.uuid for e in entries_in_order]
    await db.commit()

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
