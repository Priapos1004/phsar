"""Tests for merge_candidate_service: list ordering + merge with keep_uuid.

Detection-side coverage lives in test_merge_detection.py. Router-level
coverage lives in tests/routers/test_admin.py. This file pins down the
service's recommended-A ordering and the merge service's keep_uuid swap.
"""

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import select

from app.exceptions import InvalidMergeKeepError
from app.models.anime import Anime
from app.models.media import Media
from app.models.media_studio import MediaStudio
from app.models.merge_candidate import MergeCandidate, MergeCandidateStatus
from app.models.ratings import Ratings
from app.models.studio import Studio
from app.models.users import RoleType, Users
from app.services.merge_candidate_service import list_pending, merge
from tests._helpers import media_kwargs


async def _make_pair(
    db_session,
    *,
    a_mal: int,
    b_mal: int,
    a_aired_from: datetime | None = None,
    b_aired_from: datetime | None = None,
) -> tuple[Anime, Anime, Media, Media, UUID]:
    studio = Studio(name=f"Service Studio {a_mal}")
    db_session.add(studio)
    await db_session.flush()

    a = Anime(mal_id=a_mal, title=f"Service A {a_mal}")
    b = Anime(mal_id=b_mal, title=f"Service B {b_mal}")
    db_session.add_all([a, b])
    await db_session.flush()

    media_a = Media(**media_kwargs(a.id, a_mal * 10, aired_from=a_aired_from))
    media_b = Media(**media_kwargs(b.id, b_mal * 10, aired_from=b_aired_from))
    db_session.add_all([media_a, media_b])
    await db_session.flush()

    db_session.add_all([
        MediaStudio(media_id=media_a.id, studio_id=studio.id),
        MediaStudio(media_id=media_b.id, studio_id=studio.id),
    ])
    await db_session.flush()

    a_id, b_id = sorted((a.id, b.id))
    candidate = MergeCandidate(
        anime_a_id=a_id, anime_b_id=b_id,
        similarity_score=0.95, detected_by="title_studio",
        status=MergeCandidateStatus.pending,
    )
    db_session.add(candidate)
    await db_session.flush()
    return a, b, media_a, media_b, candidate.uuid


@pytest.mark.asyncio
async def test_list_pending_orders_by_earliest_aired_from(db_session):
    """When both sides have aired_from, the side that aired earlier is
    surfaced as anime_a (the recommended-keep side)."""
    earlier = datetime(2010, 1, 1, tzinfo=timezone.utc)
    later = datetime(2018, 1, 1, tzinfo=timezone.utc)
    a, b, _, _, candidate_uuid = await _make_pair(
        db_session, a_mal=90101, b_mal=90102,
        a_aired_from=later, b_aired_from=earlier,
    )

    items = await list_pending(db_session)
    item = next(it for it in items if it.uuid == str(candidate_uuid))
    assert item.anime_a.uuid == str(b.uuid)
    assert item.anime_b.uuid == str(a.uuid)


@pytest.mark.asyncio
async def test_list_pending_tiebreak_on_rating_count(db_session):
    """Same aired_from (both NULL): the side with more user ratings wins
    A — preserves more user data after the merge."""
    a, b, _, media_b, candidate_uuid = await _make_pair(
        db_session, a_mal=90201, b_mal=90202,
    )
    user = Users(username=f"merge-tester-{a.id}", hashed_password="x", role=RoleType.User)
    db_session.add(user)
    await db_session.flush()
    db_session.add(Ratings(rating=8.0, media_id=media_b.id, user_id=user.id))
    await db_session.flush()

    items = await list_pending(db_session)
    item = next(it for it in items if it.uuid == str(candidate_uuid))
    assert item.anime_a.uuid == str(b.uuid)
    assert item.anime_a.rating_count == 1
    assert item.anime_b.rating_count == 0


@pytest.mark.asyncio
async def test_list_pending_falls_back_to_anime_id(db_session):
    """Tied on aired_from + rating_count: lower-id anime stays as A."""
    a, b, _, _, candidate_uuid = await _make_pair(
        db_session, a_mal=90301, b_mal=90302,
    )
    items = await list_pending(db_session)
    item = next(it for it in items if it.uuid == str(candidate_uuid))
    a_id, _ = sorted((a.id, b.id))
    keeper_uuid = str((a if a.id == a_id else b).uuid)
    assert item.anime_a.uuid == keeper_uuid


