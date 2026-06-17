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
from app.models.media import Media, MediaType, RelationType
from app.models.media_relation_edges import MediaRelationEdges
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
    # Anime mal_id + title mirror the anchor media so reclassify_anime
    # treats the row as in-sync (matches create_anime_from_media's flow).
    a = Anime(mal_id=907010, title="Re-detect Show")
    b = Anime(mal_id=907020, title="Re-detect Show 2")
    # C shares studio with A but its title only matches B's media title —
    # so before the merge, A-C wouldn't flag (low title score), but after
    # the merge B's media sits under A and the detector should re-score.
    c = Anime(mal_id=907030, title="Re-detect Show Side Story")
    db_session.add_all([a, b, c])
    await db_session.flush()

    media_a = Media(**media_kwargs(a.id, 907010, title="Re-detect Show"))
    media_b = Media(**media_kwargs(b.id, 907020, title="Re-detect Show 2"))
    media_c = Media(**media_kwargs(c.id, 907030, title="Re-detect Show Side Story"))
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


@pytest.mark.asyncio
async def test_list_pending_includes_reclassification_preview(db_session):
    """list_pending stamps each candidate with the per-media changes
    that would land if the admin clicks merge — substance-gate
    demotions, alt-version labels, anchor flips."""
    studio = Studio(name="Preview Studio")
    db_session.add(studio)
    await db_session.flush()

    a = Anime(mal_id=940101, title="Preview TV")
    b = Anime(mal_id=940201, title="Preview Manner Movie")
    db_session.add_all([a, b])
    await db_session.flush()

    media_a = Media(**media_kwargs(
        a.id, 940101, title="Preview TV",
        media_type=MediaType.TV, relation_type=RelationType.Main,
        episodes=13, duration_seconds=1440,
        aired_from=datetime(2015, 1, 1, tzinfo=timezone.utc),
    ))
    # B's weak Main (1-min Movie) — substance gate will demote it.
    media_b = Media(**media_kwargs(
        b.id, 940201, title="Preview Manner Movie",
        media_type=MediaType.Movie, relation_type=RelationType.Main,
        episodes=1, duration_seconds=60,
        aired_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
    ))
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
        similarity_score=0.9, detected_by="title_studio",
        status=MergeCandidateStatus.pending,
    )
    db_session.add(candidate)
    await db_session.flush()

    items = await list_pending(db_session)
    item = next(it for it in items if it.uuid == str(candidate.uuid))
    # B's weak Main media is flagged for demotion to side_story.
    preview_by_uuid = {p.media_uuid: p for p in item.pending_reclassifications}
    pending = preview_by_uuid.get(str(media_b.uuid))
    assert pending is not None
    assert pending.old_relation_type == "main"
    assert pending.new_relation_type == "side_story"
    # A's strong Main stays Main → not in the preview.
    assert str(media_a.uuid) not in preview_by_uuid


