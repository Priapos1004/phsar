import logging

import pytest

from app.exceptions import MainMediaNotFoundError
from app.services.search_service import (
    _pick_root_for_promotion,
    get_first_main_relation,
)

logger = logging.getLogger(__name__)

def test_get_first_main_relation():
    # Test with a dictionary containing two main relations
    media_dict = {
        0: {"relation_type": "side", "title": "Side Anime", "mal_id": 0},
        1: {"relation_type": "main", "title": "Main Anime", "mal_id": 1},
        2: {"relation_type": "side", "title": "Side Anime 2", "mal_id": 2},
        3: {"relation_type": "main", "title": "Main Anime 2", "mal_id": 3},
    }
    result = get_first_main_relation(media_dict)
    assert result == 1

    # Test with a dictionary without a main relation
    media_dict = {
        1: {"relation_type": "side", "title": "Side Anime", "mal_id": 1},
        2: {"relation_type": "side", "title": "Another Side Anime", "mal_id": 2},
    }
    with pytest.raises(MainMediaNotFoundError) as exc_info:
        get_first_main_relation(media_dict)

    logger.debug(f"Error message: '{exc_info.value}'")


# ---------------------------------------------------------------------------
# _pick_root_for_promotion (Option B fallback when seeded BFS has no main)
# ---------------------------------------------------------------------------


def test_pick_root_prefers_oldest_within_same_type_tier():
    """When all entries are the same media type, oldest aired_from wins.
    This is the donghua case: a sub-universe of ONAs where the original
    series should be promoted to main, not the newest spin-off."""
    graph = {
        63606: {"mal_id": 63606, "media_type": "ONA", "aired_from": "2026-04-01T00:00:00+00:00", "title": "Zhe Tian Movie"},
        51289: {"mal_id": 51289, "media_type": "ONA", "aired_from": "2021-05-01T00:00:00+00:00", "title": "Zhe Tian"},
    }
    assert _pick_root_for_promotion(graph) == 51289


def test_pick_root_prefers_tv_over_special_even_if_special_aired_first():
    """The pilot-before-main edge case. A Special pilot aired in 2020,
    the canonical TV series aired in 2022. We MUST pick the TV (tier 0)
    even though the Special (tier 3) is older — otherwise the catalog
    surfaces the pilot as the franchise's main entry."""
    graph = {
        7000: {"mal_id": 7000, "media_type": "Special", "aired_from": "2020-01-01T00:00:00+00:00", "title": "Anime W Pilot"},
        7001: {"mal_id": 7001, "media_type": "TV", "aired_from": "2022-04-01T00:00:00+00:00", "title": "Anime W"},
    }
    assert _pick_root_for_promotion(graph) == 7001


def test_pick_root_prefers_tv_over_ona():
    """When a TV and an ONA coexist in the graph (rare but possible),
    TV wins — it's the canonical main format. The ONA might still be
    in the same franchise as a related entry."""
    graph = {
        8000: {"mal_id": 8000, "media_type": "ONA", "aired_from": "2020-01-01T00:00:00+00:00", "title": "Older ONA"},
        8001: {"mal_id": 8001, "media_type": "TV", "aired_from": "2024-01-01T00:00:00+00:00", "title": "Newer TV"},
    }
    assert _pick_root_for_promotion(graph) == 8001


def test_pick_root_treats_missing_aired_from_as_oldest_within_tier():
    """A graph entry with aired_from=None must NOT outrank an entry
    with a real date (we'd be promoting an unscheduled placeholder).
    Sort nulls last."""
    graph = {
        9000: {"mal_id": 9000, "media_type": "ONA", "aired_from": None, "title": "No Date ONA"},
        9001: {"mal_id": 9001, "media_type": "ONA", "aired_from": "2022-01-01T00:00:00+00:00", "title": "Dated ONA"},
    }
    assert _pick_root_for_promotion(graph) == 9001


def test_pick_root_empty_graph_returns_none():
    """Defensive: an empty graph (shouldn't happen in practice, but
    possible if every BFS hit was filtered as null-title or PV/CM)
    returns None so the caller can decide to skip cleanly."""
    assert _pick_root_for_promotion({}) is None


