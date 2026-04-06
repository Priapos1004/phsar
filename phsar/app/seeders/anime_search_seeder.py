import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anime import Anime
from app.models.anime_search import AnimeSearch
from app.services.anime_search_service import anime_title_texts
from app.services.vector_embedding_service import create_anime_embedding

logger = logging.getLogger(__name__)


async def seed_anime_embeddings(db: AsyncSession):
    """Backfill AnimeSearch embeddings for any anime that doesn't have one yet."""

    # Query only anime that are missing embeddings (LEFT JOIN + IS NULL)
    stmt = (
        select(Anime)
        .outerjoin(AnimeSearch, AnimeSearch.anime_id == Anime.id)
        .where(AnimeSearch.id.is_(None))
    )
    result = await db.execute(stmt)
    missing = result.scalars().all()

    if not missing:
        return

    logger.info(f"Backfilling embeddings for {len(missing)} anime")
    for anime in missing:
        await create_anime_embedding(
            db,
            anime_id=anime.id,
            title_texts=anime_title_texts(anime),
            description_text=anime.description or "",
        )
        logger.info(f"Backfilled embedding for Anime: {anime.title} (ID: {anime.id})")

    await db.commit()
