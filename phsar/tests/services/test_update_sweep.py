"""update_sweep dispatcher + tier query tests.

Diff and refresh-one-anime tests use the rolled-back db_session fixture.
Full-dispatcher tests can't — `update_sweep_dispatcher` calls
session.commit() per anime, which ends the connection-bound outer
transaction the fixture relies on. Those tests open their own sessions
via async_session_maker and clean up the inserted rows explicitly,
mirroring tests/services/test_job_worker.py.

Diff/dispatcher tests inject a fake scraper whose extract_information is
the identity (returns the preshaped payload as-is) so each test cooks
the exact payload it wants without rebuilding a full MAL response.
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.core.db import async_session_maker, engine
from app.daos.anime_dao import AnimeDAO
from app.models.anime import Anime
from app.models.anime_freshness import AnimeFreshness
from app.models.media import Media
from app.models.media_freshness import MediaFreshness
from app.services.scrape_dispatcher import (
    _apply_media_diff,
    _refresh_one_anime,
    update_sweep_dispatcher,
)
from tests._helpers import media_kwargs


@pytest.fixture(autouse=True)
async def _reset_engine_pool():
    """Each pytest-asyncio test gets a fresh event loop. Pooled
    connections are bound to whatever loop opened them — disposing here
    means the next acquire() rebinds to the current loop. Mirrors the
    pattern in test_job_worker.py."""
    await engine.dispose()
    yield


class _FakeScraper:
    """Stand-in for JikanScraper in dispatcher tests.

    Uses the async-context-manager protocol the real scraper uses, but
    `extract_information` is the identity so tests cook payloads
    directly. Pass `payloads_by_mal_id={mal_id: payload, ...}` to vend
    different payloads per media; pass `error_for_mal_id` to raise on a
    specific id (per-anime fault isolation tests)."""

    def __init__(self, payloads_by_mal_id: dict[int, dict], error_for_mal_id: int | None = None):
        self._payloads = payloads_by_mal_id
        self._error_for = error_for_mal_id
        self.refresh_calls: list[int] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def refresh_anime(self, mal_id: int) -> dict:
        self.refresh_calls.append(mal_id)
        if self._error_for is not None and mal_id == self._error_for:
            raise RuntimeError(f"simulated MAL failure for {mal_id}")
        return self._payloads[mal_id]

    @staticmethod
    def extract_information(payload: dict) -> dict:
        return payload


def _payload(
    score: float | None = 7.5,
    scored_by: int = 1000,
    episodes: int | None = 12,
    airing_status: str = "Finished Airing",
    aired_to: str | None = "2020-06-30T00:00:00+00:00",
) -> dict:
    return {
        "score": score,
        "scored_by": scored_by,
        "episodes": episodes,
        "airing_status": airing_status,
        "aired_to": aired_to,
    }


# ---------------------------------------------------------------------------
# _apply_media_diff (pure unit tests)
# ---------------------------------------------------------------------------


def test_diff_no_change_returns_false():
    media = Media(**media_kwargs(anime_id=1, mal_id=1, score=7.5, scored_by=1000, episodes=12,
        airing_status="Finished Airing",
        aired_to=datetime(2020, 6, 30, tzinfo=timezone.utc),
    ))
    assert _apply_media_diff(media, _payload()) is False


def test_diff_score_change_returns_true():
    media = Media(**media_kwargs(anime_id=1, mal_id=1, score=7.5, scored_by=1000, episodes=12,
        airing_status="Finished Airing",
        aired_to=datetime(2020, 6, 30, tzinfo=timezone.utc),
    ))
    assert _apply_media_diff(media, _payload(score=8.0)) is True
    assert media.score == 8.0


def test_diff_episodes_was_null_logs_only(caplog):
    media = Media(**media_kwargs(anime_id=1, mal_id=42, score=7.5, scored_by=1000, episodes=None,
        airing_status="Currently Airing", aired_to=None, title="Some Show",
    ))
    with caplog.at_level(logging.INFO, logger="app.services.scrape_dispatcher"):
        changed = _apply_media_diff(media, _payload(episodes=24, airing_status="Currently Airing", aired_to=None))
    assert changed is True
    assert media.episodes == 24
    assert any("Episode count revealed" in r.message for r in caplog.records)


def test_diff_small_vote_drift_below_threshold_returns_false():
    """A +1 vote on a high-vote anime moves scored_by but the weighted
    delta is essentially zero — must not reset the stability counter."""
    media = Media(**media_kwargs(anime_id=1, mal_id=1, score=8.5, scored_by=5_000_000, episodes=12,
        airing_status="Finished Airing",
        aired_to=datetime(2020, 6, 30, tzinfo=timezone.utc),
    ))
    payload = _payload(score=8.5, scored_by=5_000_001, episodes=12, aired_to="2020-06-30T00:00:00+00:00")
    assert _apply_media_diff(media, payload) is False
    # But the value is still written through — data freshness.
    assert media.scored_by == 5_000_001


def test_diff_borderline_score_change_below_threshold_returns_false():
    """+0.005 score on 1k votes — weighted delta ~0.015, below 0.05."""
    media = Media(**media_kwargs(anime_id=1, mal_id=1, score=7.500, scored_by=1000, episodes=12,
        airing_status="Finished Airing",
        aired_to=datetime(2020, 6, 30, tzinfo=timezone.utc),
    ))
    payload = _payload(score=7.505, scored_by=1000)
    assert _apply_media_diff(media, payload) is False
    assert media.score == 7.505


def test_diff_score_appears_is_a_structural_change():
    """score going from None (anime not yet rated) to a real value is a
    real-world transition — must reset the counter regardless of the
    weighted threshold."""
    media = Media(**media_kwargs(anime_id=1, mal_id=1, score=None, scored_by=0, episodes=12,
        airing_status="Currently Airing", aired_to=None,
    ))
    payload = _payload(score=8.0, scored_by=500, airing_status="Currently Airing", aired_to=None)
    assert _apply_media_diff(media, payload) is True
    assert media.score == 8.0
    assert media.scored_by == 500


def test_diff_refuses_to_clobber_airing_status_with_none():
    """airing_status is NOT NULL — a missing field in MAL payload (rare,
    defensive) must not blow up the row."""
    media = Media(**media_kwargs(anime_id=1, mal_id=1, score=7.5, scored_by=1000, episodes=12,
        airing_status="Finished Airing",
        aired_to=datetime(2020, 6, 30, tzinfo=timezone.utc),
    ))
    payload = _payload()
    payload["airing_status"] = None
    assert _apply_media_diff(media, payload) is False
    assert media.airing_status == "Finished Airing"


# ---------------------------------------------------------------------------
# _refresh_one_anime (uses db_session)
# ---------------------------------------------------------------------------


async def _build_anime_with_one_media(
    db_session, mal_id_a: int, mal_id_m: int, *, freshness: AnimeFreshness | None = None,
    media_freshness: MediaFreshness | None = None, **media_overrides,
) -> Anime:
    anime = Anime(mal_id=mal_id_a, title=f"A{mal_id_a}")
    db_session.add(anime)
    await db_session.flush()
    if freshness is not None:
        freshness.anime_id = anime.id
        db_session.add(freshness)
    media = Media(**media_kwargs(anime_id=anime.id, mal_id=mal_id_m, **media_overrides))
    db_session.add(media)
    await db_session.flush()
    if media_freshness is not None:
        media_freshness.media_id = media.id
        db_session.add(media_freshness)
    await db_session.flush()
    # Re-fetch so the relationships line up with the eager-loaded shape
    # the dispatcher gets from select_due_for_sweep.
    result = await db_session.execute(
        select(Anime).where(Anime.id == anime.id).options(
            selectinload(Anime.media).selectinload(Media.freshness),
            selectinload(Anime.freshness),
        )
    )
    return result.scalars().first()


@pytest.mark.asyncio
async def test_refresh_increments_counter_when_unchanged(db_session):
    anime = await _build_anime_with_one_media(
        db_session, mal_id_a=-9001, mal_id_m=-9101,
        freshness=AnimeFreshness(last_checked_at=datetime.now(timezone.utc) - timedelta(days=1), stable_check_count=5),
        media_freshness=MediaFreshness(last_checked_at=datetime.now(timezone.utc) - timedelta(days=1)),
        score=7.5, scored_by=1000, episodes=12, airing_status="Finished Airing",
        aired_to=datetime(2020, 6, 30, tzinfo=timezone.utc),
    )
    media_mal_id = anime.media[0].mal_id
    scraper = _FakeScraper({media_mal_id: _payload()})

    changed = await _refresh_one_anime(db_session, anime, scraper)

    assert changed is False
    assert anime.freshness.stable_check_count == 6


@pytest.mark.asyncio
async def test_refresh_resets_counter_on_score_change(db_session):
    anime = await _build_anime_with_one_media(
        db_session, mal_id_a=-9002, mal_id_m=-9102,
        freshness=AnimeFreshness(last_checked_at=datetime.now(timezone.utc) - timedelta(days=1), stable_check_count=7),
        media_freshness=MediaFreshness(last_checked_at=datetime.now(timezone.utc) - timedelta(days=1)),
        score=7.5, scored_by=1000, episodes=12, airing_status="Finished Airing",
        aired_to=datetime(2020, 6, 30, tzinfo=timezone.utc),
    )
    media_mal_id = anime.media[0].mal_id
    scraper = _FakeScraper({media_mal_id: _payload(score=8.0)})

    changed = await _refresh_one_anime(db_session, anime, scraper)

    assert changed is True
    assert anime.freshness.stable_check_count == 0
    assert anime.media[0].score == 8.0


@pytest.mark.asyncio
async def test_refresh_currently_airing_resets_counter_without_diff(db_session):
    """A live show must always reset to 0 even when the payload is
    identical — so the next sweep still picks it up via tier 1 (not tier
    2's stable<3). Belt-and-braces against drift."""
    anime = await _build_anime_with_one_media(
        db_session, mal_id_a=-9003, mal_id_m=-9103,
        freshness=AnimeFreshness(last_checked_at=datetime.now(timezone.utc) - timedelta(days=1), stable_check_count=4),
        media_freshness=MediaFreshness(last_checked_at=datetime.now(timezone.utc) - timedelta(days=1)),
        score=7.5, scored_by=1000, episodes=12, airing_status="Currently Airing",
        aired_to=None,
    )
    media_mal_id = anime.media[0].mal_id
    scraper = _FakeScraper({media_mal_id: _payload(airing_status="Currently Airing", aired_to=None)})

    changed = await _refresh_one_anime(db_session, anime, scraper)

    assert changed is False
    assert anime.freshness.stable_check_count == 0


@pytest.mark.asyncio
async def test_refresh_bumps_last_checked_even_when_unchanged(db_session):
    old_anime_ts = datetime.now(timezone.utc) - timedelta(days=30)
    old_media_ts = datetime.now(timezone.utc) - timedelta(days=30)
    anime = await _build_anime_with_one_media(
        db_session, mal_id_a=-9004, mal_id_m=-9104,
        freshness=AnimeFreshness(last_checked_at=old_anime_ts, stable_check_count=10),
        media_freshness=MediaFreshness(last_checked_at=old_media_ts),
        score=7.5, scored_by=1000, episodes=12, airing_status="Finished Airing",
        aired_to=datetime(2020, 6, 30, tzinfo=timezone.utc),
    )
    media_mal_id = anime.media[0].mal_id
    scraper = _FakeScraper({media_mal_id: _payload()})

    await _refresh_one_anime(db_session, anime, scraper)

    assert anime.freshness.last_checked_at > old_anime_ts
    assert anime.media[0].freshness.last_checked_at > old_media_ts


@pytest.mark.asyncio
async def test_refresh_creates_missing_sidecars_defensively(db_session):
    """Dispatcher must not crash on a row that's missing its sidecar —
    save_service from 7b creates them on insert and the migration
    backfilled existing rows, but a legacy/seed row could still be
    bare."""
    anime = await _build_anime_with_one_media(
        db_session, mal_id_a=-9005, mal_id_m=-9105,
        freshness=None, media_freshness=None,
        score=7.5, scored_by=1000, episodes=12, airing_status="Finished Airing",
        aired_to=datetime(2020, 6, 30, tzinfo=timezone.utc),
    )
    assert anime.freshness is None
    assert anime.media[0].freshness is None
    media_mal_id = anime.media[0].mal_id
    scraper = _FakeScraper({media_mal_id: _payload()})

    await _refresh_one_anime(db_session, anime, scraper)

    assert anime.freshness is not None
    assert anime.freshness.stable_check_count == 0
    assert anime.media[0].freshness is not None


# ---------------------------------------------------------------------------
# AnimeDAO.select_due_for_sweep (uses db_session)
# ---------------------------------------------------------------------------


async def _seed_anime(
    db_session, *, mal_id: int, last_checked_at: datetime | None,
    stable_check_count: int = 5, airing_status: str = "Finished Airing",
    aired_from: datetime | None = None, relation_type=None,
):
    """Insert anime + one media + an anime_freshness row. Defaults
    avoid every tier (stable=5, last_checked=recent, finished, no airing,
    no main, no recent main); each test overrides the field that
    triggers its tier."""
    from app.models.media import RelationType
    if relation_type is None:
        relation_type = RelationType.SideStory
    anime = Anime(mal_id=mal_id, title=f"A{mal_id}")
    db_session.add(anime)
    await db_session.flush()
    media = Media(**media_kwargs(
        anime_id=anime.id, mal_id=mal_id * 100,
        airing_status=airing_status,
        relation_type=relation_type,
        aired_from=aired_from,
    ))
    db_session.add(media)
    af = AnimeFreshness(
        anime_id=anime.id,
        last_checked_at=last_checked_at,
        stable_check_count=stable_check_count,
    )
    db_session.add(af)
    await db_session.flush()
    return anime


async def _select_due_ids(db_session) -> set[int]:
    rows = await AnimeDAO().select_due_for_sweep(db_session, limit=1000)
    return {a.id for a in rows}


@pytest.mark.asyncio
async def test_tier_currently_airing_always_selected(db_session):
    a = await _seed_anime(
        db_session, mal_id=-7001,
        last_checked_at=datetime.now(timezone.utc) - timedelta(hours=1),
        stable_check_count=10, airing_status="Currently Airing",
    )
    assert a.id in await _select_due_ids(db_session)


@pytest.mark.asyncio
async def test_tier_stable_under_threshold_selected(db_session):
    a_stable_2 = await _seed_anime(
        db_session, mal_id=-7002, stable_check_count=2,
        last_checked_at=datetime.now(timezone.utc),
    )
    a_stable_3 = await _seed_anime(
        db_session, mal_id=-7003, stable_check_count=3,
        last_checked_at=datetime.now(timezone.utc),
    )
    ids = await _select_due_ids(db_session)
    assert a_stable_2.id in ids
    assert a_stable_3.id not in ids


@pytest.mark.asyncio
async def test_tier_recent_main_weekly_selected(db_session):
    from app.models.media import RelationType
    recent_main = await _seed_anime(
        db_session, mal_id=-7004, stable_check_count=10,
        last_checked_at=datetime.now(timezone.utc) - timedelta(days=8),
        relation_type=RelationType.Main,
        aired_from=datetime.now(timezone.utc) - timedelta(days=730),  # 2y ago
    )
    assert recent_main.id in await _select_due_ids(db_session)


@pytest.mark.asyncio
async def test_tier_old_main_excluded_from_weekly(db_session):
    """Main media aired 7y ago + last_checked 8d ago + stable=10 + no
    airing → falls outside tiers 1, 2, 3, AND 4 (4 fires only when
    last_checked > 180 days). Should NOT be selected this run."""
    from app.models.media import RelationType
    old_main = await _seed_anime(
        db_session, mal_id=-7005, stable_check_count=10,
        last_checked_at=datetime.now(timezone.utc) - timedelta(days=8),
        relation_type=RelationType.Main,
        aired_from=datetime.now(timezone.utc) - timedelta(days=365 * 7),
    )
    assert old_main.id not in await _select_due_ids(db_session)


@pytest.mark.asyncio
async def test_tier_long_tail_selected(db_session):
    a = await _seed_anime(
        db_session, mal_id=-7006, stable_check_count=10,
        last_checked_at=datetime.now(timezone.utc) - timedelta(days=200),
    )
    assert a.id in await _select_due_ids(db_session)


@pytest.mark.asyncio
async def test_tier_handles_missing_sidecar(db_session):
    """Anime without an anime_freshness row falls back to created_at via
    COALESCE. _seed_anime always creates a sidecar, so build one without."""
    anime = Anime(mal_id=-7007, title="A-7007")
    db_session.add(anime)
    await db_session.flush()
    # Create the anime more than 180 days ago by direct UPDATE so it
    # falls into tier 4 via COALESCE on created_at.
    from sqlalchemy import update
    await db_session.execute(
        update(Anime)
        .where(Anime.id == anime.id)
        .values(created_at=datetime.now(timezone.utc) - timedelta(days=200))
    )
    db_session.add(Media(**media_kwargs(anime_id=anime.id, mal_id=-7007 * 100)))
    await db_session.flush()
    assert anime.id in await _select_due_ids(db_session)


# ---------------------------------------------------------------------------
# update_sweep_dispatcher (per-anime commit isolation)
#
# Uses real sessions + explicit cleanup because the dispatcher commits per
# anime, which terminates the connection-bound outer-rollback fixture.
# ---------------------------------------------------------------------------


class _NoopProgressReporter:
    def __init__(self, *_args, **_kwargs):
        pass

    async def update(self, *_args, **_kwargs):
        return None


@pytest.fixture
async def tracked_anime():
    """Yields a list to which tests append anime ids; teardown deletes
    those rows so the table is clean for the next test. Mirrors
    test_job_worker.py's tracked_jobs fixture."""
    ids: list[int] = []
    yield ids
    if ids:
        async with async_session_maker() as s:
            # Cascade deletes media + freshness via FK CASCADE.
            await s.execute(delete(Anime).where(Anime.id.in_(ids)))
            await s.commit()


async def _real_seed(
    *, mal_id: int, last_checked_at: datetime | None,
    stable_check_count: int = 0, airing_status: str = "Finished Airing",
    score: float = 7.5, scored_by: int = 1000, episodes: int = 12,
    aired_to: datetime | None = datetime(2020, 6, 30, tzinfo=timezone.utc),
) -> int:
    """Insert anime + media + freshness via a real committed session.
    Defaults align with `_payload()` so a same-payload refresh produces
    no diff. Returns anime.id."""
    async with async_session_maker() as s:
        anime = Anime(mal_id=mal_id, title=f"A{mal_id}")
        s.add(anime)
        await s.flush()
        media = Media(**media_kwargs(
            anime_id=anime.id, mal_id=mal_id * 100,
            airing_status=airing_status,
            score=score, scored_by=scored_by, episodes=episodes, aired_to=aired_to,
        ))
        s.add(media)
        await s.flush()
        s.add(MediaFreshness(media_id=media.id, last_checked_at=last_checked_at))
        s.add(AnimeFreshness(
            anime_id=anime.id,
            last_checked_at=last_checked_at,
            stable_check_count=stable_check_count,
        ))
        await s.commit()
        return anime.id


def _patch_select_due(monkeypatch, anime_ids: list[int]) -> None:
    """Replace AnimeDAO.select_due_for_sweep with a function that returns
    only the test's anime ids (in order). Without this, the dispatcher
    would pick up unrelated rows left in the test DB by other tests and
    try to refresh them through our fake scraper, KeyError'ing on
    unrecognized mal_ids and side-effect-mutating real rows."""
    async def fake_select(self, db, limit):
        result = await db.execute(
            select(Anime)
            .where(Anime.id.in_(anime_ids))
            .order_by(Anime.id.asc())
            .options(
                selectinload(Anime.media).selectinload(Media.freshness),
                selectinload(Anime.freshness),
            )
        )
        rows = {a.id: a for a in result.scalars().all()}
        return [rows[i] for i in anime_ids if i in rows]

    monkeypatch.setattr(AnimeDAO, "select_due_for_sweep", fake_select)


@pytest.mark.asyncio
async def test_dispatcher_returns_summary(tracked_anime, monkeypatch):
    a1_id = await _real_seed(
        mal_id=-8001, last_checked_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    a2_id = await _real_seed(
        mal_id=-8002, last_checked_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    tracked_anime.extend([a1_id, a2_id])

    payloads = {
        -8001 * 100: _payload(),                  # no diff → counter +1
        -8002 * 100: _payload(score=9.9),         # diff → counter reset
    }
    fake = _FakeScraper(payloads)
    monkeypatch.setattr("app.services.scrape_dispatcher.JikanScraper", lambda: fake)
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.ProgressReporter",
        _NoopProgressReporter,
    )
    _patch_select_due(monkeypatch, [a1_id, a2_id])

    async with async_session_maker() as session:
        job = type("FakeJob", (), {"id": 999})()
        summary = await update_sweep_dispatcher(session, job)

    assert summary["anime_refreshed"] == 2
    assert summary["anime_changed"] == 1
    assert sorted(fake.refresh_calls) == sorted([-8001 * 100, -8002 * 100])


@pytest.mark.asyncio
async def test_dispatcher_isolates_failures_per_anime(tracked_anime, monkeypatch):
    """Anime #2 raises mid-refresh; #1 and #3 must still commit. The
    refreshed count is 2, not 0 or 3, and #2's last_checked_at stays at
    its old value."""
    old = datetime.now(timezone.utc) - timedelta(days=10)
    a1_id = await _real_seed(mal_id=-8101, last_checked_at=old)
    a2_id = await _real_seed(mal_id=-8102, last_checked_at=old)
    a3_id = await _real_seed(mal_id=-8103, last_checked_at=old)
    tracked_anime.extend([a1_id, a2_id, a3_id])

    payloads = {
        -8101 * 100: _payload(),
        -8102 * 100: _payload(),
        -8103 * 100: _payload(),
    }
    fake = _FakeScraper(payloads, error_for_mal_id=-8102 * 100)
    monkeypatch.setattr("app.services.scrape_dispatcher.JikanScraper", lambda: fake)
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.ProgressReporter",
        _NoopProgressReporter,
    )
    _patch_select_due(monkeypatch, [a1_id, a2_id, a3_id])

    async with async_session_maker() as session:
        job = type("FakeJob", (), {"id": 998})()
        summary = await update_sweep_dispatcher(session, job)

    assert summary["anime_refreshed"] == 2

    # Verify a2's last_checked_at didn't advance (still at the seeded
    # value, modulo asyncpg precision); a1/a3's did.
    async with async_session_maker() as s:
        result = await s.execute(
            select(Anime).where(Anime.id.in_([a1_id, a2_id, a3_id]))
            .options(selectinload(Anime.freshness))
        )
        anime_by_id = {a.id: a for a in result.scalars().all()}
    assert anime_by_id[a1_id].freshness.last_checked_at > old
    assert anime_by_id[a3_id].freshness.last_checked_at > old
    # a2's freshness unchanged (stays at seeded value).
    assert anime_by_id[a2_id].freshness.last_checked_at == old
