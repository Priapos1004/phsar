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
from app.services.media_search_service import media_title_texts
from app.services.vector_embedding_service import (
    create_anime_embedding,
    create_media_embedding,
    create_rating_embedding,
    regenerate_anime_embedding,
    regenerate_media_embedding,
    regenerate_rating_embedding,
)

logger = logging.getLogger(__name__)

# Commit checkpoint cadence for the full re-embed. A mid-run container
# restart leaves the committed rows re-normalized and the rest on their
# old (still-valid) vectors — search keeps serving throughout — and a
# re-run is idempotent. Small batches bound the transaction and the
# lost-work window without paying a commit per row.
_REEMBED_COMMIT_BATCH = 50


async def _backfill_anime_embeddings(db: AsyncSession):
    stmt = (
        select(Anime)
        .outerjoin(AnimeSearch, AnimeSearch.anime_id == Anime.id)
        .where(AnimeSearch.id.is_(None))
    )
    result = await db.execute(stmt)
    missing = result.scalars().all()

    count = 0
    for anime in missing:
        try:
            await create_anime_embedding(
                db,
                anime_id=anime.id,
                title_texts=anime_title_texts(anime),
                description_text=anime.description or "",
            )
            count += 1
            logger.info(f"Backfilled embedding for Anime: {anime.title} (ID: {anime.id})")
        except Exception:
            logger.exception(f"Failed to backfill embedding for Anime: {anime.title} (ID: {anime.id})")

    return count


async def _backfill_media_embeddings(db: AsyncSession):
    stmt = (
        select(Media)
        .outerjoin(MediaSearch, MediaSearch.media_id == Media.id)
        .where(MediaSearch.id.is_(None))
    )
    result = await db.execute(stmt)
    missing = result.scalars().all()

    count = 0
    for media in missing:
        try:
            await create_media_embedding(
                db,
                media_id=media.id,
                title_texts=media_title_texts(media),
                description_text=media.description or "",
            )
            count += 1
            logger.info(f"Backfilled embedding for Media: {media.title} (ID: {media.id})")
        except Exception:
            logger.exception(f"Failed to backfill embedding for Media: {media.title} (ID: {media.id})")

    return count


async def _backfill_rating_embeddings(db: AsyncSession):
    stmt = (
        select(Ratings)
        .outerjoin(RatingSearch, RatingSearch.rating_id == Ratings.id)
        .where(Ratings.note.isnot(None), RatingSearch.id.is_(None))
    )
    result = await db.execute(stmt)
    missing = result.scalars().all()

    count = 0
    for rating in missing:
        try:
            await create_rating_embedding(db, rating_id=rating.id, note=rating.note)
            count += 1
            logger.info(f"Backfilled embedding for Rating ID: {rating.id}")
        except Exception:
            logger.exception(f"Failed to backfill embedding for Rating ID: {rating.id}")

    return count


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


async def _reembed_anime(db: AsyncSession) -> int:
    rows = (await db.execute(select(Anime))).scalars().all()
    for i, anime in enumerate(rows, start=1):
        await regenerate_anime_embedding(
            db,
            anime_id=anime.id,
            title_texts=anime_title_texts(anime),
            description_text=anime.description or "",
        )
        if i % _REEMBED_COMMIT_BATCH == 0:
            await db.commit()
            logger.info(f"Re-embed anime: {i}/{len(rows)}")
    await db.commit()
    return len(rows)


async def _reembed_media(db: AsyncSession) -> int:
    rows = (await db.execute(select(Media))).scalars().all()
    for i, media in enumerate(rows, start=1):
        await regenerate_media_embedding(
            db,
            media_id=media.id,
            title_texts=media_title_texts(media),
            description_text=media.description or "",
        )
        if i % _REEMBED_COMMIT_BATCH == 0:
            await db.commit()
            logger.info(f"Re-embed media: {i}/{len(rows)}")
    await db.commit()
    return len(rows)


async def _reembed_ratings(db: AsyncSession) -> int:
    rows = (await db.execute(select(Ratings).where(Ratings.note.isnot(None)))).scalars().all()
    for i, rating in enumerate(rows, start=1):
        await regenerate_rating_embedding(db, rating_id=rating.id, note=rating.note)
        if i % _REEMBED_COMMIT_BATCH == 0:
            await db.commit()
            logger.info(f"Re-embed ratings: {i}/{len(rows)}")
    await db.commit()
    return len(rows)


async def reembed_all_embeddings(db: AsyncSession) -> dict[str, int]:
    """Regenerate EVERY search embedding in place via the current
    `generate_embedding` normalization.

    Distinct from `backfill_embeddings`, which only fills NULL rows: this
    overwrites existing vectors. It's the one-time re-normalization path
    after a `generate_embedding` change — specifically the case-folding fix
    (see `vector_embedding_service.generate_embedding`): query and document
    embeddings must share one case space, and the existing catalog predates
    the fold. Gated by `EMBEDDING_REEMBED_ON_STARTUP` and fired post-yield
    in the background (see `main._post_yield_backfills`) so a ~5-9 min
    catalog re-encode on the 2-vCPU VM can't stall /health.

    In-place regen (delete+insert per row) keeps search serving the old
    vectors until each row is overwritten — no empty-result window. Commits
    in `_REEMBED_COMMIT_BATCH` batches so a mid-run restart checkpoints
    progress; re-running is idempotent (re-encoding an already-folded row
    yields the same vector). Reachable only via the env flag — flip it on
    for one deploy, watch for the completion log, flip it back off."""
    logger.info("Re-embedding entire catalog (full re-normalization pass)")
    anime_count = await _reembed_anime(db)
    media_count = await _reembed_media(db)
    rating_count = await _reembed_ratings(db)
    logger.info(
        f"Re-embed complete: {anime_count} anime, {media_count} media, {rating_count} ratings"
    )
    return {"anime": anime_count, "media": media_count, "ratings": rating_count}
