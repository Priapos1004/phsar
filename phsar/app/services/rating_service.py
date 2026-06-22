import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.media_dao import MediaDAO
from app.daos.rating_dao import RatingDAO
from app.daos.watch_event_dao import WatchEventDAO
from app.exceptions import (
    MediaNotFoundError,
    RatingNotFoundError,
    RewatchNotAllowedError,
)
from app.models.media import Media
from app.models.ratings import Ratings, WatchStatus
from app.schemas.media_filter_schema import SearchType
from app.schemas.rating_schema import (
    RatedMediaResult,
    RatingAttributes,
    RatingBulkCreate,
    RatingCreate,
    RatingOut,
    RatingScoreItem,
    RatingSearchFilters,
)
from app.services.media_search_service import media_to_dict
from app.services.spoiler_service import recompute_visibility_for_anime
from app.services.vector_embedding_service import (
    create_rating_embedding,
    generate_embedding,
)

logger = logging.getLogger(__name__)

rating_dao = RatingDAO()
media_dao = MediaDAO()
watch_event_dao = WatchEventDAO()

_EXCLUDE_BULK = {"media_uuids"}


def _rating_to_out(r: Ratings, watched_count: int) -> RatingOut:
    data = {
        "uuid": r.uuid,
        "rating": r.rating,
        "watch_status": r.watch_status,
        "watched_count": watched_count,
        "episodes_watched": r.episodes_watched,
        "note": r.note,
        "media_uuid": r.media.uuid,
        "media_title": r.media.title,
        "media_cover_image": r.media.cover_image,
        "anime_uuid": r.media.anime.uuid,
        "anime_title": r.media.anime.title,
        "created_at": r.created_at,
        "modified_at": r.modified_at,
    }
    for field in RatingAttributes.model_fields:
        data[field] = getattr(r, field)
    return RatingOut(**data)


async def _ratings_to_out(db: AsyncSession, user_id: int, ratings: list[Ratings]) -> list[RatingOut]:
    """Shape ratings into RatingOut, batch-loading watched_count (one grouped query)."""
    counts = await watch_event_dao.counts_for_user_media_ids(
        db, user_id, [r.media_id for r in ratings]
    )
    return [_rating_to_out(r, counts.get(r.media_id, 0)) for r in ratings]


async def _resolve_media_uuids(db: AsyncSession, media_uuids: list[UUID]) -> list[Media]:
    """Batch-fetch media by UUIDs in input order. Raises MediaNotFoundError if any UUID is missing."""
    all_media = await media_dao.get_all_by_field(db, "uuid", media_uuids)
    media_by_uuid = {m.uuid: m for m in all_media}

    missing_uuids = [uuid for uuid in media_uuids if uuid not in media_by_uuid]
    if missing_uuids:
        raise MediaNotFoundError(", ".join(str(u) for u in missing_uuids))

    return [media_by_uuid[uuid] for uuid in media_uuids]


async def _upsert_note_embedding(db: AsyncSession, rating: Ratings, note: str | None):
    """Create, update, or delete the RatingSearch embedding when a note changes.
    Deletes the embedding when note is cleared so orphaned vectors don't persist."""
    if note:
        if rating.rating_search:
            rating.rating_search.note_embedding = await generate_embedding(note)
        else:
            await create_rating_embedding(db, rating_id=rating.id, note=note)
    elif rating.rating_search:
        await db.delete(rating.rating_search)


