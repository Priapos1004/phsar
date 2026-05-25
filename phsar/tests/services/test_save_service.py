"""save_search_results / attach_search_result_to_anime persist
MediaRelationEdges sidecars so the merge / preview / backfill paths can
re-classify without re-hitting MAL.
"""

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.anime import Anime
from app.models.media import Media, MediaType, RelationType
from app.models.media_relation_edges import MediaRelationEdges
from app.schemas.media_schema import MediaUnconnected
from app.schemas.search_schema import SearchResultDB
from app.services.save_service import save_search_results


def _media(mal_id: int, title: str, relation: RelationType) -> MediaUnconnected:
    return MediaUnconnected(
        mal_id=mal_id, mal_url=f"https://example/{mal_id}",
        title=title, name_eng=None, name_jap=None,
        media_type=MediaType.TV, relation_type=relation,
        age_rating=None, description=None, original_source=None,
        cover_image=None, score=None, scored_by=0,
        episodes=12, anime_season_name=None, anime_season_year=None,
        airing_status="Finished Airing", aired_from=None, aired_to=None,
        duration=None, duration_seconds=1440,
        genres=[], studio=[],
    )


async def test_save_search_results_persists_edges_per_media(db_session):
    """SearchResultDB carries per-anime edges; save_search_results
    projects per-source onto each MediaRelationEdges row."""
    result = SearchResultDB(
        anime_mal_id=900_001,
        unconnected_media_list=[
            _media(900_001, "Test TV", RelationType.Main),
            _media(900_002, "Test TV S2", RelationType.Main),
            _media(900_003, "Test Side", RelationType.SideStory),
        ],
        cross_link_mal_ids=set(),
        edges=[
            (900_001, 900_002, "sequel"),
            (900_001, 900_003, "side_story"),
            (900_002, 900_001, "prequel"),
        ],
    )
    await save_search_results(db_session, [result])

    stmt = (
        select(Anime)
        .where(Anime.mal_id == 900_001)
        .options(selectinload(Anime.media).selectinload(Media.relation_edges))
    )
    anime = (await db_session.execute(stmt)).scalar_one()
    edges_by_mal = {m.mal_id: m.relation_edges.edges for m in anime.media}

    # Sidecars exist and carry just the per-source projection.
    assert edges_by_mal[900_001] == [[900_002, "sequel"], [900_003, "side_story"]]
    assert edges_by_mal[900_002] == [[900_001, "prequel"]]
    assert edges_by_mal[900_003] == []


async def test_save_search_results_defaults_empty_edges(db_session):
    """SearchResultDB without edges (legacy callers / paths that don't
    capture relations) still persist MediaRelationEdges rows with []."""
    result = SearchResultDB(
        anime_mal_id=900_010,
        unconnected_media_list=[_media(900_010, "Solo Show", RelationType.Main)],
        cross_link_mal_ids=set(),
    )
    await save_search_results(db_session, [result])

    stmt = (
        select(MediaRelationEdges)
        .join(Media, Media.id == MediaRelationEdges.media_id)
        .where(Media.mal_id == 900_010)
    )
    sidecar = (await db_session.execute(stmt)).scalar_one()
    assert sidecar.edges == []


async def test_save_search_results_emits_split_candidate_on_disjoint_chains(db_session):
    """When SearchResultDB.disjoint_franchises is non-empty (third pass
    found contamination), save_search_results queues a SplitCandidate row
    pointing at the new Anime so admin can review + split. Pins the
    BNHA→Vigilante scrape-time flow.
    """
    from app.models.split_candidate import SplitCandidate, SplitCandidateStatus

    result = SearchResultDB(
        anime_mal_id=900_020,
        unconnected_media_list=[
            _media(900_020, "BNHA-like S1", RelationType.Main),
            _media(900_021, "Vigilante-like S1", RelationType.SideStory),
        ],
        cross_link_mal_ids=set(),
        edges=[
            (900_020, 900_021, "spin-off"),
            # The bridge edge that find_disjoint_franchises uses; we
            # don't re-run detection here — the caller provided the
            # already-computed cluster payload below.
        ],
        disjoint_franchises=[
            {
                "member_mal_ids": [900_021, 900_022],
                "substance_member_mal_ids": [900_021, 900_022],
                "suggested_anchor_mal_id": 900_021,
                "bridge_edges": [[900_020, 900_021, "spin-off"]],
            }
        ],
    )
    await save_search_results(db_session, [result])

    stmt = (
        select(SplitCandidate)
        .join(Anime, Anime.id == SplitCandidate.anime_id)
        .where(Anime.mal_id == 900_020)
    )
    candidate = (await db_session.execute(stmt)).scalar_one()
    assert candidate.status == SplitCandidateStatus.pending
    assert candidate.detected_by == "scrape"
    assert candidate.clusters == [
        {
            "member_mal_ids": [900_021, 900_022],
            "substance_member_mal_ids": [900_021, 900_022],
            "suggested_anchor_mal_id": 900_021,
            "bridge_edges": [[900_020, 900_021, "spin-off"]],
        }
    ]


async def test_save_search_results_clean_graph_no_split_candidate(db_session):
    """A clean scrape (no disjoint_franchises in the SearchResultDB) does
    NOT create a SplitCandidate row. Pins the no-false-positive property
    on the common path.
    """
    from app.models.split_candidate import SplitCandidate

    result = SearchResultDB(
        anime_mal_id=900_030,
        unconnected_media_list=[
            _media(900_030, "Clean Show", RelationType.Main),
        ],
        cross_link_mal_ids=set(),
        edges=[],
    )
    await save_search_results(db_session, [result])

    stmt = (
        select(SplitCandidate)
        .join(Anime, Anime.id == SplitCandidate.anime_id)
        .where(Anime.mal_id == 900_030)
    )
    candidates = (await db_session.execute(stmt)).scalars().all()
    assert candidates == []
