import logging

import pytest

from app.exceptions import MainMediaNotFoundError
from app.services import search_service
from app.services.search_service import get_first_main_relation

logger = logging.getLogger(__name__)


def _patch_scraper(monkeypatch, relations, all_info, unwanted_media=None):
    """Patch `search_service.JikanScraper` with a stub whose async-context
    `search_title` returns the given `(relations, all_info, unwanted_media)`
    tuple — the one thing the integration tests below vary."""

    class _FakeScraper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def search_title(self, **kwargs):
            return (relations, all_info, unwanted_media or set())

    monkeypatch.setattr(search_service, "JikanScraper", lambda: _FakeScraper())


def test_get_first_main_relation():
    media_dict = {
        0: {"relation_type": "side", "title": "Side Anime", "mal_id": 0},
        1: {"relation_type": "main", "title": "Main Anime", "mal_id": 1},
        2: {"relation_type": "side", "title": "Side Anime 2", "mal_id": 2},
        3: {"relation_type": "main", "title": "Main Anime 2", "mal_id": 3},
    }
    result = get_first_main_relation(media_dict)
    assert result == 1

    media_dict = {
        1: {"relation_type": "side", "title": "Side Anime", "mal_id": 1},
        2: {"relation_type": "side", "title": "Another Side Anime", "mal_id": 2},
    }
    with pytest.raises(MainMediaNotFoundError) as exc_info:
        get_first_main_relation(media_dict)

    logger.debug(f"Error message: '{exc_info.value}'")


# ---------------------------------------------------------------------------
# search_mal_api integration: classifier-driven anchor + substance-aware
# attach-vs-save routing.
# ---------------------------------------------------------------------------


def _info(mal_id: int, title: str, *, media_type: str = "ONA", aired_from: str = "2024-01-01T00:00:00+00:00", episodes: int | None = None, duration_seconds: int | None = None, scored_by: int = 0, airing_status: str = "Finished Airing") -> dict:
    return {
        "mal_id": mal_id,
        "mal_url": f"https://example/{mal_id}",
        "title": title,
        "name_eng": None,
        "name_jap": None,
        "other_names": [],
        "media_type": media_type,
        "genres": [],
        "studio": [],
        "age_rating": None,
        "description": None,
        "original_source": None,
        "cover_image": None,
        "score": None,
        "scored_by": scored_by,
        "episodes": episodes,
        "anime_season_name": None,
        "anime_season_year": None,
        "aired_from": aired_from,
        "aired_to": None,
        "airing_status": airing_status,
        "duration": None,
        "duration_seconds": duration_seconds,
    }


@pytest.mark.asyncio
async def test_search_mal_api_seeded_weak_anchor_saves_as_new_anime(monkeypatch):
    """Seeded BFS with a sparse-metadata donghua sub-universe (no node
    passes substance, no cross-link). The classifier still picks an
    anchor by tier+age (oldest ONA) and search_mal_api saves it as a
    new anime because seed_mal_id is set — the seasonal sweep flagged
    this mal_id deliberately."""
    from app.services.search_service import search_mal_api

    seed_mal_id = 51289  # Zhe Tian (the canonical earliest ONA)
    movie_mal_id = 63606  # Zhe Tian Movie

    fake_graph = {
        seed_mal_id: {
            "mal_id": seed_mal_id,
            "title": "Zhe Tian",
            "aired_from": "2021-05-01T00:00:00+00:00",
            "media_type": "ONA",
        },
        movie_mal_id: {
            "mal_id": movie_mal_id,
            "title": "Zhe Tian Movie",
            "aired_from": "2026-04-01T00:00:00+00:00",
            "media_type": "ONA",
        },
    }
    fake_all_info = {
        seed_mal_id: _info(seed_mal_id, "Zhe Tian", media_type="ONA", aired_from="2021-05-01T00:00:00+00:00"),
        movie_mal_id: _info(movie_mal_id, "Zhe Tian Movie", media_type="ONA", aired_from="2026-04-01T00:00:00+00:00", episodes=1),
    }

    _patch_scraper(monkeypatch, [(fake_graph, [], set())], fake_all_info)

    result = await search_mal_api(
        query="Zhe Tian",
        excluded_mal_ids=set(),
        seed_mal_id=movie_mal_id,
    )

    assert len(result.search_result_db_list) == 1
    sr = result.search_result_db_list[0]
    # Tier-2 ONA, oldest aired → 51289 anchors.
    assert sr.anime_mal_id == seed_mal_id
    titles = [m.title for m in sr.unconnected_media_list]
    assert titles[0] == "Zhe Tian"
    assert "Zhe Tian Movie" in titles
    assert result.attach_actions == []


