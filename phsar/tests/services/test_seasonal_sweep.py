"""seasonal_sweep dispatcher tests.

The dispatcher paginates /seasons/now (faked), dedupes against the
catalog, and enqueues one user_scrape Job per new MAL ID with
requested_by_user_id=None. Per-row commit means the rolled-back
db_session fixture won't see the inserts — tests open their own
async_session_maker sessions and explicitly clean up the inserted
rows after each test.

Mirrors test_update_sweep.py's harness: engine.dispose() autouse +
tracked_anime / tracked_jobs fixtures.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from app.core.db import async_session_maker, engine
from app.exceptions import (
    AnimeFilteredOutError,
    AnimeNotFoundError,
    MainMediaNotFoundError,
)
from app.models.anime import Anime
from app.models.job import Job, JobKind, JobStatus
from app.models.media import Media
from app.models.media_unwanted import MediaUnwanted
from app.schemas.search_schema import (
    AttachToExistingAction,
    SearchResultDBExtended,
)
from app.services.scrape_dispatcher import (
    seasonal_sweep_dispatcher,
    user_scrape_dispatcher,
)
from tests._helpers import media_kwargs


def _empty_extended() -> SearchResultDBExtended:
    """The post-7c handle_search_mal_api_results return shape — empty
    everywhere. Use this in tests that don't exercise the search path."""
    return SearchResultDBExtended(
        search_result_db_list=[], unwanted_media=set(), attach_actions=[],
    )


@pytest.fixture(autouse=True)
async def _reset_engine_pool():
    """Same pool-disposal pattern as test_job_worker.py: each
    pytest-asyncio test runs on a fresh event loop, and asyncpg
    refuses pooled connections that were bound to a different loop."""
    await engine.dispose()
    yield


@pytest.fixture
async def tracked_anime():
    ids: list[int] = []
    yield ids
    if ids:
        async with async_session_maker() as s:
            await s.execute(delete(Anime).where(Anime.id.in_(ids)))
            await s.commit()


@pytest.fixture
async def tracked_unwanted():
    """Cleanup for MediaUnwanted rows seeded by individual tests.
    Anime/Media are covered by tracked_anime (FK cascade), but
    MediaUnwanted has no FK so we evict by mal_id."""
    mal_ids: list[int] = []
    yield mal_ids
    if mal_ids:
        async with async_session_maker() as s:
            await s.execute(delete(MediaUnwanted).where(MediaUnwanted.mal_id.in_(mal_ids)))
            await s.commit()


@pytest.fixture
async def cleanup_seasonal_children():
    """Remove every seasonal-sweep-spawned user_scrape job after the
    test. requested_by_user_id=None + kind=user_scrape uniquely
    identifies them; clean up by created_at window so we never touch
    rows from other tests that happen to be running in parallel."""
    started_at = datetime.now(timezone.utc)
    yield
    async with async_session_maker() as s:
        await s.execute(
            delete(Job)
            .where(Job.kind == JobKind.user_scrape)
            .where(Job.requested_by_user_id.is_(None))
            .where(Job.created_at >= started_at)
        )
        await s.commit()


async def _seed_anime(mal_id: int) -> int:
    async with async_session_maker() as s:
        anime = Anime(mal_id=mal_id, title=f"A{mal_id}")
        s.add(anime)
        await s.flush()
        media = Media(**media_kwargs(anime_id=anime.id, mal_id=mal_id * 100))
        s.add(media)
        await s.commit()
        return anime.id


async def _seed_unwanted(mal_id: int) -> None:
    async with async_session_maker() as s:
        s.add(MediaUnwanted(mal_id=mal_id, title=f"U{mal_id}", reason="Music"))
        await s.commit()


def _patch_scraper(monkeypatch, entries: list[dict]) -> None:
    """Replace JikanScraper with a stub whose `fetch_current_season`
    returns `entries`. No real MAL hit, no rate-limit sleep."""

    class _FakeScraper:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def fetch_current_season(self):
            return entries

    monkeypatch.setattr(
        "app.services.scrape_dispatcher.JikanScraper", lambda: _FakeScraper(),
    )


class _NoopProgressReporter:
    def __init__(self, *_args, **_kwargs):
        pass

    async def update(self, *_args, **_kwargs):
        return None