async def _upsert_single_rating(
    db: AsyncSession, user_id: int, media: Media, fields: dict, note: str | None,
    existing: Ratings | None, *, known_has_events: bool | None = None,
) -> UUID:
    """Core upsert logic: create or update one rating and manage its note embedding.
    Returns the rating UUID. Does not commit — caller manages the transaction.

    `known_has_events` lets a batch caller pass the media's prior-event existence
    (fetched once for the whole batch) so the first-watch check skips its per-media query."""

    if existing:
        old_note = existing.note
        for key, value in fields.items():
            setattr(existing, key, value)
        existing.note = note

        # Only regenerate the embedding if note text actually changed (avoids redundant ML inference)
        if existing.note != old_note:
            await _upsert_note_embedding(db, existing, existing.note)

        result_uuid = existing.uuid
    else:
        rating = Ratings(user_id=user_id, media_id=media.id, note=note, **fields)
        await rating_dao.create(db, rating)

        if note:
            await create_rating_embedding(db, rating_id=rating.id, note=note)

        result_uuid = rating.uuid

    await _maybe_log_first_watch(
        db, user_id, media.id, fields.get("watch_status"), known_has_events=known_has_events
    )
    return result_uuid


async def _maybe_log_first_watch(
    db: AsyncSession, user_id: int, media_id: int, watch_status: WatchStatus | None,
    *, known_has_events: bool | None = None,
) -> None:
    """Log the first watch event when a rating write lands as `completed` and the user has
    no prior history for this media. Covers the first completion and an on_hold/dropped →
    completed transition, but a re-rate of media that already has events never duplicates —
    so an accidental delete-then-re-add can't pollute the watch time series. Rewatches go
    through `log_rewatch` instead.

    `known_has_events` short-circuits the per-media existence query when a batch caller
    already fetched it for the whole set (avoids an N+1 in the bulk-upsert loop)."""
    if watch_status != WatchStatus.completed:
        return
    has_events = (
        known_has_events
        if known_has_events is not None
        else await watch_event_dao.exists_for_user_media(db, user_id, media_id)
    )
    if not has_events:
        await watch_event_dao.create_event(db, user_id, media_id)


async def upsert_rating(
    db: AsyncSession, user_id: int, media_uuid: UUID, data: RatingCreate,
    delete_watch_history: bool = False,
) -> RatingOut:
    """Create or update a rating for a media. If the user already rated this media,
    the existing rating is updated instead of raising an error.

    `delete_watch_history` lets the caller wipe the media's watch events alongside the
    write — used when downgrading a rating from completed back to on_hold/dropped and the
    user confirms the prior completions no longer apply."""
    logger.debug(f"DB session: {id(db)}")

    media = (await _resolve_media_uuids(db, [media_uuid]))[0]
    existing = await rating_dao.get_by_user_and_media(db, user_id, media.id)
    # Honor history deletion only on a genuine completed -> on_hold/dropped downgrade,
    # derived server-side from the actual transition rather than trusting the raw flag —
    # so the flag can't wipe history on an upgrade or no-op edit.
    is_downgrade = (
        existing is not None
        and existing.watch_status == WatchStatus.completed
        and data.watch_status != WatchStatus.completed
    )
    fields = data.model_dump()
    note = fields.pop("note")

    uuid = await _upsert_single_rating(db, user_id, media, fields, note, existing)
    if delete_watch_history and is_downgrade:
        await watch_event_dao.delete_for_user_media(db, user_id, [media.id])
    await recompute_visibility_for_anime(db, user_id, media.anime_id)
    await db.commit()

    # Re-fetch with eager loading for media/anime relationships needed by _rating_to_out
    rating = await rating_dao.get_by_uuid_and_user(db, uuid, user_id)
    return (await _ratings_to_out(db, user_id, [rating]))[0]


async def get_rating_for_media(db: AsyncSession, user_id: int, media_uuid: UUID) -> RatingOut:
    rating = await rating_dao.get_by_media_uuid_and_user(db, media_uuid, user_id)
    if not rating:
        raise RatingNotFoundError(str(media_uuid))
    return (await _ratings_to_out(db, user_id, [rating]))[0]


async def get_user_ratings(
    db: AsyncSession, user_id: int, limit: int = 50, offset: int = 0
) -> list[RatingOut]:
    ratings = await rating_dao.get_all_by_user(db, user_id, limit, offset)
    return await _ratings_to_out(db, user_id, ratings)