def test_pick_root_unknown_media_type_loses_to_known():
    """An entry with an unknown / missing media_type should NOT win
    over a TV/Movie/ONA. Fall back to tier 99 so it sorts last."""
    graph = {
        9100: {"mal_id": 9100, "media_type": None, "aired_from": "2010-01-01T00:00:00+00:00", "title": "Untyped Old"},
        9101: {"mal_id": 9101, "media_type": "ONA", "aired_from": "2024-01-01T00:00:00+00:00", "title": "Recent ONA"},
    }
    assert _pick_root_for_promotion(graph) == 9101


# ---------------------------------------------------------------------------
# search_mal_api integration: seeded-mode promote-root fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_mal_api_seeded_promotes_root_when_no_main(monkeypatch):
    """End-to-end for the new fallback path: seeded BFS returns a
    graph with no main story and no cross-link. search_mal_api must
    promote the picked root to 'main' and return a SearchResultDB
    (not silently swallow the graph like the title-search path does).

    This is the donghua case condensed into a unit test: two ONA
    entries, neither has the 'main' relation_type because the BFS
    couldn't anchor them on TV/Movie. With seed_mal_id set, we expect
    the oldest ONA to be promoted and a SearchResultDB produced."""
    from app.services import search_service
    from app.services.search_service import search_mal_api

    seed_mal_id = 51289  # Zhe Tian
    movie_mal_id = 63606  # Zhe Tian Movie

    # Stub JikanScraper.search_title to return the BFS shape the
    # production code would produce for this donghua sub-universe.
    fake_graph = {
        seed_mal_id: {
            "mal_id": seed_mal_id,
            "title": "Zhe Tian",
            "aired_from": "2021-05-01T00:00:00+00:00",
            "media_type": "ONA",
            "relation_type": "parent_story",
        },
        movie_mal_id: {
            "mal_id": movie_mal_id,
            "title": "Zhe Tian Movie",
            "aired_from": "2026-04-01T00:00:00+00:00",
            "media_type": "ONA",
            "relation_type": "side_story",
        },
    }
    fake_all_info = {
        seed_mal_id: {
            "mal_id": seed_mal_id,
            "mal_url": f"https://example/{seed_mal_id}",
            "title": "Zhe Tian",
            "name_eng": None,
            "name_jap": None,
            "other_names": [],
            "media_type": "ONA",
            "genres": [],
            "studio": [],
            "age_rating": None,
            "description": None,
            "original_source": None,
            "cover_image": None,
            "score": None,
            "scored_by": 0,
            "episodes": None,
            "anime_season_name": None,
            "anime_season_year": None,
            "aired_from": "2021-05-01T00:00:00+00:00",
            "aired_to": None,
            "airing_status": "Currently Airing",
            "duration": None,
            "duration_seconds": None,
        },
        movie_mal_id: {
            "mal_id": movie_mal_id,
            "mal_url": f"https://example/{movie_mal_id}",
            "title": "Zhe Tian Movie",
            "name_eng": None,
            "name_jap": None,
            "other_names": [],
            "media_type": "ONA",
            "genres": [],
            "studio": [],
            "age_rating": None,
            "description": None,
            "original_source": None,
            "cover_image": None,
            "score": None,
            "scored_by": 0,
            "episodes": 1,
            "anime_season_name": None,
            "anime_season_year": None,
            "aired_from": "2026-04-01T00:00:00+00:00",
            "aired_to": None,
            "airing_status": "Finished Airing",
            "duration": None,
            "duration_seconds": None,
        },
    }

    class _FakeScraper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def search_title(
            self, title=None, excluded_mal_ids=None, initial_search_limit=3,
            progress=None, seed_mal_id=None, seed_payload=None,
        ):
            # Return ONE graph with no main relation, empty cross-links.
            return ([(fake_graph, set())], fake_all_info, set())

    monkeypatch.setattr(search_service, "JikanScraper", lambda: _FakeScraper())

    result = await search_mal_api(
        query="Zhe Tian",
        excluded_mal_ids=set(),
        seed_mal_id=movie_mal_id,
    )

    # The graph was promoted, not swallowed.
    assert len(result.search_result_db_list) == 1
    sr = result.search_result_db_list[0]
    # The earliest-aired ONA (the parent series, mal_id=51289) was
    # promoted to main per the type-tier + aired_from sort.
    assert sr.anime_mal_id == seed_mal_id
    # Both entries are in the unconnected_media_list. Main goes first.
    titles = [m.title for m in sr.unconnected_media_list]
    assert titles[0] == "Zhe Tian"
    assert "Zhe Tian Movie" in titles
    # No attach action (no cross-link to existing).
    assert result.attach_actions == []


