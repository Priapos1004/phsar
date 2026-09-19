"""backfill_split_candidates — catalogue-wide disjoint-franchise detection.

Runs from the lifespan after relation_backfiller lands the TERMINAL sidecars,
and from the admin re-detect button. The startup caller is the reason this is
tested here rather than only through the endpoint: a regression that only shows
on boot would otherwise be invisible to the suite.

Every call passes `anime_ids` to scope the scan. Unscoped it walks the whole
catalogue, which against a dev DB restored from a prod dump means materialising
every Anime, Media and relation sidecar to assert on one fixture row.

Fixtures use NEGATIVE mal_ids, as in test_relation_backfiller.py — the session is
transactional but reads through the live catalogue, so inserts share the
unique-mal_id namespace. They must still ASCEND from the intended anchor:
`_pick_anchor` takes a `min` whose sort key falls through to mal_id when the other
fields tie, so the anchor is the lowest id. Number a fixture downwards and the
classifier anchors on the offshoot, finds one connected chain, and flags nothing —
a green test asserting zero.
"""

from sqlalchemy import select

from app.models.anime import Anime
from app.models.media import Media, RelationType
from app.models.media_relation_edges import MediaRelationEdges
from app.models.split_candidate import SplitCandidate, SplitCandidateStatus
from app.seeders.split_candidate_backfiller import backfill_split_candidates
from tests._helpers import media_kwargs


async def _contaminated_anime(db_session, *, base=-82199):
    """An anime bundling two disjoint main chains: an anchor plus an offshoot
    pair reachable only by spin-off. The shape find_disjoint_franchises flags.

    Media ids ascend from `base` so the anchor holds the lowest — see the anchor
    note in the module docstring.
    """
    anchor_id, off1_id, off2_id = base, base + 1, base + 2

    source = Anime(mal_id=base - 1, title="Backfill Source")
    db_session.add(source)
    await db_session.flush()

    anchor = Media(**media_kwargs(
        source.id, anchor_id, title="Anchor S1",
        relation_type=RelationType.Main, episodes=13, duration_seconds=1440,
    ))
    off_s1 = Media(**media_kwargs(
        source.id, off1_id, title="Offshoot S1",
        relation_type=RelationType.SideStory, episodes=13, duration_seconds=1440,
    ))
    off_s2 = Media(**media_kwargs(
        source.id, off2_id, title="Offshoot S2",
        relation_type=RelationType.SideStory, episodes=13, duration_seconds=1440,
    ))
    db_session.add_all([anchor, off_s1, off_s2])
    await db_session.flush()

    db_session.add_all([
        MediaRelationEdges(media_id=anchor.id, edges=[[off1_id, "spin-off"]]),
        MediaRelationEdges(media_id=off_s1.id, edges=[
            [anchor_id, "parent_story"], [off2_id, "sequel"],
        ]),
        MediaRelationEdges(media_id=off_s2.id, edges=[[off1_id, "prequel"]]),
    ])
    await db_session.flush()
    return source


async def _candidates_for(db_session, anime_id):
    return (await db_session.execute(
        select(SplitCandidate).where(SplitCandidate.anime_id == anime_id)
    )).scalars().all()


async def test_backfill_flags_a_disjoint_franchise(db_session):
    source = await _contaminated_anime(db_session)

    summary = await backfill_split_candidates(db_session, anime_ids={source.id})

    assert summary["candidates_inserted"] == 1
    rows = await _candidates_for(db_session, source.id)
    assert len(rows) == 1
    assert rows[0].status == SplitCandidateStatus.pending
    assert rows[0].detected_by == "backfill"


async def test_backfill_is_idempotent(db_session):
    source = await _contaminated_anime(db_session, base=-82299)

    first = await backfill_split_candidates(db_session, anime_ids={source.id})
    second = await backfill_split_candidates(db_session, anime_ids={source.id})

    assert first["candidates_inserted"] == 1
    # Re-running must not stack a duplicate row on the same anime; the startup
    # caller runs on every boot.
    assert second["candidates_inserted"] == 0
    assert len(await _candidates_for(db_session, source.id)) == 1


async def test_backfill_leaves_a_clean_anime_alone(db_session):
    """One connected main chain — no disjoint clusters, so nothing to flag."""
    clean = Anime(mal_id=-82399, title="Backfill Clean")
    db_session.add(clean)
    await db_session.flush()

    s1 = Media(**media_kwargs(
        clean.id, -82398, title="Clean S1",
        relation_type=RelationType.Main, episodes=13, duration_seconds=1440,
    ))
    s2 = Media(**media_kwargs(
        clean.id, -82397, title="Clean S2",
        relation_type=RelationType.Main, episodes=13, duration_seconds=1440,
    ))
    db_session.add_all([s1, s2])
    await db_session.flush()
    db_session.add_all([
        MediaRelationEdges(media_id=s1.id, edges=[[-82397, "sequel"]]),
        MediaRelationEdges(media_id=s2.id, edges=[[-82398, "prequel"]]),
    ])
    await db_session.flush()

    summary = await backfill_split_candidates(db_session, anime_ids={clean.id})

    assert summary["candidates_inserted"] == 0
    assert await _candidates_for(db_session, clean.id) == []