def _patch_progress(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.ProgressReporter", _NoopProgressReporter,
    )


async def _run_dispatcher(job_id: int = 9100) -> dict:
    async with async_session_maker() as session:
        job = type("FakeJob", (), {"id": job_id})()
        return await seasonal_sweep_dispatcher(session, job)


async def _fetch_seasonal_children(after: datetime) -> list[Job]:
    """Return every system user_scrape job inserted at-or-after `after`,
    so we never collide with unrelated rows from other tests."""
    async with async_session_maker() as s:
        result = await s.execute(
            select(Job)
            .where(Job.kind == JobKind.user_scrape)
            .where(Job.requested_by_user_id.is_(None))
            .where(Job.created_at >= after)
            .order_by(Job.created_at.asc())
        )
        return list(result.scalars().all())


@pytest.mark.asyncio
async def test_dispatcher_enqueues_only_new_mal_ids(
    tracked_anime, tracked_unwanted, cleanup_seasonal_children, monkeypatch,
):
    """4 season entries: 1 already in Anime, 1 already in MediaUnwanted,
    2 brand new. Only the 2 new ones get enqueued."""
    existing_mal_id = -9101
    unwanted_mal_id = -9102
    new_a_mal_id = -9103
    new_b_mal_id = -9104

    a_id = await _seed_anime(existing_mal_id)
    tracked_anime.append(a_id)
    await _seed_unwanted(unwanted_mal_id)
    tracked_unwanted.append(unwanted_mal_id)

    _patch_progress(monkeypatch)
    _patch_scraper(monkeypatch, [
        {"mal_id": existing_mal_id, "title": "Already In Catalog"},
        {"mal_id": unwanted_mal_id, "title": "Already Filtered"},
        {"mal_id": new_a_mal_id, "title": "New Show A"},
        {"mal_id": new_b_mal_id, "title": "New Show B"},
    ])
    # Don't ping the worker; the test environment doesn't have one running.
    monkeypatch.setattr("app.services.scrape_dispatcher.job_worker.notify", lambda: None)

    started = datetime.now(timezone.utc)
    summary = await _run_dispatcher(job_id=9001)

    assert summary == {
        "season_entries": 4,
        "new_entries_enqueued": 2,
        "dedup_skipped": 2,
    }

    children = await _fetch_seasonal_children(started)
    assert sorted(c.payload["mal_id"] for c in children) == sorted(
        [new_a_mal_id, new_b_mal_id],
    )
    for child in children:
        assert child.kind is JobKind.user_scrape
        assert child.status is JobStatus.queued
        assert child.requested_by_user_id is None
        assert "query" in child.payload
        assert "mal_id" in child.payload


@pytest.mark.asyncio
async def test_dispatcher_dedupes_against_existing_media_mal_id(
    tracked_anime, cleanup_seasonal_children, monkeypatch,
):
    """A season entry whose mal_id matches an existing Media (side-story
    under a different parent anime) must be skipped — otherwise we'd
    rescrape the same show from a different angle and trip the merge
    detector."""
    parent_mal_id = -9201
    side_story_mal_id = -9201 * 100  # _seed_anime's media gets mal_id = parent * 100
    a_id = await _seed_anime(parent_mal_id)
    tracked_anime.append(a_id)

    _patch_progress(monkeypatch)
    _patch_scraper(monkeypatch, [
        {"mal_id": side_story_mal_id, "title": "Side Story As Season Entry"},
    ])
    monkeypatch.setattr("app.services.scrape_dispatcher.job_worker.notify", lambda: None)

    started = datetime.now(timezone.utc)
    summary = await _run_dispatcher(job_id=9201)

    assert summary["new_entries_enqueued"] == 0
    assert summary["dedup_skipped"] == 1
    assert await _fetch_seasonal_children(started) == []


@pytest.mark.asyncio
async def test_dispatcher_empty_season_returns_zeros(monkeypatch):
    """Off-week or fresh DB: /seasons/now returns nothing. The dispatcher
    must not crash, must return zero-zero summary, and must not touch
    the worker notify channel."""
    _patch_progress(monkeypatch)
    _patch_scraper(monkeypatch, [])

    notify_calls: list[int] = []
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.job_worker.notify",
        lambda: notify_calls.append(1),
    )

    summary = await _run_dispatcher(job_id=9301)

    assert summary == {
        "season_entries": 0,
        "new_entries_enqueued": 0,
        "dedup_skipped": 0,
    }
    assert notify_calls == []


