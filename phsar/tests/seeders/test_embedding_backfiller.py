"""`reembed_all_embeddings` — the one-shot catalog re-normalization path.

Unlike `backfill_embeddings` (which only fills NULL rows), the re-embed
overwrites EVERY existing vector so the catalog picks up a
`generate_embedding` change (the case-folding fix). The tests overwrite
stored vectors with a sentinel and assert the re-embed replaces them with
freshly-encoded ones — proving it regenerates in place rather than skipping
populated rows.
"""

import numpy as np
import pytest
from sqlalchemy import select

from app.models.anime import Anime
from app.models.anime_search import AnimeSearch
from app.models.media import Media
from app.models.media_search import MediaSearch
from app.models.rating_search import RatingSearch
from app.models.ratings import Ratings, WatchStatus
from app.models.users import RoleType, Users
from app.seeders.embedding_backfiller import reembed_all_embeddings
from app.services.anime_search_service import anime_title_texts
from app.services.vector_embedding_service import (
    create_anime_embedding,
    create_media_embedding,
    create_rating_embedding,
    generate_embedding,
)
from tests._helpers import media_kwargs

_SENTINEL = [0.5] * 384


def _is_sentinel(vec) -> bool:
    return np.allclose(np.asarray(vec, dtype=float), _SENTINEL)


async def _cosine_to(vec, text: str) -> float:
    """Cosine similarity of a stored vector to a freshly-encoded `text`."""
    fresh = np.asarray(await generate_embedding(text), dtype=float)
    stored = np.asarray(vec, dtype=float)
    return float(stored @ fresh / (np.linalg.norm(stored) * np.linalg.norm(fresh)))


@pytest.mark.asyncio
async def test_reembed_regenerates_existing_vectors_in_place(db_session):
    anime = Anime(mal_id=99001, title="Reembed Show", description="A reembed description.")
    db_session.add(anime)
    await db_session.flush()
    await create_anime_embedding(
        db_session, anime_id=anime.id,
        title_texts=anime_title_texts(anime), description_text=anime.description or "",
    )
    media = Media(**media_kwargs(anime.id, 990010, title="Reembed Media"))
    db_session.add(media)
    await db_session.flush()
    await create_media_embedding(
        db_session, media_id=media.id,
        title_texts=[media.title], description_text=media.title,
    )

    user = Users(username="reembed-rater", hashed_password="x", role=RoleType.User)
    db_session.add(user)
    await db_session.flush()
    rating = Ratings(
        rating=9.0, media_id=media.id, user_id=user.id,
        note="A Memorable Note", episodes_watched=12, watch_status=WatchStatus.completed,
    )
    db_session.add(rating)
    await db_session.flush()
    await create_rating_embedding(db_session, rating_id=rating.id, note=rating.note)

    # Overwrite the stored vectors so a no-op (skip-populated) pass is
    # distinguishable from a true regeneration.
    a_row = (await db_session.execute(
        select(AnimeSearch).where(AnimeSearch.anime_id == anime.id))).scalar_one()
    m_row = (await db_session.execute(
        select(MediaSearch).where(MediaSearch.media_id == media.id))).scalar_one()
    r_row = (await db_session.execute(
        select(RatingSearch).where(RatingSearch.rating_id == rating.id))).scalar_one()
    a_row.title_embedding = _SENTINEL
    m_row.title_embedding = _SENTINEL
    r_row.note_embedding = _SENTINEL
    await db_session.flush()

    counts = await reembed_all_embeddings(db_session)
    assert counts["anime"] >= 1 and counts["media"] >= 1 and counts["ratings"] >= 1

    a_after = (await db_session.execute(
        select(AnimeSearch).where(AnimeSearch.anime_id == anime.id))).scalar_one()
    m_after = (await db_session.execute(
        select(MediaSearch).where(MediaSearch.media_id == media.id))).scalar_one()
    r_after = (await db_session.execute(
        select(RatingSearch).where(RatingSearch.rating_id == rating.id))).scalar_one()

    # Each sentinel was replaced by the freshly case-folded encoding.
    assert not _is_sentinel(a_after.title_embedding)
    assert not _is_sentinel(m_after.title_embedding)
    assert not _is_sentinel(r_after.note_embedding)
    assert await _cosine_to(
        a_after.title_embedding,
        " ".join(t for t in anime_title_texts(anime) if t),
    ) > 0.999
    assert await _cosine_to(m_after.title_embedding, media.title) > 0.999
    assert await _cosine_to(r_after.note_embedding, rating.note) > 0.999