@pytest.mark.asyncio
async def test_merge_keep_uuid_swaps_direction(db_session):
    """keep_uuid pointing at the table's anime_b causes the merge to keep
    that side and delete the original anime_a instead."""
    a, b, _, _, candidate_uuid = await _make_pair(
        db_session, a_mal=90401, b_mal=90402,
    )
    a_id, b_id = sorted((a.id, b.id))
    table_a = a if a.id == a_id else b
    table_b = b if b.id == b_id else a

    surviving_uuid = await merge(db_session, uuid=candidate_uuid, keep_uuid=table_b.uuid)
    assert surviving_uuid == str(table_b.uuid)
    assert await db_session.get(Anime, table_a.id) is None
    assert await db_session.get(Anime, table_b.id) is not None


@pytest.mark.asyncio
async def test_merge_keep_uuid_default_keeps_anime_a(db_session):
    """Omitting keep_uuid preserves the table's anime_a (back-compat with
    the original behavior)."""
    a, b, _, _, candidate_uuid = await _make_pair(
        db_session, a_mal=90501, b_mal=90502,
    )
    a_id, b_id = sorted((a.id, b.id))
    table_a = a if a.id == a_id else b
    table_b = b if b.id == b_id else a

    surviving_uuid = await merge(db_session, uuid=candidate_uuid)
    assert surviving_uuid == str(table_a.uuid)
    assert await db_session.get(Anime, table_b.id) is None


@pytest.mark.asyncio
async def test_merge_redetects_against_third_anime(db_session):
    """Three-way duplicate scenario: pending candidates A-B and B-C exist.
    Merging A-B cascades B-C away (B is deleted), but B's media now sits
    under A. If A and C now match per the detector, A-C should be flagged
    so the admin doesn't lose the duplicate signal."""
    studio = Studio(name="Re-detect Studio")
    db_session.add(studio)
    await db_session.flush()

    # A and B share studio + match titles via containment ("Show" ⊂ "Show 2").
    a = Anime(mal_id=90701, title="Re-detect Show")
    b = Anime(mal_id=90702, title="Re-detect Show 2")
    # C shares studio with A but its title only matches B's media title —
    # so before the merge, A-C wouldn't flag (low title score), but after
    # the merge B's media sits under A and the detector should re-score.
    c = Anime(mal_id=90703, title="Re-detect Show Side Story")
    db_session.add_all([a, b, c])
    await db_session.flush()

    media_a = Media(**media_kwargs(a.id, 907010, title="Re-detect Show TV"))
    media_b = Media(**media_kwargs(b.id, 907020, title="Re-detect Show 2 TV"))
    media_c = Media(**media_kwargs(c.id, 907030, title="Re-detect Show Side Story TV"))
    db_session.add_all([media_a, media_b, media_c])
    await db_session.flush()
    db_session.add_all([
        MediaStudio(media_id=media_a.id, studio_id=studio.id),
        MediaStudio(media_id=media_b.id, studio_id=studio.id),
        MediaStudio(media_id=media_c.id, studio_id=studio.id),
    ])
    await db_session.flush()

    a_id, b_id = sorted((a.id, b.id))
    candidate_ab = MergeCandidate(
        anime_a_id=a_id, anime_b_id=b_id,
        similarity_score=0.9, detected_by="title_studio",
        status=MergeCandidateStatus.pending,
    )
    db_session.add(candidate_ab)
    await db_session.flush()

    survivor_uuid = await merge(db_session, uuid=candidate_ab.uuid)
    assert survivor_uuid == str((a if a.id == a_id else b).uuid)

    # The original A-B candidate is gone via cascade (B was deleted). Any
    # newly detected pair must reference the surviving anime + C.
    survivor_id = a.id if a.id == a_id else b.id
    new_pair = sorted((survivor_id, c.id))
    fresh = (await db_session.execute(
        select(MergeCandidate).where(
            MergeCandidate.anime_a_id == new_pair[0],
            MergeCandidate.anime_b_id == new_pair[1],
        )
    )).scalars().first()
    assert fresh is not None, "expected post-merge re-detection to flag survivor vs C"
    assert fresh.status == MergeCandidateStatus.pending


@pytest.mark.asyncio
async def test_merge_keep_uuid_unrelated_raises(db_session):
    """A keep_uuid that resolves to neither side must reject — almost
    always a stale frontend payload, never silently accept."""
    _, _, _, _, candidate_uuid = await _make_pair(
        db_session, a_mal=90601, b_mal=90602,
    )
    unrelated = Anime(mal_id=90699, title="Unrelated")
    db_session.add(unrelated)
    await db_session.flush()

    with pytest.raises(InvalidMergeKeepError):
        await merge(db_session, uuid=candidate_uuid, keep_uuid=unrelated.uuid)
