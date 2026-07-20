import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.tag_dao import TagDAO
from app.models.tag import Tag

logger = logging.getLogger(__name__)

tag_dao = TagDAO()

# The immutable per-user default tag. Its reserved color is kept OUT of the
# user-selectable palette (see the frontend tag palette) so the default tag
# reads as special and can't be visually impersonated by a custom tag.
DEFAULT_TAG_NAME = "Watchlist"
DEFAULT_TAG_COLOR = "#f97316"  # orange — reserved for the default tag


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