@pytest.mark.asyncio
async def test_dispatcher_notifies_worker_after_enqueue(
    cleanup_seasonal_children, monkeypatch,
):
    """Worker.notify() must fire exactly once after the enqueue loop —
    not per-child (would be redundant), not zero (would force a 60s
    wall-clock wait before the first child runs)."""
    _patch_progress(monkeypatch)
    _patch_scraper(monkeypatch, [
        {"mal_id": -9401, "title": "Fresh Show"},
    ])

    notify_calls: list[int] = []
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.job_worker.notify",
        lambda: notify_calls.append(1),
    )

    await _run_dispatcher(job_id=9401)

    assert notify_calls == [1]


@pytest.mark.asyncio
async def test_dispatcher_skips_entries_with_missing_mal_id(
    cleanup_seasonal_children, monkeypatch,
):
    """Defensive: a malformed MAL payload missing `mal_id` must be
    silently skipped, not enqueued with mal_id=None (which would 422
    out of the child's ScrapeJobRequest validation later)."""
    _patch_progress(monkeypatch)
    _patch_scraper(monkeypatch, [
        {"title": "No mal_id"},                       # missing entirely
        {"mal_id": None, "title": "Null mal_id"},     # explicitly null
        {"mal_id": -9501, "title": "Valid"},
    ])
    monkeypatch.setattr("app.services.scrape_dispatcher.job_worker.notify", lambda: None)

    started = datetime.now(timezone.utc)
    summary = await _run_dispatcher(job_id=9501)

    assert summary["new_entries_enqueued"] == 1
    assert summary["dedup_skipped"] == 2
    children = await _fetch_seasonal_children(started)
    assert [c.payload["mal_id"] for c in children] == [-9501]


# ---------------------------------------------------------------------------
# user_scrape_dispatcher: filter-out vs not-found error surface
#
# These tests live here (next to seasonal_sweep) because they cover the
# exact failure modes the seasonal-sweep children hit in production:
# the BFS classifies the seed as Music/PV/CM/Hentai, persists a
# MediaUnwanted row, and returns an empty result. Pre-fix, every such
# case raised AnimeNotFoundError, which is misleading in the jobs
# table — admins debugging a row had no signal whether the show was
# missing on MAL or just filtered out by us. Post-fix, the dispatcher
# checks MediaUnwanted for the seed mal_id and raises
# AnimeFilteredOutError with the reason.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_scrape_raises_filtered_out_when_seed_in_unwanted(
    tracked_unwanted, monkeypatch,
):
    """When seed_mal_id was filtered as Music/PV/CM/Hentai, the BFS
    persists a MediaUnwanted row and returns []. The dispatcher must
    surface that with AnimeFilteredOutError carrying the reason —
    AnimeNotFoundError would be honestly misleading."""
    seed_mal_id = -7711

    async def fake_handle(db, query=None, progress=None, seed_mal_id=None):
        # Simulate search_title classifying the seed as a PV: MediaUnwanted
        # row already committed by the real handle_search_mal_api_results,
        # we just seed it directly here.
        async with async_session_maker() as s:
            s.add(MediaUnwanted(
                mal_id=seed_mal_id, title="Some PV", reason="PV",
            ))
            await s.commit()
        return _empty_extended()

    monkeypatch.setattr(
        "app.services.scrape_dispatcher.handle_search_mal_api_results",
        fake_handle,
    )
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.ProgressReporter", _NoopProgressReporter,
    )
    tracked_unwanted.append(seed_mal_id)

    job = type("FakeJob", (), {
        "id": 7711,
        "payload": {"query": "Some PV", "mal_id": seed_mal_id},
    })()
    async with async_session_maker() as session:
        with pytest.raises(AnimeFilteredOutError) as exc_info:
            await user_scrape_dispatcher(session, job)

    assert exc_info.value.reason == "PV"
    assert exc_info.value.title == "Some PV"
    assert "filtered out as PV" in str(exc_info.value)


