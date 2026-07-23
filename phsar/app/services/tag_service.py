import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.tag_dao import TagDAO
from app.daos.watchlist_dao import WatchlistDAO
from app.exceptions import (
    DefaultTagImmutableError,
    DuplicateTagNameError,
    TagLimitError,
    TagNotFoundError,
)
from app.models.tag import Tag
from app.schemas.tag_schema import TagCreate, TagOut, TagUpdate

logger = logging.getLogger(__name__)

tag_dao = TagDAO()
watchlist_dao = WatchlistDAO()

# The immutable per-user default tag. Its reserved color is kept OUT of the
# user-selectable palette (see the frontend tag palette) so the default tag
# reads as special and can't be visually impersonated by a custom tag.
DEFAULT_TAG_NAME = "Watchlist"
DEFAULT_TAG_COLOR = "#f97316"  # orange — reserved for the default tag
# Anti-runaway ceiling, not a target: the default tag + a handful of intent/genre
# buckets covers realistic use, and the grid's tag filter is multi-select so extra
# tags are cheap. Keeps the filter list readable.
TAGS_PER_USER_LIMIT = 15


def _tag_to_out(tag: Tag, counts: tuple[int, int]) -> TagOut:
    out = TagOut.model_validate(tag)
    out.entry_count, out.anime_count = counts
    return out


async def _get_owned_tag(db: AsyncSession, user_id: int, uuid: UUID) -> Tag:
    tag = await tag_dao.get_by_uuid_and_user(db, uuid, user_id)
    if not tag:
        raise TagNotFoundError(str(uuid))
    return tag


async def _commit_or_raise_duplicate(db: AsyncSession, name: str) -> None:
    """Commit, translating a unique_user_tag violation into DuplicateTagNameError.
    Backstops the check-then-write race (double-click / concurrent request) that the
    happy-path pre-check can't close — mirrors anime_completion_dao's ON CONFLICT."""
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        if "unique_user_tag" in str(e.orig):
            raise DuplicateTagNameError(name) from e
        raise


async def create_default_tag(db: AsyncSession, user_id: int) -> Tag:
    """Ensure the user has their immutable default 'Watchlist' tag.

    Idempotent — returns the existing default if one is present, else creates it.
    Does NOT commit; the caller owns the transaction.
    """
    existing = await tag_dao.get_default_for_user(db, user_id)
    if existing:
        return existing
    tag = Tag(
        user_id=user_id,
        name=DEFAULT_TAG_NAME,
        color=DEFAULT_TAG_COLOR,
        is_default=True,
    )
    return await tag_dao.create(db, tag)


async def list_tags(db: AsyncSession, user_id: int) -> list[TagOut]:
    """All of a user's tags (default first) with their entry + anime counts."""
    tags = await tag_dao.get_all_by_user(db, user_id)
    counts = await watchlist_dao.counts_by_tag(db, user_id)
    return [_tag_to_out(t, counts.get(t.id, (0, 0))) for t in tags]


async def create_tag(db: AsyncSession, user_id: int, data: TagCreate) -> TagOut:
    if await tag_dao.count_by_user(db, user_id) >= TAGS_PER_USER_LIMIT:
        raise TagLimitError(TAGS_PER_USER_LIMIT)
    if await tag_dao.get_by_name_and_user(db, data.name, user_id):
        raise DuplicateTagNameError(data.name)

    tag = Tag(user_id=user_id, name=data.name, color=data.color, is_default=False)
    await tag_dao.create(db, tag)
    await _commit_or_raise_duplicate(db, data.name)
    await db.refresh(tag)
    return _tag_to_out(tag, (0, 0))


async def update_tag(db: AsyncSession, user_id: int, uuid: UUID, data: TagUpdate) -> TagOut:
    tag = await _get_owned_tag(db, user_id, uuid)
    if tag.is_default:
        raise DefaultTagImmutableError()

    if data.name is not None and data.name != tag.name:
        if await tag_dao.get_by_name_and_user(db, data.name, user_id):
            raise DuplicateTagNameError(data.name)
        tag.name = data.name
    if data.color is not None:
        tag.color = data.color

    await _commit_or_raise_duplicate(db, tag.name)
    await db.refresh(tag)
    counts = await watchlist_dao.counts_for_tag(db, user_id, tag.id)
    return _tag_to_out(tag, counts)


async def delete_tag(
    db: AsyncSession, user_id: int, uuid: UUID, reassign_entries: bool
) -> int:
    """Delete a non-default tag. When reassign_entries is True the tag's entries
    move to the default 'Watchlist' tag first (nothing lost); otherwise they're
    deleted with the tag. Returns the number of entries moved/deleted."""
    tag = await _get_owned_tag(db, user_id, uuid)
    if tag.is_default:
        raise DefaultTagImmutableError()

    if reassign_entries:
        default = await create_default_tag(db, user_id)
        affected = await watchlist_dao.reassign_tag(db, user_id, tag.id, default.id)
    else:
        # Explicit delete (not just the FK cascade) so we can return an accurate count.
        affected = await watchlist_dao.delete_all_by_user_and_tag_id(db, user_id, tag.id)

    await tag_dao.delete(db, tag)
    await db.commit()
    return affected


async def empty_tag(db: AsyncSession, user_id: int, uuid: UUID) -> int:
    """Remove all watchlist entries under a tag, keeping the tag itself. Works on
    any tag — this is the default tag's only bulk-clear action (it can't be
    deleted). Returns the number of entries removed."""
    tag = await _get_owned_tag(db, user_id, uuid)
    removed = await watchlist_dao.delete_all_by_user_and_tag_id(db, user_id, tag.id)
    await db.commit()
    return removed
