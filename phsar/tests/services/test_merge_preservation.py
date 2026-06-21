"""Data-preservation invariants for merge_candidate_service.merge.

Merging A←B re-parents B's media onto A and deletes the B anime row. The
intentional state changes:

- B's anime row is deleted (cascade).
- B's anime_search row is deleted (cascade).
- merge_candidate rows referencing B on either side are cascade-deleted.
- A's anime_search row is regenerated from the merged title set.
- B's media rows now have anime_id == A.id.

Everything else attached to B's media (ratings, watchlist entries,
studio links, genre links, per-media embeddings) must survive the merge
unchanged. These tests pin those invariants so a future refactor of the
merge flow can't silently drop user data.
"""

import pytest
from sqlalchemy import select

from app.models.anime import Anime
from app.models.anime_search import AnimeSearch
from app.models.genre import Genre, GenreType
from app.models.media import Media
from app.models.media_genre import MediaGenre
from app.models.media_search import MediaSearch
from app.models.media_studio import MediaStudio
from app.models.merge_candidate import MergeCandidate, MergeCandidateStatus
from app.models.ratings import Ratings, WatchStatus
from app.models.studio import Studio
from app.models.users import RoleType, Users
from app.models.watchlist import Watchlist
from app.services.merge_candidate_service import merge
from tests._helpers import media_kwargs


async def _seed_merge_pair(
    db_session, *, mal_a: int, mal_b: int, b_media_count: int = 2,
) -> dict:
    """Two anime sharing one studio + a pending merge candidate. Returns
    handles for the survivor (A), the loser (B), and B's media list — used
    by every test in this file."""
    studio = Studio(name=f"Preservation Studio {mal_a}")
    db_session.add(studio)
    await db_session.flush()

    a = Anime(mal_id=mal_a, title=f"Preservation A {mal_a}")
    b = Anime(mal_id=mal_b, title=f"Preservation B {mal_b}")
    db_session.add_all([a, b])
    await db_session.flush()

    media_a = Media(**media_kwargs(a.id, mal_a * 10))
    db_session.add(media_a)
    media_b_list: list[Media] = []
    for i in range(b_media_count):
        m = Media(**media_kwargs(b.id, mal_b * 10 + i, title=f"B Media {i}"))
        db_session.add(m)
        media_b_list.append(m)
    await db_session.flush()

    db_session.add(MediaStudio(media_id=media_a.id, studio_id=studio.id))
    for m in media_b_list:
        db_session.add(MediaStudio(media_id=m.id, studio_id=studio.id))
    await db_session.flush()

    a_id, b_id = sorted((a.id, b.id))
    candidate = MergeCandidate(
        anime_a_id=a_id, anime_b_id=b_id,
        similarity_score=0.95, detected_by="title_studio",
        status=MergeCandidateStatus.pending,
    )
    db_session.add(candidate)
    await db_session.flush()

    survivor = a if a.id == a_id else b
    loser = b if b.id == b_id else a
    return {
        "survivor": survivor,
        "loser": loser,
        "media_a": media_a,
        "media_b_list": media_b_list,
        "candidate_uuid": candidate.uuid,
        "studio": studio,
    }


@pytest.mark.asyncio
async def test_merge_preserves_b_media_columns(db_session):
    """Every column on B's media stays as it was — only `anime_id` flips."""
    seed = await _seed_merge_pair(db_session, mal_a=91101, mal_b=91102)
    snapshot = [
        {
            "uuid": m.uuid,
            "mal_id": m.mal_id,
            "title": m.title,
            "media_type": m.media_type,
            "scored_by": m.scored_by,
            "airing_status": m.airing_status,
        }
        for m in seed["media_b_list"]
    ]

    await merge(db_session, uuid=seed["candidate_uuid"])

    for original in snapshot:
        row = (await db_session.execute(
            select(Media).where(Media.uuid == original["uuid"])
        )).scalars().first()
        assert row is not None, f"media {original['uuid']} disappeared"
        assert row.anime_id == seed["survivor"].id
        for col in ("mal_id", "title", "media_type", "scored_by", "airing_status"):
            assert getattr(row, col) == original[col], f"{col} drifted for {original['uuid']}"