@pytest.mark.asyncio
async def test_search_mal_api_filters_unwanted_from_cross_links(monkeypatch):
    """Regression guard: when BFS surfaces a cross-link to a mal_id
    that's actually in MediaUnwanted (a filtered PV/Music/CM), the
    attach-action fallback would try to attach to a parent Anime that
    doesn't exist. unwanted_mal_ids strips those from cross_link_mal_ids
    before the attach-vs-save decision."""
    from app.services.search_service import search_mal_api

    seed_mal_id = 63991
    unwanted_pv = 57314

    fake_graph = {
        seed_mal_id: {
            "mal_id": seed_mal_id,
            "title": "Benghuai Show",
            "aired_from": "2025-01-01T00:00:00+00:00",
            "media_type": "ONA",
        },
    }
    fake_all_info = {
        seed_mal_id: _info(seed_mal_id, "Benghuai Show", media_type="ONA", aired_from="2025-01-01T00:00:00+00:00", episodes=1),
    }

    _patch_scraper(monkeypatch, [(fake_graph, [], {unwanted_pv})], fake_all_info)

    result = await search_mal_api(
        query="Benghuai Show",
        excluded_mal_ids={unwanted_pv},
        seed_mal_id=seed_mal_id,
        unwanted_mal_ids={unwanted_pv},
    )

    assert result.attach_actions == []
    assert len(result.search_result_db_list) == 1
    assert result.search_result_db_list[0].anime_mal_id == seed_mal_id


@pytest.mark.asyncio
async def test_search_mal_api_title_mode_skips_weak_anchor_graphs(monkeypatch):
    """Critical contract: a title-search (no seed) where the classifier
    picks a substance-failing anchor and there's no cross-link gets
    skipped. Top-3 fuzzy matches from MAL are often genuine garbage and
    shouldn't auto-promote to catalog rows."""
    from app.services.search_service import search_mal_api

    fake_graph = {
        5000: {
            "mal_id": 5000,
            "title": "Random Garbage",
            "aired_from": "2024-01-01T00:00:00+00:00",
            "media_type": "ONA",
        },
    }
    fake_all_info = {
        5000: _info(5000, "Random Garbage", media_type="ONA", aired_from="2024-01-01T00:00:00+00:00", episodes=1),
    }

    _patch_scraper(monkeypatch, [(fake_graph, [], set())], fake_all_info)

    result = await search_mal_api(
        query="some fuzzy query",
        excluded_mal_ids=set(),
        seed_mal_id=None,
    )

    assert result.search_result_db_list == []
    assert result.attach_actions == []


@pytest.mark.asyncio
async def test_search_mal_api_single_not_yet_aired_classified_and_saved_as_main(
    db_session, monkeypatch,
):
    """End-to-end: MAL returns one anime whose only entry hasn't aired yet
    (NULL episodes/duration, 'Not yet aired'). The substance gate's pending
    exemption keeps it anchor-eligible, so it classifies as `main`, isn't
    dropped as a weak anchor, and persists cleanly through save_search_results
    despite the NULL volatile fields."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.anime import Anime
    from app.models.media import RelationType
    from app.services.save_service import save_search_results
    from app.services.search_service import search_mal_api

    mal_id = 999_321
    fake_graph = {
        mal_id: {
            "mal_id": mal_id,
            "title": "Unaired Show",
            "aired_from": "2027-01-01T00:00:00+00:00",
            "media_type": "TV",
        },
    }
    fake_all_info = {
        mal_id: _info(
            mal_id, "Unaired Show", media_type="TV",
            aired_from="2027-01-01T00:00:00+00:00",
            episodes=None, duration_seconds=None, airing_status="Not yet aired",
        ),
    }

    _patch_scraper(monkeypatch, [(fake_graph, [], set())], fake_all_info)

    result = await search_mal_api(
        query="Unaired Show", excluded_mal_ids=set(), seed_mal_id=mal_id,
    )

    # Classified main, not dropped, not attached.
    assert result.attach_actions == []
    assert len(result.search_result_db_list) == 1
    sr = result.search_result_db_list[0]
    assert sr.anime_mal_id == mal_id
    assert sr.unconnected_media_list[0].relation_type == RelationType.Main

    # Handled end-to-end: persists with NULL episodes/duration intact.
    await save_search_results(db_session, result.search_result_db_list)
    anime = (
        await db_session.execute(
            select(Anime).where(Anime.mal_id == mal_id).options(selectinload(Anime.media))
        )
    ).scalar_one()
    assert len(anime.media) == 1
    m = anime.media[0]
    assert m.relation_type == RelationType.Main
    assert m.airing_status == "Not yet aired"
    assert m.episodes is None
    assert m.duration_seconds is None
