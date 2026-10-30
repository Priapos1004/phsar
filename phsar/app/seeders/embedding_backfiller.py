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
    cosine_similarity,
    create_anime_embedding,
    create_media_embedding,
    create_rating_embedding,
    encode_description,
    regenerate_anime_embedding,
    regenerate_media_embedding,
    regenerate_rating_embedding,
)

logger = logging.getLogger(__name__)

# Commit checkpoint cadence for the full re-embed (`reembed_all_embeddings`).
# Small batches bound the transaction and the lost-work window without paying
# a commit per row.
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
            assert rating.note is not None  # the query selects noted ratings only
            await create_rating_embedding(db, rating_id=rating.id, note=rating.note)
            count += 1
            logger.info(f"Backfilled embedding for Rating ID: {rating.id}")
        except Exception:
            logger.exception(f"Failed to backfill embedding for Rating ID: {rating.id}")

    return count


async def backfill_embeddings(db: AsyncSession):
    """Backfill missing embeddings for anime, media, and ratings.

    Runs at startup so any row without one gets one. A model change goes through
    `reembed_all_embeddings` instead.
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


async def _reembed(db: AsyncSession, label: str, stmt, regenerate) -> int:
    rows = (await db.execute(stmt)).scalars().all()
    for i, row in enumerate(rows, start=1):
        await regenerate(row)
        if i % _REEMBED_COMMIT_BATCH == 0:
            await db.commit()
            logger.info(f"Re-embed {label}: {i}/{len(rows)}")
    await db.commit()
    return len(rows)


async def embeddings_are_stale(db: AsyncSession) -> bool:
    """Whether the stored vectors predate what `generate_embedding` produces now.
    Re-encodes one stored row, the lowest-id anime, and
    compares: one encode per boot instead of a flag someone must remember to
    flip, where forgetting leaves search comparing two models without an error.

    `reembed_all_embeddings` writes that row last, so a pass cut short anywhere
    leaves it stale and the next boot runs the pass again. The floor only absorbs
    float noise between two encodes of the same text."""
    row = (await db.execute(
        select(Anime, AnimeSearch.description_embedding)
        .join(AnimeSearch, AnimeSearch.anime_id == Anime.id)
        .order_by(Anime.id)
        .limit(1)
    )).first()
    if row is None:
        return False
    anime, stored = row
    fresh = await encode_description(anime_title_texts(anime), anime.description or "")
    return cosine_similarity(stored, fresh) < 0.9999


async def reembed_all_embeddings(db: AsyncSession) -> dict[str, int]:
    """Regenerate EVERY search embedding in place via the current
    `generate_embedding`.

    Distinct from `backfill_embeddings`, which only fills NULL rows: this
    overwrites existing vectors, after any change to what a stored vector is built
    from — query and stored vectors must come from the same model and text.

    In-place regen (delete+insert per row) keeps search serving the old
    vectors until each row is overwritten — no empty-result window. After a
    model change those old vectors sit in the other model's space, so semantic
    results are poor until the pass ends; that window is accepted. Commits
    in `_REEMBED_COMMIT_BATCH` batches; re-running is idempotent (re-encoding a
    row with the current model yields the same vector)."""
    logger.info("Stored embeddings are stale — re-embedding entire catalog")
    # Anime last, highest id first: the probe's row is the last one written
    # (`embeddings_are_stale`).
    counts = {
        "media": await _reembed(db, "media", select(Media), lambda media: regenerate_media_embedding(
            db, media_id=media.id, title_texts=media_title_texts(media),
            description_text=media.description or "",
        )),
        # `or ""` only narrows the type: the query selects noted ratings.
        "ratings": await _reembed(
            db, "ratings", select(Ratings).where(Ratings.note.isnot(None)),
            lambda rating: regenerate_rating_embedding(db, rating_id=rating.id, note=rating.note or ""),
        ),
        "anime": await _reembed(
            db, "anime", select(Anime).order_by(Anime.id.desc()),
            lambda anime: regenerate_anime_embedding(
                db, anime_id=anime.id, title_texts=anime_title_texts(anime),
                description_text=anime.description or "",
            ),
        ),
    }
    logger.info(
        f"Re-embed complete: {counts['anime']} anime, {counts['media']} media, {counts['ratings']} ratings"
    )
    return counts
