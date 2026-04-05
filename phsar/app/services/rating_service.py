import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.media_dao import MediaDAO
from app.daos.rating_dao import RatingDAO
from app.exceptions import (
    MediaNotFoundError,
    RatingNotFoundError,
)
from app.models.media import Media
from app.models.rating_search import RatingSearch
from app.models.ratings import Ratings
from app.schemas.media_filter_schema import SearchType
from app.schemas.rating_schema import (
    RatedMediaResult,
    RatingAttributes,
    RatingBulkCreate,
    RatingCreate,
    RatingOut,
    RatingSearchFilters,
)
from app.services.media_search_service import media_to_dict
from app.services.vector_embedding_service import generate_embedding

logger = logging.getLogger(__name__)

rating_dao = RatingDAO()
media_dao = MediaDAO()

_EXCLUDE_BULK = {"media_uuids"}


def _rating_to_out(r: Ratings) -> RatingOut:
    data = {
        "uuid": r.uuid,
        "rating": r.rating,
        "dropped": r.dropped,
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


async def _resolve_media_uuids(db: AsyncSession, media_uuids: list[UUID]) -> list[Media]:
    """Batch-fetch media by UUIDs in input order. Raises MediaNotFoundError if any UUID is missing."""
    all_media = await media_dao.get_all_by_field(db, "uuid", media_uuids)
    media_by_uuid = {m.uuid: m for m in all_media}

    media_list = []
    for uuid in media_uuids:
        media = media_by_uuid.get(uuid)
        if not media:
            raise MediaNotFoundError(str(uuid))
        media_list.append(media)
    return media_list


async def _create_note_embedding(db: AsyncSession, rating_id: int, note: str):
    """Generate an embedding for a note and create a RatingSearch record."""
    embedding = await generate_embedding(note)
    db.add(RatingSearch(rating_id=rating_id, note_embedding=embedding))


async def _upsert_note_embedding(db: AsyncSession, rating: Ratings, note: str | None):
    """Create, update, or delete the RatingSearch embedding when a note changes.
    Deletes the embedding when note is cleared so orphaned vectors don't persist."""
    if note:
        embedding = await generate_embedding(note)
        if rating.rating_search:
            rating.rating_search.note_embedding = embedding
        else:
            db.add(RatingSearch(rating_id=rating.id, note_embedding=embedding))
    elif rating.rating_search:
        await db.delete(rating.rating_search)


async def _upsert_single_rating(
    db: AsyncSession, user_id: int, media: Media, fields: dict, note: str | None,
    existing: Ratings | None,
) -> UUID:
    """Core upsert logic: create or update one rating and manage its note embedding.
    Returns the rating UUID. Does not commit — caller manages the transaction."""

    if existing:
        old_note = existing.note
        for key, value in fields.items():
            setattr(existing, key, value)
        existing.note = note

        # Only regenerate the embedding if note text actually changed (avoids redundant ML inference)
        if existing.note != old_note:
            await _upsert_note_embedding(db, existing, existing.note)

        return existing.uuid
    else:
        rating = Ratings(user_id=user_id, media_id=media.id, note=note, **fields)
        await rating_dao.create(db, rating)

        # New rating has no rating_search yet — create embedding directly
        if note:
            await _create_note_embedding(db, rating.id, note)

        return rating.uuid


async def upsert_rating(db: AsyncSession, user_id: int, media_uuid: UUID, data: RatingCreate) -> RatingOut:
    """Create or update a rating for a media. If the user already rated this media,
    the existing rating is updated instead of raising an error."""
    logger.debug(f"DB session: {id(db)}")

    media = (await _resolve_media_uuids(db, [media_uuid]))[0]
    existing = await rating_dao.get_by_user_and_media(db, user_id, media.id)
    fields = data.model_dump()
    note = fields.pop("note")

    uuid = await _upsert_single_rating(db, user_id, media, fields, note, existing)
    await db.commit()

    # Re-fetch with eager loading for media/anime relationships needed by _rating_to_out
    rating = await rating_dao.get_by_uuid_and_user(db, uuid, user_id)
    return _rating_to_out(rating)


async def get_rating_for_media(db: AsyncSession, user_id: int, media_uuid: UUID) -> RatingOut:
    rating = await rating_dao.get_by_media_uuid_and_user(db, media_uuid, user_id)
    if not rating:
        raise RatingNotFoundError(str(media_uuid))
    return _rating_to_out(rating)


async def get_user_ratings(
    db: AsyncSession, user_id: int, limit: int = 50, offset: int = 0
) -> list[RatingOut]:
    ratings = await rating_dao.get_all_by_user(db, user_id, limit, offset)
    return [_rating_to_out(r) for r in ratings]


async def delete_rating(db: AsyncSession, user_id: int, rating_uuid: UUID) -> None:
    rating = await rating_dao.get_by_uuid_and_user(db, rating_uuid, user_id)
    if not rating:
        raise RatingNotFoundError(str(rating_uuid))
    await rating_dao.delete(db, rating)
    await db.commit()


def _rating_to_rated_media_result(r: Ratings) -> RatedMediaResult:
    rating_data = {
        "rating_uuid": r.uuid,
        "user_rating": r.rating,
        "dropped": r.dropped,
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
    return [_rating_to_rated_media_result(r) for r in ratings]


async def bulk_upsert_ratings(db: AsyncSession, user_id: int, data: RatingBulkCreate) -> list[RatingOut]:
    """Create or update ratings for multiple media at once. Existing ratings are updated.
    Note is placed on the last (newest) media only; earlier media have their note cleared.
    This is intentional: bulk-rating means 'rate the whole anime with one note.'"""
    logger.debug(f"DB session: {id(db)}")

    media_list = await _resolve_media_uuids(db, data.media_uuids)

    # Batch-fetch existing ratings to avoid N+1 queries in the upsert loop
    media_ids = [m.id for m in media_list]
    existing_ratings = await rating_dao.get_by_user_and_media_ids(db, user_id, media_ids)
    existing_by_media_id = {r.media_id: r for r in existing_ratings}

    # Note goes on the last (newest) media so anime page can show notes chronologically
    note_index = len(media_list) - 1
    shared_fields = data.model_dump(exclude=_EXCLUDE_BULK | {"note"})
    rating_uuids = []

    for i, media in enumerate(media_list):
        note = data.note if i == note_index else None
        existing = existing_by_media_id.get(media.id)
        uuid = await _upsert_single_rating(db, user_id, media, shared_fields, note, existing)
        rating_uuids.append(uuid)

    await db.commit()

    # Batch re-fetch with eager loading for _rating_to_out
    ratings = await rating_dao.get_by_uuids_and_user(db, rating_uuids, user_id)
    rating_by_uuid = {r.uuid: r for r in ratings}
    return [_rating_to_out(rating_by_uuid[uuid]) for uuid in rating_uuids]