@pytest.mark.asyncio
async def test_merge_preserves_ratings_on_b_media(db_session):
    """User ratings attached to B's media survive the re-parent: same
    media_id, same row, same fields."""
    seed = await _seed_merge_pair(db_session, mal_a=91201, mal_b=91202)
    user = Users(username="rate-keeper", hashed_password="x", role=RoleType.User)
    db_session.add(user)
    await db_session.flush()

    target = seed["media_b_list"][0]
    db_session.add(Ratings(
        rating=8.5, media_id=target.id, user_id=user.id,
        note="liked it", episodes_watched=12, watch_status=WatchStatus.completed,
    ))
    await db_session.flush()
    target_id = target.id

    await merge(db_session, uuid=seed["candidate_uuid"])

    surviving_rating = (await db_session.execute(
        select(Ratings).where(
            Ratings.media_id == target_id, Ratings.user_id == user.id,
        )
    )).scalars().first()
    assert surviving_rating is not None
    assert surviving_rating.rating == 8.5
    assert surviving_rating.note == "liked it"
    assert surviving_rating.episodes_watched == 12


@pytest.mark.asyncio
async def test_merge_preserves_watchlist_on_b_media(db_session):
    """Watchlist entries on B's media survive — merge re-parents Media but
    doesn't touch the watchlist table."""
    seed = await _seed_merge_pair(db_session, mal_a=91301, mal_b=91302)
    user = Users(username="watch-keeper", hashed_password="x", role=RoleType.User)
    db_session.add(user)
    await db_session.flush()

    target = seed["media_b_list"][0]
    db_session.add(Watchlist(
        media_id=target.id, user_id=user.id, note="queued", priority=2,
    ))
    await db_session.flush()
    target_id = target.id

    await merge(db_session, uuid=seed["candidate_uuid"])

    entry = (await db_session.execute(
        select(Watchlist).where(
            Watchlist.media_id == target_id, Watchlist.user_id == user.id,
        )
    )).scalars().first()
    assert entry is not None
    assert entry.note == "queued"
    assert entry.priority == 2


@pytest.mark.asyncio
async def test_merge_preserves_media_studio_links(db_session):
    """media_studio rows attached to B's media stay intact — the merge
    flow re-parents Media but doesn't touch the studio join table."""
    seed = await _seed_merge_pair(db_session, mal_a=91401, mal_b=91402)
    target = seed["media_b_list"][0]
    extra_studio = Studio(name="Second Studio")
    db_session.add(extra_studio)
    await db_session.flush()
    db_session.add(MediaStudio(media_id=target.id, studio_id=extra_studio.id))
    await db_session.flush()
    target_id = target.id
    extra_id = extra_studio.id
    seed_studio_id = seed["studio"].id

    await merge(db_session, uuid=seed["candidate_uuid"])

    studio_ids = (await db_session.execute(
        select(MediaStudio.studio_id).where(MediaStudio.media_id == target_id)
    )).scalars().all()
    assert set(studio_ids) == {seed_studio_id, extra_id}


@pytest.mark.asyncio
async def test_merge_preserves_media_genre_links(db_session):
    """media_genre rows on B's media stay intact — the merge flow re-parents
    Media but doesn't touch the genre join table."""
    seed = await _seed_merge_pair(db_session, mal_a=91501, mal_b=91502)
    genre = Genre(name="Preservation Genre", genre_type=GenreType.Genres)
    db_session.add(genre)
    await db_session.flush()
    target = seed["media_b_list"][0]
    db_session.add(MediaGenre(media_id=target.id, genre_id=genre.id))
    await db_session.flush()
    target_id = target.id
    genre_id = genre.id

    await merge(db_session, uuid=seed["candidate_uuid"])

    genre_ids = (await db_session.execute(
        select(MediaGenre.genre_id).where(MediaGenre.media_id == target_id)
    )).scalars().all()
    assert genre_id in genre_ids


