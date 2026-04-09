import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anime import Anime
from app.models.anime_search import AnimeSearch
from app.models.media import Media
from app.models.media_search import MediaSearch
from app.models.rating_search import RatingSearch
from app.models.ratings import Ratings
from app.services.anime_search_service import anime_title_texts
from app.services.vector_embedding_service import (
    create_anime_embedding,
    create_media_embedding,
    create_rating_embedding,
)

logger = logging.getLogger(__name__)


async def _backfill_anime_embeddings(db: AsyncSession):
    stmt = (
        select(Anime)
        .outerjoin(AnimeSearch, AnimeSearch.anime_id == Anime.id)
        .where(AnimeSearch.id.is_(None))
    )
    result = await db.execute(stmt)
    missing = result.scalars().all()

    for anime in missing:
        await create_anime_embedding(
            db,
            anime_id=anime.id,
            title_texts=anime_title_texts(anime),
            description_text=anime.description or "",
        )
        logger.info(f"Backfilled embedding for Anime: {anime.title} (ID: {anime.id})")

    return len(missing)


async def _backfill_media_embeddings(db: AsyncSession):
    stmt = (
        select(Media)
        .outerjoin(MediaSearch, MediaSearch.media_id == Media.id)
        .where(MediaSearch.id.is_(None))
    )
    result = await db.execute(stmt)
    missing = result.scalars().all()

    for media in missing:
        await create_media_embedding(
            db,
            media_id=media.id,
            title_texts=[media.title, media.name_eng, media.name_jap, *(media.other_names or [])],
            description_text=media.description or "",
        )
        logger.info(f"Backfilled embedding for Media: {media.title} (ID: {media.id})")

    return len(missing)


async def _backfill_rating_embeddings(db: AsyncSession):
    stmt = (
        select(Ratings)
        .outerjoin(RatingSearch, RatingSearch.rating_id == Ratings.id)
        .where(Ratings.note.isnot(None), RatingSearch.id.is_(None))
    )
    result = await db.execute(stmt)
    missing = result.scalars().all()

    for rating in missing:
        await create_rating_embedding(db, rating_id=rating.id, note=rating.note)
        logger.info(f"Backfilled embedding for Rating ID: {rating.id}")

    return len(missing)


async def backfill_embeddings(db: AsyncSession):
    """Backfill missing embeddings for anime, media, and ratings.

    Intended to run at startup so that an embedding model swap
    (Alembic migration wipes vectors) is followed by automatic regeneration.
    """
    anime_count = await _backfill_anime_embeddings(db)
    media_count = await _backfill_media_embeddings(db)
    rating_count = await _backfill_rating_embeddings(db)

    total = anime_count + media_count + rating_count
    if total:
        logger.info(
            f"Backfilled embeddings: {anime_count} anime, {media_count} media, {rating_count} ratings"
        )
        await db.commit()