@pytest.mark.asyncio
async def test_user_scrape_raises_main_not_found_when_seed_has_no_anchor(monkeypatch):
    """Seed BFS produced no main story AND no single cross-link parent
    AND no MediaUnwanted (i.e., the entry exists on MAL but its graph
    can't be saved). Surface MainMediaNotFoundError so the error message
    in jobs.failed says 'Couldn't identify a main story' instead of the
    misleading 'Anime titled X not found' (which implies MAL had no
    record at all)."""
    seed_mal_id = -7712

    async def fake_handle(db, query=None, progress=None, seed_mal_id=None):
        return _empty_extended()

    monkeypatch.setattr(
        "app.services.scrape_dispatcher.handle_search_mal_api_results",
        fake_handle,
    )
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.ProgressReporter", _NoopProgressReporter,
    )

    job = type("FakeJob", (), {
        "id": 7712,
        "payload": {"query": "Ghost Show", "mal_id": seed_mal_id},
    })()
    async with async_session_maker() as session:
        with pytest.raises(MainMediaNotFoundError):
            await user_scrape_dispatcher(session, job)


@pytest.mark.asyncio
async def test_user_scrape_raises_not_found_when_no_seed_and_empty(monkeypatch):
    """No seed_mal_id AND empty results — caller submitted a fuzzy
    title-only query and MAL returned nothing usable. AnimeNotFoundError
    is the correct surface here (the user's query is the relevant
    identifier; no mal_id to anchor anything to)."""
    async def fake_handle(db, query=None, progress=None, seed_mal_id=None):
        return _empty_extended()

    monkeypatch.setattr(
        "app.services.scrape_dispatcher.handle_search_mal_api_results",
        fake_handle,
    )
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.ProgressReporter", _NoopProgressReporter,
    )

    job = type("FakeJob", (), {
        "id": 7713,
        "payload": {"query": "Some Fuzzy Query"},  # no mal_id
    })()
    async with async_session_maker() as session:
        with pytest.raises(AnimeNotFoundError):
            await user_scrape_dispatcher(session, job)


@pytest.mark.asyncio
async def test_user_scrape_attaches_orphan_graph_to_existing_parent(
    tracked_anime, monkeypatch,
):
    """The hero path: seed is an orphan side-story (no main story in
    its graph) but the BFS surfaced exactly one cross-link to an
    existing Anime in the catalog. The dispatcher must route the new
    media under that parent via `attach_search_result_to_anime`
    (the same primitive 7c's freshness probe uses) — NOT raise an
    error, NOT save a duplicate Anime."""
    # Seed an existing parent Anime + one Media row (the cross-link target).
    parent_mal_id = -7800
    parent_anime_id = await _seed_anime(parent_mal_id)
    tracked_anime.append(parent_anime_id)
    target_media_mal_id = parent_mal_id * 100  # _seed_anime's Media gets parent_mal_id*100

    # The orphan side-story being discovered by this scrape.
    orphan_seed_mal_id = -7801

    async def fake_handle(db, query=None, progress=None, seed_mal_id=None):
        # Simulate search_mal_api packaging an attach action: the
        # orphan_seed's graph is a single side-story that resolved its
        # only cross-link to target_media_mal_id (which belongs to the
        # existing parent we seeded above).
        return SearchResultDBExtended(
            search_result_db_list=[],
            unwanted_media=set(),
            attach_actions=[AttachToExistingAction(
                target_mal_id=target_media_mal_id,
                related_anime_graph={
                    orphan_seed_mal_id: {
                        "mal_id": orphan_seed_mal_id,
                        "title": "Orphan Side Story",
                        "aired_from": None,
                        "media_type": "ONA",
                        "relation_type": "side_story",
                    },
                },
                all_info={
                    orphan_seed_mal_id: {
                        "mal_id": orphan_seed_mal_id,
                        "mal_url": f"https://example/{orphan_seed_mal_id}",
                        "title": "Orphan Side Story",
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
                        "aired_from": None,
                        "aired_to": None,
                        "airing_status": "Finished Airing",
                        "duration": None,
                        "duration_seconds": None,
                    },
                },
            )],
        )

    # Replace heavy downstream side-effects so the test is hermetic:
    # `attach_search_result_to_anime` would otherwise insert a Media row
    # + embeddings, and we're testing routing not persistence here.
    attach_calls: list[dict] = []

    async def fake_attach(db, parent_anime, graph, all_info):
        attach_calls.append({
            "parent_anime_id": parent_anime.id,
            "graph_mal_ids": list(graph.keys()),
            "all_info_mal_ids": list(all_info.keys()),
        })
        return len(graph)

    monkeypatch.setattr(
        "app.services.scrape_dispatcher.handle_search_mal_api_results",
        fake_handle,
    )
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.attach_search_result_to_anime",
        fake_attach,
    )
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.ProgressReporter", _NoopProgressReporter,
    )

    job = type("FakeJob", (), {
        "id": 7801,
        "payload": {"query": "Orphan Side Story", "mal_id": orphan_seed_mal_id},
    })()
    async with async_session_maker() as session:
        summary = await user_scrape_dispatcher(session, job)

    # The attach was routed to the right parent with the right graph.
    assert len(attach_calls) == 1
    assert attach_calls[0]["parent_anime_id"] == parent_anime_id
    assert attach_calls[0]["graph_mal_ids"] == [orphan_seed_mal_id]
    # Dispatcher reports the attach in the result summary so admins can
    # see what happened from the bell / jobs table.
    assert summary["anime_count"] == 0
    assert summary["media_count"] == 0
    assert summary["attached_count"] == 1


