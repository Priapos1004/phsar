import logging
import threading
from functools import lru_cache

import numpy as np
from anyio import to_thread
from sentence_transformers import SentenceTransformer
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.anime_search import AnimeSearch
from app.models.media_search import MediaSearch
from app.models.rating_search import RatingSearch

logger = logging.getLogger(__name__)

MODEL_NAME = 'intfloat/multilingual-e5-small'
# Cache first: the model is pinned, so asking the Hub whether it changed only costs a
# request and a warning every boot. A fresh machine's first run falls back to the download.
try:
    model = SentenceTransformer(MODEL_NAME, local_files_only=True)
except OSError:
    model = SentenceTransformer(MODEL_NAME)

# One encode at a time. Encodes run on worker threads (`_run_encode`), and the tokenizer
# and torch's native kernels are not safe to drive from several at once: concurrent
# encodes hang or segfault the process. An encode takes ~30 ms, so the queue costs little;
# a query cache hit never takes it.
_encode_lock = threading.Lock()

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
    with _encode_lock:
        return tuple(model.encode(text, show_progress_bar=False).tolist())


@lru_cache(maxsize=EMBEDDING_CACHE_SIZE)
def _encode_query_cached(text: str) -> tuple[float, ...]:
    """Memoized encode, for SEARCH QUERIES only. Safe to cache by construction:
    `model.encode` is deterministic and the model version is fixed at deploy, so
    the folded text fully determines the vector."""
    return _encode(text)


def _fold(text: str) -> str:
    """The single case-fold every embedding passes through, queries and stored text
    alike — why here and not at the call sites is in docs/features/search.md. It also
    makes capitalisation variants of one query a single cache entry."""
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
    text does not — a save encodes its text exactly once, and a
    sweep or `reembed_all_embeddings` inserts thousands of keys that can never be
    hit again. Sharing a 256-slot LRU therefore left the query cache fully evicted
    after every sweep, i.e. cold precisely after the nightly maintenance window.
    """
    # e5 is asymmetric: docs/features/search.md.
    return await _run_encode(_encode_query_cached, "query: " + text)


async def generate_embedding(text: str) -> list[float]:
    """Embed DOCUMENT text (descriptions with their titles, rating notes) — uncached, since
    a given document string is encoded once. Search queries go through
    `generate_query_embedding`."""
    return await _run_encode(_encode, "passage: " + text)


def cosine_similarity(a, b) -> float:
    """Cosine similarity of two embedding vectors. Returns 0.0 if either
    vector is empty/None or has zero norm. Uses numpy so merge detection's
    O(catalog²) backfill doesn't spend its time in a Python float-loop on
    384-dim arrays."""
    if a is None or b is None:
        return 0.0
    a_arr = np.asarray(a, dtype=np.float32)
    b_arr = np.asarray(b, dtype=np.float32)
    if a_arr.size == 0 or a_arr.shape != b_arr.shape:
        return 0.0
    norm_a = float(np.linalg.norm(a_arr))
    norm_b = float(np.linalg.norm(b_arr))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


async def encode_description(title_texts: list[str | None], description_text: str | None) -> list[float]:
    """The titles and the description encoded together, so any title change
    invalidates it too."""
    combined_text = " ".join([t for t in title_texts if t])
    return await generate_embedding(f"{combined_text} {description_text or ''}")


async def _create_search_embedding(db: AsyncSession, model_class, fk_kwargs: dict, title_texts: list[str | None], description_text: str | None):
    """Shared helper for creating a description embedding and persisting it."""
    description_embedding = await encode_description(title_texts, description_text)
    obj = model_class(**fk_kwargs, description_embedding=description_embedding)
    db.add(obj)
    await db.flush()


async def create_media_embedding(db: AsyncSession, media_id: int, title_texts: list[str | None], description_text: str | None):
    await _create_search_embedding(db, MediaSearch, {"media_id": media_id}, title_texts, description_text)


async def create_anime_embedding(db: AsyncSession, anime_id: int, title_texts: list[str | None], description_text: str | None):
    await _create_search_embedding(db, AnimeSearch, {"anime_id": anime_id}, title_texts, description_text)


async def create_rating_embedding(db: AsyncSession, rating_id: int, note: str):
    embedding = await generate_embedding(note)
    db.add(RatingSearch(rating_id=rating_id, note_embedding=embedding))
    await db.flush()


async def _regenerate_search_embedding(
    db: AsyncSession, model_class, fk_column, fk_value: int,
    title_texts: list[str | None], description_text: str | None,
) -> None:
    """Replace the existing search-embedding row with one built from
    fresh text. Encode FIRST, then DELETE + INSERT, so an encode failure
    leaves the prior row intact — without this discipline a model-loading
    crash mid-call would land a dangling DELETE in the session, and a
    caller catching the exception without rolling back (per-anime
    try/except in relation_backfiller etc.) would commit the deletion
    with no replacement.
    """
    description_embedding = await encode_description(title_texts, description_text)

    await db.execute(delete(model_class).where(fk_column == fk_value))
    db.add(model_class(**{fk_column.key: fk_value}, description_embedding=description_embedding))
    await db.flush()


async def regenerate_media_embedding(
    db: AsyncSession, media_id: int, title_texts: list[str | None], description_text: str | None,
) -> None:
    await _regenerate_search_embedding(
        db, MediaSearch, MediaSearch.media_id, media_id, title_texts, description_text,
    )


async def regenerate_anime_embedding(
    db: AsyncSession, anime_id: int, title_texts: list[str | None], description_text: str | None,
) -> None:
    await _regenerate_search_embedding(
        db, AnimeSearch, AnimeSearch.anime_id, anime_id, title_texts, description_text,
    )


async def regenerate_rating_embedding(db: AsyncSession, rating_id: int, note: str) -> None:
    """Replace a rating's note embedding. Encode first, then delete + insert,
    so an encode failure leaves
    the prior row intact (same discipline as `_regenerate_search_embedding`).
    Tolerates a missing row — the DELETE is a no-op — so it doubles as a
    backfill for a note that never got a search row."""
    embedding = await generate_embedding(note)
    await db.execute(delete(RatingSearch).where(RatingSearch.rating_id == rating_id))
    db.add(RatingSearch(rating_id=rating_id, note_embedding=embedding))
    await db.flush()