@pytest.mark.asyncio
async def test_merge_preserves_media_search_embeddings(db_session):
    """Per-media title/description embeddings on B's media survive — they
    were generated from the media's own text and stay valid post-reparent."""
    seed = await _seed_merge_pair(db_session, mal_a=91601, mal_b=91602)
    target = seed["media_b_list"][0]
    title_emb = [0.1] * 384
    desc_emb = [0.2] * 384
    db_session.add(MediaSearch(
        media_id=target.id,
        title_embedding=title_emb,
        description_embedding=desc_emb,
    ))
    await db_session.flush()
    target_id = target.id

    await merge(db_session, uuid=seed["candidate_uuid"])

    row = (await db_session.execute(
        select(MediaSearch).where(MediaSearch.media_id == target_id)
    )).scalars().first()
    assert row is not None
    # pgvector stores as float32; round-trip through asyncpg leaves tiny
    # ULP-level drift on each component. Approximate equality is the right
    # contract for "embedding survived unchanged."
    assert list(row.title_embedding) == pytest.approx(title_emb, rel=1e-6)
    assert list(row.description_embedding) == pytest.approx(desc_emb, rel=1e-6)


@pytest.mark.asyncio
async def test_merge_a_media_untouched(db_session):
    """A's own media is not mutated by the merge. Only the survivor's
    `anime_search` is intentionally replaced; A's media columns and join
    rows stay byte-identical."""
    seed = await _seed_merge_pair(db_session, mal_a=91701, mal_b=91702)
    user = Users(username="a-side-rater", hashed_password="x", role=RoleType.User)
    db_session.add(user)
    await db_session.flush()
    db_session.add(Ratings(
        rating=7.0, media_id=seed["media_a"].id, user_id=user.id,
        note="A side note",
    ))
    await db_session.flush()

    media_a_uuid = seed["media_a"].uuid
    media_a_title = seed["media_a"].title

    await merge(db_session, uuid=seed["candidate_uuid"])

    media_a_row = (await db_session.execute(
        select(Media).where(Media.uuid == media_a_uuid)
    )).scalars().first()
    assert media_a_row is not None
    assert media_a_row.title == media_a_title
    assert media_a_row.anime_id == seed["survivor"].id

    a_rating = (await db_session.execute(
        select(Ratings).where(
            Ratings.media_id == media_a_row.id, Ratings.user_id == user.id,
        )
    )).scalars().first()
    assert a_rating is not None
    assert a_rating.rating == 7.0
    assert a_rating.note == "A side note"


@pytest.mark.asyncio
async def test_merge_anime_search_for_loser_deleted(db_session):
    """anime_search rows for the loser anime are cascade-removed — the
    embedding becomes stale the moment the anime row is gone."""
    seed = await _seed_merge_pair(db_session, mal_a=91801, mal_b=91802)
    db_session.add(AnimeSearch(
        anime_id=seed["loser"].id,
        title_embedding=[0.5] * 384,
        description_embedding=[0.5] * 384,
    ))
    await db_session.flush()
    loser_id = seed["loser"].id

    await merge(db_session, uuid=seed["candidate_uuid"])

    rows = (await db_session.execute(
        select(AnimeSearch).where(AnimeSearch.anime_id == loser_id)
    )).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_merge_anime_search_for_survivor_refreshed(db_session):
    """The survivor's anime_search row is regenerated from the merged
    title set — must exist post-merge with non-empty embeddings."""
    seed = await _seed_merge_pair(db_session, mal_a=91901, mal_b=91902)
    survivor_id = seed["survivor"].id

    await merge(db_session, uuid=seed["candidate_uuid"])

    row = (await db_session.execute(
        select(AnimeSearch).where(AnimeSearch.anime_id == survivor_id)
    )).scalars().first()
    assert row is not None
    assert len(list(row.title_embedding)) == 384
    assert len(list(row.description_embedding)) == 384
