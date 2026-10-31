"""`reembed_all_embeddings` — the catalog re-embed path — and `embeddings_are_stale`,
the boot probe that decides when it runs. Stored vectors are overwritten with a
sentinel, which a real encode never produces.
"""

import itertools

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
from app.seeders import embedding_backfiller
from app.seeders.embedding_backfiller import (
    embeddings_are_stale,
    reembed_all_embeddings,
)
from app.services.anime_search_service import anime_title_texts
from app.services.vector_embedding_service import (
    cosine_similarity,
    create_anime_embedding,
    create_media_embedding,
    create_rating_embedding,
    generate_embedding,
    regenerate_anime_embedding,
)
from tests._helpers import media_kwargs

_SENTINEL = [0.5] * 384


def _is_sentinel(vec) -> bool:
    return np.allclose(np.asarray(vec, dtype=float), _SENTINEL)


async def _cosine_to(vec, text: str) -> float:
    """Cosine similarity of a stored vector to a freshly-encoded `text`."""
    return cosine_similarity(vec, await generate_embedding(text))


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
        title_texts=[media.title], description_text=None,
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
    a_row.description_embedding = _SENTINEL
    m_row.description_embedding = _SENTINEL
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
    assert not _is_sentinel(a_after.description_embedding)
    assert not _is_sentinel(m_after.description_embedding)
    assert not _is_sentinel(r_after.note_embedding)
    assert await _cosine_to(
        a_after.description_embedding,
        f"{' '.join(t for t in anime_title_texts(anime) if t)} {anime.description}",
    ) > 0.999
    # The media has no description, so the re-embed encodes its title alone.
    assert await _cosine_to(m_after.description_embedding, media.title) > 0.999
    assert await _cosine_to(r_after.note_embedding, rating.note) > 0.999


async def _probe_row(db_session) -> AnimeSearch:
    """The row `embeddings_are_stale` reads — the lowest-id anime's. Two fixture anime
    make sure one exists and give the anime pass a second row to cut on. One fixture media
    gives the media pass a row to cut on, even on an empty database."""
    for mal_id in (99011, 99012):
        anime = Anime(mal_id=mal_id, title=f"Probe {mal_id}", description="A probe description.")
        db_session.add(anime)
        await db_session.flush()
        await create_anime_embedding(
            db_session, anime_id=anime.id,
            title_texts=anime_title_texts(anime), description_text=anime.description or "",
        )
    db_session.add(Media(**media_kwargs(anime.id, 990120, title="Probe Media")))
    await db_session.flush()
    return (await db_session.execute(
        select(AnimeSearch).order_by(AnimeSearch.anime_id).limit(1))).scalar_one()


async def test_the_probe_tells_current_vectors_from_stale_ones(db_session):
    anime = await db_session.get(Anime, (await _probe_row(db_session)).anime_id)
    await regenerate_anime_embedding(
        db_session, anime_id=anime.id,
        title_texts=anime_title_texts(anime), description_text=anime.description or "",
    )
    assert not await embeddings_are_stale(db_session)

    row = (await db_session.execute(select(AnimeSearch).where(AnimeSearch.anime_id == anime.id))).scalar_one()
    row.description_embedding = _SENTINEL
    await db_session.flush()
    assert await embeddings_are_stale(db_session)


async def _skip(*_args, **_kwargs):
    return None


def _dies_on(call: int, real):
    calls = itertools.count(1)

    async def regenerate(*args, **kwargs):
        if next(calls) == call:
            raise RuntimeError("cut")
        await real(*args, **kwargs)
    return regenerate


@pytest.mark.parametrize("cut", ["media", "anime"])
async def test_a_pass_cut_short_leaves_the_probe_stale(db_session, monkeypatch, cut):
    """Cut on the first media row, or on the second anime row after one real write:
    either way the probe still reads stale. The anime pass stays real in the media
    case, so a pass that ran anime first would fail here."""
    row = await _probe_row(db_session)
    row.description_embedding = _SENTINEL
    await db_session.flush()

    monkeypatch.setattr(embedding_backfiller, "regenerate_rating_embedding", _skip)
    if cut == "media":
        monkeypatch.setattr(embedding_backfiller, "regenerate_media_embedding", _dies_on(1, _skip))
    else:
        monkeypatch.setattr(embedding_backfiller, "regenerate_media_embedding", _skip)
        monkeypatch.setattr(
            embedding_backfiller, "regenerate_anime_embedding",
            _dies_on(2, embedding_backfiller.regenerate_anime_embedding),
        )

    with pytest.raises(RuntimeError, match="cut"):
        await reembed_all_embeddings(db_session)
    assert await embeddings_are_stale(db_session)
