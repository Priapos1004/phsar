"""Tests for split_candidate_service: dismiss + execute_split lifecycle.

Detection-side coverage lives in test_relation_classifier.py (the pure
`find_disjoint_franchises` function). This file pins the service that
acts on those detections — creating new anime, re-parenting media,
preserving Ratings via Media UUID stability.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.exceptions import (
    SplitCandidateAlreadyResolvedError,
    SplitCandidateNotFoundError,
)
from app.models.anime import Anime
from app.models.media import Media, RelationType
from app.models.media_relation_edges import MediaRelationEdges
from app.models.split_candidate import SplitCandidate, SplitCandidateStatus
from app.services.split_candidate_service import dismiss, execute_split
from tests._helpers import media_kwargs


async def _make_bnha_with_vigilante_candidate(db_session):
    """Build a BNHA-shape contaminated anime + pending SplitCandidate for
    the Vigilante cluster. Returns the source Anime + its media + the
    SplitCandidate uuid.

    Shape: BNHA S1 (TV, main, anchor) ← spin-off → Vigilante S1 (TV,
    side_story) ← sequel → Vigilante S2 (TV, side_story).
    """
    bnha = Anime(mal_id=931964, title="BNHA-like")
    db_session.add(bnha)
    await db_session.flush()

    bnha_s1 = Media(**media_kwargs(
        bnha.id, 931964, title="BNHA S1",
        relation_type=RelationType.Main, episodes=13, duration_seconds=1440,
    ))
    vig_s1 = Media(**media_kwargs(
        bnha.id, 960593, title="Vigilante S1",
        relation_type=RelationType.SideStory, episodes=13, duration_seconds=1440,
    ))
    vig_s2 = Media(**media_kwargs(
        bnha.id, 961942, title="Vigilante S2",
        relation_type=RelationType.SideStory, episodes=13, duration_seconds=1440,
    ))
    db_session.add_all([bnha_s1, vig_s1, vig_s2])
    await db_session.flush()

    # Sidecars: BNHA→Vigilante via spin-off, Vigilante S1↔S2 via sequel.
    db_session.add_all([
        MediaRelationEdges(media_id=bnha_s1.id, edges=[[960593, "spin-off"]]),
        MediaRelationEdges(media_id=vig_s1.id, edges=[
            [931964, "parent_story"], [961942, "sequel"],
        ]),
        MediaRelationEdges(media_id=vig_s2.id, edges=[[960593, "prequel"]]),
    ])

    candidate = SplitCandidate(
        anime_id=bnha.id,
        clusters=[{
            "member_mal_ids": [960593, 961942],
            "substance_member_mal_ids": [960593, 961942],
            "suggested_anchor_mal_id": 960593,
            "bridge_edges": [[931964, 960593, "spin-off"]],
        }],
        status=SplitCandidateStatus.pending,
        detected_by="scrape",
    )
    db_session.add(candidate)
    await db_session.flush()
    return bnha, [bnha_s1, vig_s1, vig_s2], candidate.uuid


@pytest.mark.asyncio
async def test_execute_split_creates_new_anime_and_reparents_media(db_session):
    """Splitting the Vigilante cluster: a new Anime row appears for
    Vigilante, the two Vigilante Media rows re-parent under it, and the
    source anime loses those 2 from its media list."""
    bnha, media, candidate_uuid = await _make_bnha_with_vigilante_candidate(db_session)
    bnha_s1, vig_s1, vig_s2 = media
    original_bnha_uuid = str(bnha.uuid)

    surviving_uuid, new_anime_uuids = await execute_split(db_session, candidate_uuid)

    # New anime for Vigilante.
    assert len(new_anime_uuids) == 1
    new_anime_uuid = new_anime_uuids[0]
    assert new_anime_uuid != original_bnha_uuid

    # The Vigilante anime row exists with 2 media (S1+S2).
    new_anime = (await db_session.execute(
        select(Anime).where(Anime.uuid == new_anime_uuid)
        .options(selectinload(Anime.media))
    )).scalar_one()
    assert new_anime.mal_id == 960593  # the suggested anchor
    assert {m.mal_id for m in new_anime.media} == {960593, 961942}

    # BNHA still has its S1 media, now alone.
    bnha_after = (await db_session.execute(
        select(Anime).where(Anime.uuid == original_bnha_uuid)
        .options(selectinload(Anime.media))
    )).scalar_one()
    assert {m.mal_id for m in bnha_after.media} == {931964}

    # Candidate marked split.
    cand = (await db_session.execute(
        select(SplitCandidate).where(SplitCandidate.uuid == candidate_uuid)
    )).scalar_one()
    assert cand.status == SplitCandidateStatus.split

    # Surviving uuid returned is BNHA's.
    assert surviving_uuid == original_bnha_uuid


@pytest.mark.asyncio
async def test_execute_split_preserves_media_uuids(db_session):
    """The Vigilante Media rows keep their UUIDs across the split —
    only their anime_id changes. Pins the rating-safety property: any
    Rating row pointing at Media.uuid stays attached to the same media
    after split, just under a different anime parent."""
    bnha, media, candidate_uuid = await _make_bnha_with_vigilante_candidate(db_session)
    _, vig_s1, vig_s2 = media
    vig_s1_uuid_before = str(vig_s1.uuid)
    vig_s2_uuid_before = str(vig_s2.uuid)

    await execute_split(db_session, candidate_uuid)

    # Re-fetch by id (id is stable, UUID lookup also works).
    vig_s1_after = await db_session.get(Media, vig_s1.id)
    vig_s2_after = await db_session.get(Media, vig_s2.id)
    assert str(vig_s1_after.uuid) == vig_s1_uuid_before
    assert str(vig_s2_after.uuid) == vig_s2_uuid_before
    # Both Media rows now point at the new Vigilante anime.
    assert vig_s1_after.anime_id == vig_s2_after.anime_id
    assert vig_s1_after.anime_id != bnha.id


@pytest.mark.asyncio
async def test_dismiss_leaves_db_untouched(db_session):
    """Dismiss just flips status. No anime created, no media re-parented."""
    bnha, media, candidate_uuid = await _make_bnha_with_vigilante_candidate(db_session)
    bnha_s1, vig_s1, vig_s2 = media

    await dismiss(db_session, candidate_uuid)

    cand = (await db_session.execute(
        select(SplitCandidate).where(SplitCandidate.uuid == candidate_uuid)
    )).scalar_one()
    assert cand.status == SplitCandidateStatus.dismissed

    # BNHA still owns all 3 media — nothing was moved.
    bnha_after = (await db_session.execute(
        select(Anime).where(Anime.id == bnha.id)
        .options(selectinload(Anime.media))
    )).scalar_one()
    assert {m.mal_id for m in bnha_after.media} == {931964, 960593, 961942}


@pytest.mark.asyncio
async def test_dismiss_resolved_candidate_raises(db_session):
    """Once dismissed or split, the candidate is terminal — a second
    dismiss raises 409 instead of silently re-flipping."""
    _, _, candidate_uuid = await _make_bnha_with_vigilante_candidate(db_session)
    await dismiss(db_session, candidate_uuid)
    with pytest.raises(SplitCandidateAlreadyResolvedError):
        await dismiss(db_session, candidate_uuid)


@pytest.mark.asyncio
async def test_execute_split_on_unknown_uuid_raises(db_session):
    """An unknown candidate UUID raises 404."""
    import uuid as uuid_module
    with pytest.raises(SplitCandidateNotFoundError):
        await execute_split(db_session, uuid_module.uuid4())