async def get_ratings_for_anime(
    db: AsyncSession, user_id: int, anime_uuid: UUID
) -> list[RatingOut]:
    ratings = await rating_dao.get_by_user_and_anime_uuid(db, user_id, anime_uuid)
    return await _ratings_to_out(db, user_id, ratings)


def _rating_to_score_item(r: Ratings) -> RatingScoreItem:
    data = {
        "media_uuid": r.media.uuid,
        "anime_uuid": r.media.anime.uuid,
        "media_title": r.media.title,
        "anime_title": r.media.anime.title,
        "media_cover_image": r.media.cover_image,
        "rating": r.rating,
        "watch_status": r.watch_status,
        "age_rating_numeric": r.media.age_rating_numeric,
        "genres": [mg.genre.name for mg in r.media.media_genre],
        "studios": [ms.studio.name for ms in r.media.media_studio],
        "modified_at": r.modified_at,
    }
    for field in RatingAttributes.model_fields:
        data[field] = getattr(r, field)
    return RatingScoreItem(**data)


async def get_rating_score_items(db: AsyncSession, user_id: int) -> list[RatingScoreItem]:
    """Compact list of all the user's ratings for the rating-consistency helper.
    No watched_count batch (the helper doesn't show it) — keeps this to one query."""
    ratings = await rating_dao.get_all_for_score_items(db, user_id)
    return [_rating_to_score_item(r) for r in ratings]


async def delete_rating(
    db: AsyncSession, user_id: int, rating_uuid: UUID, delete_watch_history: bool = False
) -> None:
    rating = await rating_dao.get_by_uuid_and_user(db, rating_uuid, user_id)
    if not rating:
        raise RatingNotFoundError(str(rating_uuid))
    anime_id = rating.media.anime_id
    media_id = rating.media_id
    await rating_dao.delete(db, rating)
    # Watch history is kept by default so a delete-and-re-add doesn't pollute the time
    # series; only an explicit opt-in removes it (the user can't easily undo a wrong delete).
    if delete_watch_history:
        await watch_event_dao.delete_for_user_media(db, user_id, [media_id])
    await recompute_visibility_for_anime(db, user_id, anime_id)
    await db.commit()


async def bulk_delete_ratings(
    db: AsyncSession, user_id: int, media_uuids: list[UUID], delete_watch_history: bool = False
) -> int:
    """Delete ratings for multiple media at once. Returns the number of ratings deleted.
    Silently skips media that have no rating (not an error). Watch history is kept unless
    `delete_watch_history` is set (same opt-in cascade as the single delete)."""
    media_list = await _resolve_media_uuids(db, media_uuids)
    media_ids = [m.id for m in media_list]
    if delete_watch_history:
        # Scope the opt-in history wipe to media that actually have a rating here, so a
        # selected-but-unrated media (silently skipped below) can't lose its preserved
        # events. Captured before the delete — both run in this one uncommitted tx.
        rated_media_ids = await rating_dao.get_rated_media_ids(db, user_id, media_ids)
    count = await rating_dao.bulk_delete_by_user_and_media_ids(db, user_id, media_ids)
    if delete_watch_history:
        await watch_event_dao.delete_for_user_media(db, user_id, rated_media_ids)
    # Recompute visibility for each affected anime
    affected_anime_ids = {m.anime_id for m in media_list}
    for anime_id in affected_anime_ids:
        await recompute_visibility_for_anime(db, user_id, anime_id)
    await db.commit()
    return count


async def log_rewatch(db: AsyncSession, user_id: int, rating_uuid: UUID) -> RatingOut:
    """Append a rewatch event for a rating's media, bumping its derived watched_count.
    Returns the updated rating."""
    rating = await rating_dao.get_by_uuid_and_user(db, rating_uuid, user_id)
    if not rating:
        raise RatingNotFoundError(str(rating_uuid))
    # A watch event means a completion, so only a completed rating can accrue rewatches —
    # enforce the invariant server-side (the UI already hides the button for non-completed).
    if rating.watch_status != WatchStatus.completed:
        raise RewatchNotAllowedError()
    await watch_event_dao.create_event(db, user_id, rating.media_id)
    await db.commit()
    return (await _ratings_to_out(db, user_id, [rating]))[0]