@pytest.mark.asyncio
async def test_search_mal_api_filters_unwanted_from_cross_links(monkeypatch):
    """Bug reproducer: when the BFS surfaces a cross-link to a mal_id
    that's in MediaUnwanted (a filtered PV/Music/CM, not a real
    Media), the attach-action fallback would try to attach to a parent
    Anime that doesn't exist (MediaUnwanted has no Anime FK). The fix
    passes `unwanted_mal_ids` separately so search_mal_api subtracts
    them from cross_link_mal_ids before the attach-vs-promote decision.

    Setup: seed mal_id=63991 (the failing Benghuai case in production).
    BFS produces a graph with the seed only (ONA, side_story) and
    cross_link={57314}. 57314 is in unwanted_mal_ids. Expect the
    promote-root fallback to fire instead of an attach action."""
    from app.services import search_service
    from app.services.search_service import search_mal_api

    seed_mal_id = 63991
    unwanted_pv = 57314

    fake_graph = {
        seed_mal_id: {
            "mal_id": seed_mal_id,
            "title": "Benghuai Show",
            "aired_from": "2025-01-01T00:00:00+00:00",
            "media_type": "ONA",
            "relation_type": "side_story",
        },
    }
    fake_all_info = {
        seed_mal_id: {
            "mal_id": seed_mal_id,
            "mal_url": f"https://example/{seed_mal_id}",
            "title": "Benghuai Show",
            "name_eng": None,
            "name_jap": None,
            "other_names": [],
            "media_type": "ONA",
            "genres": [],
            "studio": [],
            "age_rating": None,
            "description": None,
            "original_source": None,
            "cover_image": None,
            "score": None,
            "scored_by": 0,
            "episodes": 1,
            "anime_season_name": None,
            "anime_season_year": None,
            "aired_from": "2025-01-01T00:00:00+00:00",
            "aired_to": None,
            "airing_status": "Finished Airing",
            "duration": None,
            "duration_seconds": None,
        },
    }

    class _FakeScraper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def search_title(self, **kwargs):
            # cross_link contains the unwanted PV — pre-fix this would
            # incorrectly trigger the attach-action path.
            return ([(fake_graph, {unwanted_pv})], fake_all_info, set())

    monkeypatch.setattr(search_service, "JikanScraper", lambda: _FakeScraper())

    result = await search_mal_api(
        query="Benghuai Show",
        excluded_mal_ids={unwanted_pv},
        seed_mal_id=seed_mal_id,
        unwanted_mal_ids={unwanted_pv},
    )

    # The unwanted cross-link was filtered → no attach action.
    assert result.attach_actions == []
    # Promote-root fallback fired → seed is in the result list as main.
    assert len(result.search_result_db_list) == 1
    assert result.search_result_db_list[0].anime_mal_id == seed_mal_id


@pytest.mark.asyncio
async def test_search_mal_api_title_mode_still_swallows_orphan_graphs(monkeypatch):
    """Critical contract: the promote-root behavior is GATED on
    seed_mal_id. A title-search (no seed) with a no-main graph still
    gets swallowed silently — top-3 fuzzy matches from MAL are often
    genuine garbage and shouldn't auto-promote to catalog rows."""
    from app.services import search_service
    from app.services.search_service import search_mal_api

    fake_graph = {
        5000: {
            "mal_id": 5000,
            "title": "Random Garbage",
            "aired_from": "2024-01-01T00:00:00+00:00",
            "media_type": "ONA",
            "relation_type": "side_story",
        },
    }

    class _FakeScraper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def search_title(self, **kwargs):
            return ([(fake_graph, set())], {5000: {**fake_graph[5000]}}, set())

    monkeypatch.setattr(search_service, "JikanScraper", lambda: _FakeScraper())

    result = await search_mal_api(
        query="some fuzzy query",
        excluded_mal_ids=set(),
        seed_mal_id=None,  # title-search mode
    )

    assert result.search_result_db_list == []
    assert result.attach_actions == []
