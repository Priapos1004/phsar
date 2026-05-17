"""Strip season suffixes from existing Anime umbrella name fields.

Runs once at lifespan startup to clean up rows scraped before
`anime_service.create_anime_from_media` started normalising new rows.
Idempotent: subsequent restarts find nothing to change and exit
without touching the catalog.

When a row's title fields are updated, the anime embedding is stale
(the embedding combines `[title, name_eng, name_jap, *other_names]`),
so the existing AnimeSearch row is deleted and regenerated. Skipping
that step would leave title-vector search ranking against pre-strip
text.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anime import Anime
from app.services.anime_service import strip_season_suffix
from app.services.vector_embedding_service import regenerate_anime_embedding

logger = logging.getLogger(__name__)


async def backfill_anime_title_suffixes(db: AsyncSession) -> int:
    """Returns the number of anime rows updated. Callers commit."""
    # No selectinload for Anime.anime_search — we don't read the row,
    # only DELETE it. Pulling the 384-dim title_embedding into memory
    # for every anime would waste hundreds of MB on a large catalog.
    rows = (await db.execute(select(Anime))).scalars().all()

    updated = 0
    for anime in rows:
        new_title = strip_season_suffix(anime.title) or anime.title
        new_eng = strip_season_suffix(anime.name_eng)
        new_jap = strip_season_suffix(anime.name_jap, japanese=True)

        if (new_title, new_eng, new_jap) == (anime.title, anime.name_eng, anime.name_jap):
            continue

        # Regen embedding BEFORE mutating row fields — if regen raises,
        # the row stays consistent with the old (still-valid) embedding
        # instead of committing rewritten title fields paired with a
        # stale vector.
        new_title_texts = [new_title, new_eng, new_jap, *(anime.other_names or [])]
        try:
            logger.info(
                "Stripping suffix from Anime id=%d: title=%r → %r, name_eng=%r → %r, name_jap=%r → %r",
                anime.id, anime.title, new_title, anime.name_eng, new_eng, anime.name_jap, new_jap,
            )
            await regenerate_anime_embedding(
                db, anime.id, new_title_texts, anime.description or "",
            )
            anime.title = new_title
            anime.name_eng = new_eng
            anime.name_jap = new_jap
            updated += 1
        except Exception:
            logger.exception("Failed to strip suffix for Anime id=%d", anime.id)

    if updated:
        await db.commit()
        logger.info("Stripped season suffixes from %d anime row(s).", updated)
    return updated