def _rating_to_rated_media_result(r: Ratings, watched_count: int) -> RatedMediaResult:
    rating_data = {
        "rating_uuid": r.uuid,
        "user_rating": r.rating,
        "watch_status": r.watch_status,
        "watched_count": watched_count,
        "episodes_watched": r.episodes_watched,
        "note": r.note,
        "rating_created_at": r.created_at,
        "rating_modified_at": r.modified_at,
    }
    for field in RatingAttributes.model_fields:
        rating_data[field] = getattr(r, field)

    return RatedMediaResult(**media_to_dict(r.media), **rating_data)


async def search_user_ratings(
    db: AsyncSession,
    user_id: int,
    query: str,
    filters: RatingSearchFilters,
    search_type: SearchType,
    limit: int = 50,
) -> list[RatedMediaResult]:
    ratings = await rating_dao.search_ratings_with_filters(
        db, user_id, query, filters, search_type, limit
    )
    counts = await watch_event_dao.counts_for_user_media_ids(
        db, user_id, [r.media_id for r in ratings]
    )
    return [_rating_to_rated_media_result(r, counts.get(r.media_id, 0)) for r in ratings]


async def bulk_upsert_ratings(db: AsyncSession, user_id: int, data: RatingBulkCreate) -> list[RatingOut]:
    """Create or update ratings for multiple media at once. Existing ratings are updated.
    Note is placed on the last 'main' media (by relation_type); falls back to the last
    media overall if none are main. Earlier media have their note cleared.
    This is intentional: bulk-rating means 'rate the whole anime with one note.'"""
    logger.debug(f"DB session: {id(db)}")

    media_list = await _resolve_media_uuids(db, data.media_uuids)

    # Batch-fetch existing ratings to avoid N+1 queries in the upsert loop
    media_ids = [m.id for m in media_list]
    existing_ratings = await rating_dao.get_by_user_and_media_ids(db, user_id, media_ids)
    existing_by_media_id = {r.media_id: r for r in existing_ratings}
    # Pre-fetch which media already have watch events (one grouped query) so the per-media
    # first-watch check in the loop doesn't issue an existence query per media.
    media_with_events = set(
        await watch_event_dao.counts_for_user_media_ids(db, user_id, media_ids)
    )

    # Note goes on the last "main" media; falls back to last media if no main exists
    main_indices = [i for i, m in enumerate(media_list) if m.relation_type.value == "main"]
    note_index = main_indices[-1] if main_indices else len(media_list) - 1
    shared_fields = data.model_dump(exclude=_EXCLUDE_BULK | {"note", "episodes_watched"})
    rating_uuids = []

    for i, media in enumerate(media_list):
        note = data.note if i == note_index else None
        # Auto-fill episodes_watched per media from its total episodes
        per_media_fields = {**shared_fields, "episodes_watched": media.episodes}
        existing = existing_by_media_id.get(media.id)
        uuid = await _upsert_single_rating(
            db, user_id, media, per_media_fields, note, existing,
            known_has_events=media.id in media_with_events,
        )
        rating_uuids.append(uuid)

    # Recompute visibility for each affected anime
    affected_anime_ids = {m.anime_id for m in media_list}
    for anime_id in affected_anime_ids:
        await recompute_visibility_for_anime(db, user_id, anime_id)

    await db.commit()

    # Batch re-fetch with eager loading for _rating_to_out
    ratings = await rating_dao.get_by_uuids_and_user(db, rating_uuids, user_id)
    rating_by_uuid = {r.uuid: r for r in ratings}
    ordered = [rating_by_uuid[uuid] for uuid in rating_uuids]
    return await _ratings_to_out(db, user_id, ordered)
