import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.daos.media_unwanted_dao import MediaUnwantedDAO
from app.models.media_unwanted import MediaUnwanted

logger = logging.getLogger(__name__)

media_unwanted_dao = MediaUnwantedDAO()

async def create_unwanted_media(db: AsyncSession, unwanted_media: set[tuple[int, str, str]]) -> None:
    logger.debug(f"DB session: {id(db)}")

    incoming_mal_ids = [mal_id for mal_id, _, _ in unwanted_media]
    existing_records = await media_unwanted_dao.get_all_by_field(db, "mal_id", incoming_mal_ids)
    existing_mal_ids = {r.mal_id for r in existing_records}

    new_items = [
        MediaUnwanted(mal_id=mal_id, title=title, reason=reason)
        for mal_id, title, reason in unwanted_media
        if mal_id not in existing_mal_ids
    ]
    if new_items:
        db.add_all(new_items)
        await db.flush()

    logger.info(f"Inserted {len(new_items)} unwanted media items, skipped {len(existing_mal_ids)} existing.")
