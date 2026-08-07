import logging
from functools import lru_cache

from anyio import to_thread
from sentence_transformers import SentenceTransformer
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anime_search import AnimeSearch
from app.models.media_search import MediaSearch
from app.models.rating_search import RatingSearch

logger = logging.getLogger(__name__)

model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

# Bounded at ~3.0 MB: a 384-float tuple measures ~12 kB in CPython (the boxed
# floats dominate, 24 B apiece — not the 3 kB the raw values suggest).
#
# Sized for search-query reuse, not for holding the catalog. The cache is shared
# with document text (titles, descriptions, notes), so a sweep re-embedding
# hundreds of media will evict every query in it. That's the LRU doing its job:
# the entries worth keeping are the ones being asked for repeatedly, and a miss
# only costs what every call cost before.
EMBEDDING_CACHE_SIZE = 256


@lru_cache(maxsize=EMBEDDING_CACHE_SIZE)
def _encode_cached(text: str) -> tuple[float, ...]:
    """Memoized encode. Safe to cache by construction: `model.encode` is
    deterministic and the model version is fixed at deploy, so the folded text
    fully determines the vector.

    Returns a TUPLE. The value is shared across every caller that hits this key,
    and callers hand the result to ORM attributes — a cached list would be a
    shared mutable with no owner. `generate_embedding` copies it into a fresh
    list per call, which is 384 floats.

    show_progress_bar=False: encode() defaults to a tqdm "Batches: ..." bar on
    stdout. We encode one short string per call (search queries, saves, sweeps,
    re-embed), so the bar is pure noise — it flooded the Coolify logs.
    """
    return tuple(model.encode(text, show_progress_bar=False).tolist())


async def generate_embedding(text: str) -> list[float]:
    # Case-fold before encoding. `paraphrase-multilingual-MiniLM-L12-v2` is a
    # *cased* model, so "Kurokos" and "kurokos" produce materially different
    # vectors — and the query case difference alone reorders title results
    # enough to drop the intended show off the page (the cosine swing exceeds
    # the literal-match bonus). This is the single chokepoint every embedding
    # passes through — search queries AND stored title/description/note text —
    # so lowering here keeps the query and the documents in one case space
    # (the textbook precondition for embedding retrieval). Lowering at the
    # query call-sites alone would only paper over the symptom and risk a new
    # query↔document mismatch. Existing catalog vectors predate this and are
    # re-normalized by `embedding_backfiller.reembed_all_embeddings`.
    text = text.lower()
    # The encode is memoized on the FOLDED text (see `_encode_cached`), so the
    # fold is what makes "Kurokos" and "kurokos" one cache entry rather than two.
    #
    # A cache hit still pays the thread hop. That's deliberate: it costs
    # microseconds against a ~30 ms miss, and checking the cache on the event
    # loop first would mean two code paths for one operation.
    #
    # abandon_on_cancel=True: if the calling async task is cancelled (e.g. client
    # disconnects), abandon the thread instead of blocking until encode() finishes.
    # Without this, cancelled requests keep the thread pool occupied during the
    # CPU-heavy embedding computation.
    return list(await to_thread.run_sync(
        lambda: _encode_cached(text),
        abandon_on_cancel=True,
    ))


async def _compute_search_embeddings(
    title_texts: list[str | None], description_text: str,
) -> tuple[list[float], list[float]]:
    """Encode title + description embeddings without touching the DB.
    Returned in title-then-description order. Two sequential awaits;
    `asyncio.gather` is intentionally avoided (see CLAUDE.md "Async
    throughout" — the trap surface isn't worth the modest CPU win on
    a 2-vCPU VM)."""
    combined_text = " ".join([t for t in title_texts if t])
    title_embedding = await generate_embedding(combined_text)
    description_embedding = await generate_embedding(f"{combined_text} {description_text}")
    return title_embedding, description_embedding


async def _create_search_embedding(db: AsyncSession, model_class, fk_kwargs: dict, title_texts: list[str], description_text: str):
    """Shared helper for creating title + description embeddings and persisting them."""
    title_embedding, description_embedding = await _compute_search_embeddings(title_texts, description_text)
    obj = model_class(**fk_kwargs, title_embedding=title_embedding, description_embedding=description_embedding)
    db.add(obj)
    await db.flush()


async def create_media_embedding(db: AsyncSession, media_id: int, title_texts: list[str], description_text: str):
    await _create_search_embedding(db, MediaSearch, {"media_id": media_id}, title_texts, description_text)


async def create_anime_embedding(db: AsyncSession, anime_id: int, title_texts: list[str], description_text: str):
    await _create_search_embedding(db, AnimeSearch, {"anime_id": anime_id}, title_texts, description_text)


async def create_rating_embedding(db: AsyncSession, rating_id: int, note: str):
    embedding = await generate_embedding(note)
    db.add(RatingSearch(rating_id=rating_id, note_embedding=embedding))
    await db.flush()


async def _regenerate_search_embedding(
    db: AsyncSession, model_class, fk_column, fk_value: int,
    title_texts: list[str | None], description_text: str,
) -> None:
    """Replace the existing search-embedding row with one built from
    fresh text. Encode FIRST, then DELETE + INSERT, so an encode failure
    leaves the prior row intact — without this discipline a model-loading
    crash mid-call would land a dangling DELETE in the session, and a
    caller catching the exception without rolling back (per-anime
    try/except in relation_backfiller etc.) would commit the deletion
    with no replacement.

    Title and description embeddings are both rebuilt: title text mixes
    into the description embedding (see `_compute_search_embeddings`),
    so any title-side change invalidates both anyway.
    """
    title_embedding, description_embedding = await _compute_search_embeddings(title_texts, description_text)

    await db.execute(delete(model_class).where(fk_column == fk_value))
    db.add(model_class(
        **{fk_column.key: fk_value},
        title_embedding=title_embedding,
        description_embedding=description_embedding,
    ))
    await db.flush()


async def regenerate_media_embedding(
    db: AsyncSession, media_id: int, title_texts: list[str | None], description_text: str,
) -> None:
    await _regenerate_search_embedding(
        db, MediaSearch, MediaSearch.media_id, media_id, title_texts, description_text,
    )


async def regenerate_anime_embedding(
    db: AsyncSession, anime_id: int, title_texts: list[str | None], description_text: str,
) -> None:
    await _regenerate_search_embedding(
        db, AnimeSearch, AnimeSearch.anime_id, anime_id, title_texts, description_text,
    )


async def regenerate_rating_embedding(db: AsyncSession, rating_id: int, note: str) -> None:
    """Replace a rating's note embedding (single embedding, no title/desc
    split). Encode first, then delete + insert, so an encode failure leaves
    the prior row intact (same discipline as `_regenerate_search_embedding`).
    Tolerates a missing row — the DELETE is a no-op — so it doubles as a
    backfill for a note that never got a search row."""
    embedding = await generate_embedding(note)
    await db.execute(delete(RatingSearch).where(RatingSearch.rating_id == rating_id))
    db.add(RatingSearch(rating_id=rating_id, note_embedding=embedding))
    await db.flush()
