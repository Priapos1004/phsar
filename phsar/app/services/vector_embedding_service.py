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

# Bounded at ~4 MB: each 384-float tuple measures ~12 kB in CPython (the boxed
# floats dominate at 24 B apiece — not the 3 kB the raw values suggest), plus the
# key strings, which for a description can be several kB of synopsis.
EMBEDDING_CACHE_SIZE = 256


def _encode(text: str) -> tuple[float, ...]:
    """Encode one string. Returns a TUPLE because the memoized wrapper below
    shares its value across every caller of a key, and callers hand the result to
    ORM attributes — a cached list would be a shared mutable with no owner.

    show_progress_bar=False: encode() defaults to a tqdm "Batches: ..." bar on
    stdout. We encode one short string per call (search queries, saves, sweeps,
    re-embed), so the bar is pure noise — it flooded the Coolify logs.
    """
    return tuple(model.encode(text, show_progress_bar=False).tolist())


@lru_cache(maxsize=EMBEDDING_CACHE_SIZE)
def _encode_query_cached(text: str) -> tuple[float, ...]:
    """Memoized encode, for SEARCH QUERIES only. Safe to cache by construction:
    `model.encode` is deterministic and the model version is fixed at deploy, so
    the folded text fully determines the vector."""
    return _encode(text)


def _fold(text: str) -> str:
    """The single case-fold every embedding passes through.

    `paraphrase-multilingual-MiniLM-L12-v2` is a *cased* model, so "Kurokos" and
    "kurokos" produce materially different vectors — and the query-case difference
    alone reorders title results enough to drop the intended show off the page
    (the cosine swing exceeds the literal-match bonus). Folding here, on both
    queries AND stored title/description/note text, keeps them in one case space
    (the textbook precondition for embedding retrieval); folding at the query
    call-sites alone would paper over the symptom and risk a fresh
    query↔document mismatch. It is also what makes capitalisation variants of one
    query a single cache entry. Existing catalog vectors predate this and are
    re-normalized by `embedding_backfiller.reembed_all_embeddings`.
    """
    return text.lower()


async def _run_encode(fn, text: str) -> list[float]:
    """Run an encode off the event loop and copy the result into a fresh list.

    abandon_on_cancel=True: if the calling task is cancelled (e.g. the client
    disconnects), abandon the thread rather than blocking until encode()
    finishes — otherwise cancelled requests hold a threadpool slot through the
    whole CPU-heavy computation.

    A cache hit still pays this hop (~100 µs). Deliberate: that is 0.3% of a
    ~30 ms miss, and short-circuiting on the loop would mean two code paths for
    one operation.
    """
    return list(await to_thread.run_sync(lambda: fn(_fold(text)), abandon_on_cancel=True))


async def generate_query_embedding(text: str) -> list[float]:
    """Embed a SEARCH QUERY — memoized (~30 ms → ~0.1 ms on a hit).

    Separate from `generate_embedding` because the two populations have opposite
    reuse profiles and would share one cache otherwise. Queries repeat; document
    text does not — a save encodes each title and description exactly once, and a
    sweep or `reembed_all_embeddings` inserts thousands of keys that can never be
    hit again. Sharing a 256-slot LRU therefore left the query cache fully evicted
    after every sweep, i.e. cold precisely after the nightly maintenance window.
    """
    return await _run_encode(_encode_query_cached, text)


async def generate_embedding(text: str) -> list[float]:
    """Embed DOCUMENT text (titles, descriptions, rating notes) — uncached, since
    a given document string is encoded once. Search queries go through
    `generate_query_embedding`."""
    return await _run_encode(_encode, text)


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