@pytest.mark.asyncio
async def test_user_scrape_attach_target_vanished_falls_through_to_error(monkeypatch):
    """Race condition: attach action's target_mal_id was in the catalog
    when the BFS ran, but is gone by the time the dispatcher tries to
    attach (e.g., admin merged the two anime mid-flight). Skip the
    attach, fall through to the standard empty-result error path so
    next sweep re-evaluates."""
    async def fake_handle(db, query=None, progress=None, seed_mal_id=None):
        return SearchResultDBExtended(
            search_result_db_list=[],
            unwanted_media=set(),
            attach_actions=[AttachToExistingAction(
                target_mal_id=-99999,  # not in DB
                related_anime_graph={
                    -7802: {
                        "title": "Orphan",
                        "relation_type": "side_story",
                    },
                },
                all_info={
                    -7802: {"mal_id": -7802, "title": "Orphan"},
                },
            )],
        )

    monkeypatch.setattr(
        "app.services.scrape_dispatcher.handle_search_mal_api_results",
        fake_handle,
    )
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.ProgressReporter", _NoopProgressReporter,
    )

    job = type("FakeJob", (), {
        "id": 7802,
        "payload": {"query": "Orphan", "mal_id": -7802},
    })()
    async with async_session_maker() as session:
        with pytest.raises(MainMediaNotFoundError):
            await user_scrape_dispatcher(session, job)


@pytest.mark.asyncio
async def test_dispatcher_dedupes_duplicate_mal_ids_within_one_run(
    cleanup_seasonal_children, monkeypatch,
):
    """MAL's /seasons/now has been observed to repeat the same mal_id
    across pages — a 2-page response can produce `entries` like
    [A, B, A, C]. Without per-run dedupe, each duplicate enqueues its
    own child and they all fail the same way later. The dispatcher must
    treat the entries list as a multi-set and emit one child per
    distinct mal_id."""
    _patch_progress(monkeypatch)
    _patch_scraper(monkeypatch, [
        {"mal_id": -9601, "title": "Show A"},
        {"mal_id": -9602, "title": "Show B"},
        {"mal_id": -9601, "title": "Show A (duplicate from page 2)"},
        {"mal_id": -9603, "title": "Show C"},
        {"mal_id": -9601, "title": "Show A (third copy)"},
    ])
    monkeypatch.setattr("app.services.scrape_dispatcher.job_worker.notify", lambda: None)

    started = datetime.now(timezone.utc)
    summary = await _run_dispatcher(job_id=9601)

    assert summary == {
        "season_entries": 5,
        "new_entries_enqueued": 3,
        "dedup_skipped": 2,
    }
    children = await _fetch_seasonal_children(started)
    assert sorted(c.payload["mal_id"] for c in children) == sorted([-9601, -9602, -9603])