@pytest.mark.asyncio
async def test_merge_reconnects_main_chain_via_bridge_edges(db_session):
    """Dr. Stone split-merge shape: A holds S1 + a substance-failing
    TVSpecial bridge that has a sequel edge to B's S2. The bridge edge
    was persisted in the sidecar even though it pointed outside A's
    graph at scrape time. After merge, the consolidated classifier
    must traverse the bridge so S2 ends up as `main` (not `side_story`
    via the broken-chain fallback). Bridge itself stays side_story via
    the substance gate; the chain continues past it."""
    studio = Studio(name="Bridge Studio")
    db_session.add(studio)
    await db_session.flush()

    a = Anime(mal_id=970101, title="Bridge S1")
    b = Anime(mal_id=970301, title="Bridge S2")
    db_session.add_all([a, b])
    await db_session.flush()

    s1 = Media(**media_kwargs(
        a.id, 970101, title="Bridge S1",
        media_type=MediaType.TV, relation_type=RelationType.Main,
        episodes=24, duration_seconds=1440,
        aired_from=datetime(2019, 7, 5, tzinfo=timezone.utc),
    ))
    # The bridge: TVSpecial with 1 ep — fails substance, will be
    # side_story. But the closure walks through it as long as the
    # sequel edges are present.
    bridge = Media(**media_kwargs(
        a.id, 970201, title="Bridge Special",
        media_type=MediaType.TVSpecial, relation_type=RelationType.SideStory,
        episodes=1, duration_seconds=1440,
        aired_from=datetime(2022, 7, 10, tzinfo=timezone.utc),
    ))
    s2 = Media(**media_kwargs(
        b.id, 970301, title="Bridge S2",
        media_type=MediaType.TV, relation_type=RelationType.Main,
        episodes=22, duration_seconds=1440,
        aired_from=datetime(2023, 4, 6, tzinfo=timezone.utc),
    ))
    db_session.add_all([s1, bridge, s2])
    await db_session.flush()
    # Bridge sidecar persists the sequel-to-S2 edge despite S2 living
    # under B at scrape time — this is exactly what the post-fix BFS
    # now writes (no more dangling-edge filter at storage).
    db_session.add_all([
        MediaRelationEdges(media_id=s1.id, edges=[[970201, "sequel"]]),
        MediaRelationEdges(media_id=bridge.id, edges=[
            [970101, "prequel"], [970301, "sequel"],
        ]),
        MediaRelationEdges(media_id=s2.id, edges=[[970201, "prequel"]]),
        MediaStudio(media_id=s1.id, studio_id=studio.id),
        MediaStudio(media_id=bridge.id, studio_id=studio.id),
        MediaStudio(media_id=s2.id, studio_id=studio.id),
    ])
    await db_session.flush()

    a_id, b_id = sorted((a.id, b.id))
    candidate = MergeCandidate(
        anime_a_id=a_id, anime_b_id=b_id,
        similarity_score=0.9, detected_by="title_studio",
        status=MergeCandidateStatus.pending,
    )
    db_session.add(candidate)
    await db_session.flush()

    await merge(db_session, uuid=candidate.uuid)

    # Re-read both media to verify classification.
    refreshed = {
        m.mal_id: m for m in (await db_session.execute(
            select(Media).where(Media.mal_id.in_([970101, 970201, 970301]))
        )).scalars().all()
    }
    assert refreshed[970101].relation_type == RelationType.Main, "S1 anchor stays main"
    assert refreshed[970301].relation_type == RelationType.Main, "S2 reached via bridge — main"
    assert refreshed[970201].relation_type == RelationType.SideStory, "bridge demoted by substance gate"


@pytest.mark.asyncio
async def test_merge_demotes_weak_main_from_loser(db_session):
    """Overlord 13063 ⇄ 13064 shape: A is a substance-passing TV that's
    already classified as Main. B is a standalone 1-min Movie also
    classified Main (since it was the only media in B's anime). After
    merging A←B, the classifier runs over A's consolidated media set
    and demotes B's weak Main to SideStory via the substance gate."""
    studio = Studio(name="Weak-Demote Studio")
    db_session.add(studio)
    await db_session.flush()

    a = Anime(mal_id=950101, title="Demote TV")
    b = Anime(mal_id=950201, title="Demote Manner Movie")
    db_session.add_all([a, b])
    await db_session.flush()

    media_a = Media(**media_kwargs(
        a.id, 950101, title="Demote TV",
        media_type=MediaType.TV, relation_type=RelationType.Main,
        episodes=13, duration_seconds=1440,
        aired_from=datetime(2015, 1, 1, tzinfo=timezone.utc),
    ))
    media_b = Media(**media_kwargs(
        b.id, 950201, title="Demote Manner Movie",
        media_type=MediaType.Movie, relation_type=RelationType.Main,
        episodes=1, duration_seconds=60,
        aired_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
    ))
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
        similarity_score=0.9, detected_by="title_studio",
        status=MergeCandidateStatus.pending,
    )
    db_session.add(candidate)
    await db_session.flush()

    await merge(db_session, uuid=candidate.uuid)

    refreshed_b_media = (await db_session.execute(
        select(Media).where(Media.mal_id == 950201)
    )).scalar_one()
    assert refreshed_b_media.relation_type == RelationType.SideStory


@pytest.mark.asyncio
async def test_merge_survives_spoiler_refresh_failure(db_session, monkeypatch):
    """Post-commit `refresh_spoiler_cache_for_anime_ids` failure must NOT
    raise out of merge — the merge itself is already durably committed,
    so a 5xx would trick admin into retrying an already-resolved
    candidate and hitting AlreadyResolvedError. Mirrors the sweep
    dispatcher's soft-warn pattern."""
    from app.services import merge_candidate_service

    async def _boom(_db, _anime_ids):
        raise RuntimeError("spoiler cache unavailable")

    monkeypatch.setattr(
        merge_candidate_service,
        "refresh_spoiler_cache_for_anime_ids",
        _boom,
    )

    a, b, _, _, candidate_uuid = await _make_pair(
        db_session, a_mal=90601, b_mal=90602,
    )
    a_id, b_id = sorted((a.id, b.id))
    table_a = a if a.id == a_id else b
    table_b = b if b.id == b_id else a

    surviving_uuid = await merge(db_session, uuid=candidate_uuid)
    # Merge landed despite the failure.
    assert surviving_uuid == str(table_a.uuid)
    assert await db_session.get(Anime, table_b.id) is None
