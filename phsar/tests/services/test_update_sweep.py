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
from app.models.media_genre import MediaGenre
from app.models.media_relation_edges import MediaRelationEdges
from app.models.media_studio import MediaStudio
from app.models.media_unwanted import MediaUnwanted
from app.models.genre import Genre, GenreType
from app.models.studio import Studio
from app.services.scrape_dispatcher import (
    _advance_anime_freshness,
    _apply_genre_diff,
    _apply_media_diff,
    _apply_metadata_diff,
    _apply_studio_diff,
    _qualifies_for_relations_probe,
    _refresh_one_anime,
    _summarize_drift,
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

    `extract_information` is the identity so tests cook payloads directly.
    `search_title` is implemented as a recorder that vends canned
    `(relations_list, all_info, unwanted_media)` tuples per seed."""

    def __init__(
        self,
        payloads_by_mal_id: dict[int, dict],
        error_for_mal_id: int | None = None,
        search_title_returns: dict[int, tuple] | None = None,
        search_title_error_for_seed: int | None = None,
    ):
        self._payloads = payloads_by_mal_id
        self._error_for = error_for_mal_id
        self.refresh_calls: list[int] = []
        self._search_title_returns = search_title_returns or {}
        self._search_title_error_for_seed = search_title_error_for_seed
        self.search_title_calls: list[int] = []

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

    async def search_title(
        self,
        title=None,
        excluded_mal_ids=None,
        initial_search_limit=3,
        progress=None,
        seed_mal_id=None,
        seed_payload=None,
    ):
        self.search_title_calls.append(seed_mal_id)
        if (
            self._search_title_error_for_seed is not None
            and seed_mal_id == self._search_title_error_for_seed
        ):
            raise RuntimeError(f"simulated MAL outage during BFS for seed {seed_mal_id}")
        return self._search_title_returns.get(seed_mal_id, ([], {}, set()))


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


def test_diff_refuses_to_clobber_score_with_omitted_field():
    """MAL's scored_by is None or > 0; extract_information coerces None
    to 0 for the not-null insert column. A 0/None value during a refresh
    means MAL omitted the field — refuse to overwrite a populated count."""
    media = Media(**media_kwargs(anime_id=1, mal_id=1, score=8.5, scored_by=5_000_000, episodes=12,
        airing_status="Finished Airing",
        aired_to=datetime(2020, 6, 30, tzinfo=timezone.utc),
    ))
    payload = _payload(score=None, scored_by=0)
    assert _apply_media_diff(media, payload) is False
    assert media.score == 8.5
    assert media.scored_by == 5_000_000


# ---------------------------------------------------------------------------
# _apply_metadata_diff (mutates Media; embedding regen monkeypatched)
# ---------------------------------------------------------------------------


_METADATA_BASE = {
    "title": "Title",
    "name_eng": "English Title",
    "name_jap": "日本語タイトル",
    "other_names": [],
    "description": "Plot.",
    "cover_image": "https://example/cover.jpg",
    "age_rating": "PG-13 - Teens 13 or older",
    "original_source": "Manga",
}


def _metadata_payload(**overrides) -> dict:
    """Minimum metadata-bucket fields. Pass overrides to mutate any
    single field; pass None explicitly to exercise the "MAL omitted the
    field" guard."""
    return {**_METADATA_BASE, **overrides}


def _aligned_media(mal_id: int, **media_overrides):
    """Build a Media whose metadata fields already match _METADATA_BASE,
    so a diff with an unmodified `_metadata_payload()` is a no-op. Pass
    overrides to mutate one field at a time — that's the only delta the
    diff should pick up."""
    return Media(**media_kwargs(
        anime_id=1, mal_id=mal_id, **{**_METADATA_BASE, **media_overrides},
    ))


def _patch_regen(monkeypatch) -> list[dict]:
    """Capture calls to regenerate_media_embedding so the metadata diff
    tests don't pay the 50-100ms encode and don't require a real
    MediaSearch row. Returns a list the test asserts against."""
    calls: list[dict] = []

    async def fake_regen(session, media_id, *, title_texts, description_text):
        calls.append({
            "media_id": media_id,
            "title_texts": list(title_texts),
            "description_text": description_text,
        })

    monkeypatch.setattr(
        "app.services.scrape_dispatcher.regenerate_media_embedding", fake_regen,
    )
    return calls


@pytest.mark.asyncio
async def test_metadata_diff_no_change_returns_false(monkeypatch):
    calls = _patch_regen(monkeypatch)
    media = _aligned_media(mal_id=1)
    assert await _apply_metadata_diff(None, media, _metadata_payload()) is False
    assert calls == []


@pytest.mark.asyncio
async def test_metadata_diff_description_change_regenerates_embedding(monkeypatch):
    """Description drift (e.g. MAL replaces a placeholder synopsis with a
    real one) flips the diff and re-encodes — search hits the new text on
    the next request."""
    calls = _patch_regen(monkeypatch)
    media = _aligned_media(mal_id=1, description="Old plot.")
    assert await _apply_metadata_diff(
        None, media, _metadata_payload(description="Fresh plot."),
    ) is True
    assert media.description == "Fresh plot."
    assert len(calls) == 1
    assert calls[0]["description_text"] == "Fresh plot."


@pytest.mark.asyncio
async def test_metadata_diff_cover_only_change_skips_embedding(monkeypatch):
    """Cover image is not part of any embedding text — a cover-only
    update should write the column without paying for an encode."""
    calls = _patch_regen(monkeypatch)
    media = _aligned_media(mal_id=1, cover_image="https://example/old.jpg")
    payload = _metadata_payload(cover_image="https://example/new.jpg")
    assert await _apply_metadata_diff(None, media, payload) is True
    assert media.cover_image == "https://example/new.jpg"
    assert calls == []


@pytest.mark.asyncio
async def test_metadata_diff_title_change_regenerates_embedding(monkeypatch):
    """Title sits inside the description-embedding text too (`title +
    description` mix), so a title-only change still requires re-encoding
    both."""
    calls = _patch_regen(monkeypatch)
    media = _aligned_media(mal_id=1, title="Old Title")
    assert await _apply_metadata_diff(
        None, media, _metadata_payload(title="New Title"),
    ) is True
    assert media.title == "New Title"
    assert len(calls) == 1
    assert "New Title" in calls[0]["title_texts"]


@pytest.mark.asyncio
async def test_metadata_diff_none_passthrough_does_not_clobber(monkeypatch):
    """Mirrors the volatile bucket's None-guard: a missing field in the
    refresh payload (rare, defensive) must not overwrite a populated
    column with NULL."""
    calls = _patch_regen(monkeypatch)
    media = _aligned_media(mal_id=1, name_eng="Existing English")
    payload = _metadata_payload(name_eng=None)
    assert await _apply_metadata_diff(None, media, payload) is False
    assert media.name_eng == "Existing English"
    assert calls == []


@pytest.mark.asyncio
async def test_metadata_diff_name_eng_revealed_regenerates_embedding(monkeypatch):
    """English title arriving late (announcement → simulcast licensing)
    is the most common metadata change on MAL — must propagate to the
    title embedding so search picks up the new alias."""
    calls = _patch_regen(monkeypatch)
    media = _aligned_media(mal_id=1, name_eng=None)
    assert await _apply_metadata_diff(
        None, media, _metadata_payload(name_eng="New English"),
    ) is True
    assert media.name_eng == "New English"
    assert len(calls) == 1
    assert "New English" in calls[0]["title_texts"]


@pytest.mark.asyncio
async def test_metadata_diff_other_names_no_change_skips_regen(monkeypatch):
    """`other_names` is JSON list. Identical content (same order) is the
    common case for a steady-state refresh — no regen, no write."""
    calls = _patch_regen(monkeypatch)
    media = _aligned_media(mal_id=1, other_names=["alpha", "beta"])
    payload = _metadata_payload(other_names=["alpha", "beta"])
    assert await _apply_metadata_diff(None, media, payload) is False
    assert calls == []


@pytest.mark.asyncio
async def test_metadata_diff_other_names_reorder_skips_regen(monkeypatch):
    """MAL doesn't return title_synonyms in a stable order — a pure
    reorder must not fire the 50-100ms embedding regen on noise."""
    calls = _patch_regen(monkeypatch)
    media = _aligned_media(mal_id=1, other_names=["alpha", "beta"])
    payload = _metadata_payload(other_names=["beta", "alpha"])
    assert await _apply_metadata_diff(None, media, payload) is False
    assert calls == []


@pytest.mark.asyncio
async def test_metadata_diff_other_names_added_regenerates_embedding(monkeypatch):
    """A new synonym landing on MAL must flow into the title embedding
    so search-by-alias hits the row on the next query."""
    calls = _patch_regen(monkeypatch)
    media = _aligned_media(mal_id=1, other_names=["alpha"])
    payload = _metadata_payload(other_names=["alpha", "beta"])
    assert await _apply_metadata_diff(None, media, payload) is True
    assert media.other_names == ["alpha", "beta"]
    assert len(calls) == 1
    assert "beta" in calls[0]["title_texts"]


# ---------------------------------------------------------------------------
# _apply_genre_diff + _apply_studio_diff (use db_session)
# ---------------------------------------------------------------------------


async def _seed_genres(db_session, names: list[str]) -> dict[str, Genre]:
    """Create Genre rows with unique names so two test runs in the same
    session don't violate the `unique` constraint. The genre_type is
    fixed to Genres — the diff helper doesn't read genre_type."""
    objs = {}
    for name in names:
        genre = Genre(name=name, genre_type=GenreType.Genres)
        db_session.add(genre)
        objs[name] = genre
    await db_session.flush()
    return objs


async def _build_media_with_taxonomy(
    db_session, mal_id: int,
    genre_names: list[str] | None = None,
    studio_names: list[str] | None = None,
) -> Media:
    """Anime + Media with optional MediaGenre / MediaStudio rows wired
    up. Re-fetched with the sweep's eager-load shape so the diff helpers
    can read `media.media_genre` / `media.media_studio` without tripping
    `lazy="raise"`."""
    anime = Anime(mal_id=mal_id * 10, title=f"A{mal_id}")
    db_session.add(anime)
    await db_session.flush()
    media = Media(**media_kwargs(anime_id=anime.id, mal_id=mal_id))
    db_session.add(media)
    await db_session.flush()
    for name in genre_names or []:
        g = Genre(name=name, genre_type=GenreType.Genres)
        db_session.add(g)
        await db_session.flush()
        db_session.add(MediaGenre(media_id=media.id, genre_id=g.id))
    for name in studio_names or []:
        s = Studio(name=name)
        db_session.add(s)
        await db_session.flush()
        db_session.add(MediaStudio(media_id=media.id, studio_id=s.id))
    await db_session.flush()
    result = await db_session.execute(
        select(Media).where(Media.id == media.id).options(
            selectinload(Media.media_genre).selectinload(MediaGenre.genre),
            selectinload(Media.media_studio).selectinload(MediaStudio.studio),
        )
    )
    return result.scalars().first()


@pytest.mark.asyncio
async def test_genre_diff_no_change_returns_none(db_session):
    media = await _build_media_with_taxonomy(
        db_session, mal_id=-95000, genre_names=["GD_Action_0"],
    )
    assert await _apply_genre_diff(
        db_session, media, {"genres": ["GD_Action_0"]},
    ) is None


@pytest.mark.asyncio
async def test_genre_diff_known_addition_applied(db_session):
    """Pure addition where every new tag is already in the genre table
    is the routine case (MAL retroactively tags an old show with an
    existing Theme). Append the M2M rows silently — the bell still
    reports `applied_count` for transparency."""
    media = await _build_media_with_taxonomy(
        db_session, mal_id=-95001, genre_names=["GD_Action_1"],
    )
    # Seed the addition target as a known genre.
    await _seed_genres(db_session, ["GD_Drama_1"])

    report = await _apply_genre_diff(
        db_session, media, {"genres": ["GD_Action_1", "GD_Drama_1"]},
    )
    assert report is not None
    assert report["kind"] == "additions_applied"
    assert report["unknown_tags"] == []

    # Verify the M2M row landed.
    result = await db_session.execute(
        select(MediaGenre).where(MediaGenre.media_id == media.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_genre_diff_unknown_addition_logs_without_apply(db_session):
    """If MAL adds a tag we've never seen, log it as `unknown_tags` and
    skip the WHOLE batch of additions — half-applying would mean the
    next "what got auto-added since the seeder update?" question can't
    be answered from result_summary alone."""
    media = await _build_media_with_taxonomy(
        db_session, mal_id=-95002, genre_names=["GD_Action_2"],
    )
    await _seed_genres(db_session, ["GD_KnownAdded_2"])

    report = await _apply_genre_diff(
        db_session, media,
        {"genres": ["GD_Action_2", "GD_KnownAdded_2", "GD_NewTag_2"]},
    )
    assert report is not None
    assert report["kind"] == "additions_unknown"
    assert report["unknown_tags"] == ["GD_NewTag_2"]

    # All-or-nothing: even the known addition is skipped until seeder
    # catches up.
    result = await db_session.execute(
        select(MediaGenre).where(MediaGenre.media_id == media.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_genre_diff_removal_logs_without_apply(db_session):
    """MAL removing a genre is rare and worth admin review — never
    auto-applied (don't auto-drop the row, just flag)."""
    media = await _build_media_with_taxonomy(
        db_session, mal_id=-95003, genre_names=["GD_Action_3", "GD_Drama_3"],
    )

    report = await _apply_genre_diff(
        db_session, media, {"genres": ["GD_Action_3"]},
    )
    assert report is not None
    assert report["kind"] == "removal_or_replacement"

    # The dropped MediaGenre row is left intact.
    result = await db_session.execute(
        select(MediaGenre).where(MediaGenre.media_id == media.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_genre_diff_replacement_logs_without_apply(db_session):
    """Add + remove in the same diff classifies as
    removal_or_replacement (the removal branch wins). Same reasoning as
    pure removal — don't trust the swap, just surface it."""
    media = await _build_media_with_taxonomy(
        db_session, mal_id=-95004, genre_names=["GD_Action_4"],
    )
    await _seed_genres(db_session, ["GD_Drama_4"])

    report = await _apply_genre_diff(
        db_session, media, {"genres": ["GD_Drama_4"]},
    )
    assert report is not None
    assert report["kind"] == "removal_or_replacement"

    # Nothing applied — the original genre stays, the new one doesn't land.
    result = await db_session.execute(
        select(MediaGenre).where(MediaGenre.media_id == media.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_studio_diff_no_change_returns_none(db_session):
    media = await _build_media_with_taxonomy(
        db_session, mal_id=-96000, studio_names=["SD_Madhouse_0"],
    )
    assert await _apply_studio_diff(
        media, {"studio": ["SD_Madhouse_0"]},
    ) is None


@pytest.mark.asyncio
async def test_studio_diff_addition_logs_without_apply(db_session):
    """Studio additions DO happen legitimately (co-production credits
    surface after airing) but rare enough that surfacing every change
    is preferable to silently rewriting on a possible MAL bug."""
    media = await _build_media_with_taxonomy(
        db_session, mal_id=-96001, studio_names=["SD_Madhouse_1"],
    )

    report = await _apply_studio_diff(
        media, {"studio": ["SD_Madhouse_1", "SD_MAPPA_1"]},
    )
    assert report is not None
    assert report["kind"] == "any_change"
    assert report["new"] == ["SD_MAPPA_1", "SD_Madhouse_1"]


@pytest.mark.asyncio
async def test_studio_diff_removal_logs_without_apply(db_session):
    media = await _build_media_with_taxonomy(
        db_session, mal_id=-96002, studio_names=["SD_Madhouse_2"],
    )

    report = await _apply_studio_diff(media, {"studio": []})
    assert report is not None
    assert report["kind"] == "any_change"


def test_summarize_drift_empty():
    assert _summarize_drift([]) == {
        "applied_count": 0, "logged_count": 0, "unknown_tags": [], "samples": [],
    }


def test_summarize_drift_counts_and_unions_unknowns():
    """Cross-media unknown tags fold into one sorted list so the bell
    can render "seeder is missing: X, Y" without dedup logic of its own."""
    reports = [
        {"kind": "additions_applied", "unknown_tags": []},
        {"kind": "additions_applied", "unknown_tags": []},
        {"kind": "additions_unknown", "unknown_tags": ["Survival"]},
        {"kind": "additions_unknown", "unknown_tags": ["Survival", "Mecha-Sci-Fi"]},
        {"kind": "removal_or_replacement", "unknown_tags": []},
    ]
    out = _summarize_drift(reports)
    assert out["applied_count"] == 2
    assert out["logged_count"] == 3
    assert out["unknown_tags"] == ["Mecha-Sci-Fi", "Survival"]
    assert out["samples"] == reports  # under 5 → full list


def test_summarize_drift_caps_samples_at_5():
    """`result_summary` is JSONB; bounded samples keep a malformed MAL
    response (drift for every refreshed media) from bloating the column."""
    reports = [{"kind": "any_change", "unknown_tags": []} for _ in range(20)]
    out = _summarize_drift(reports)
    assert out["logged_count"] == 20
    assert len(out["samples"]) == 5


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
            selectinload(Anime.media).options(
                selectinload(Media.freshness),
                selectinload(Media.relation_edges),
                selectinload(Media.media_genre).selectinload(MediaGenre.genre),
                selectinload(Media.media_studio).selectinload(MediaStudio.studio),
            ),
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

    result = await _refresh_one_anime(db_session, anime, scraper)
    _advance_anime_freshness(anime, result.volatile_changed, result.is_currently_airing)

    assert result.volatile_changed is False
    assert result.is_currently_airing is False
    assert result.raw_payloads == {media_mal_id: _payload()}
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

    result = await _refresh_one_anime(db_session, anime, scraper)
    _advance_anime_freshness(anime, result.volatile_changed, result.is_currently_airing)

    assert result.volatile_changed is True
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

    result = await _refresh_one_anime(db_session, anime, scraper)
    _advance_anime_freshness(anime, result.volatile_changed, result.is_currently_airing)

    assert result.volatile_changed is False
    assert result.is_currently_airing is True
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

    result = await _refresh_one_anime(db_session, anime, scraper)
    _advance_anime_freshness(anime, result.volatile_changed, result.is_currently_airing)

    assert anime.freshness.last_checked_at > old_anime_ts
    assert anime.media[0].freshness.last_checked_at > old_media_ts


@pytest.mark.asyncio
async def test_refresh_rewrites_relation_edges_from_full_payload(db_session):
    """Step 1 of the sweep refreshes `MediaRelationEdges` from the
    /anime/{id}/full payload's bundled `relations` block. No extra MAL
    hit — the relations are already in the response that the dispatcher
    uses for canonical-field diffing. Catches MAL changes (new sequels,
    new alt-versions) over the nightly sweep cycle and surfaces bridge
    edges retroactively for pre-v0.14.1 rows."""
    anime = await _build_anime_with_one_media(
        db_session, mal_id_a=-9010, mal_id_m=-9110,
        freshness=AnimeFreshness(last_checked_at=datetime.now(timezone.utc) - timedelta(days=1)),
        media_freshness=MediaFreshness(last_checked_at=datetime.now(timezone.utc) - timedelta(days=1)),
        score=7.5, scored_by=1000, episodes=12, airing_status="Finished Airing",
        aired_to=datetime(2020, 6, 30, tzinfo=timezone.utc),
    )
    # Seed an existing sidecar with one stale edge; the /full payload
    # returns two relations, so the rewrite should replace this.
    db_session.add(MediaRelationEdges(media_id=anime.media[0].id, edges=[[-1, "sequel"]]))
    await db_session.flush()
    await db_session.refresh(anime.media[0], ["relation_edges"])

    media_mal_id = anime.media[0].mal_id
    raw_with_relations = {
        **_payload(),
        "relations": [
            {"relation": "Sequel", "entry": [{"type": "anime", "mal_id": 100}]},
            {"relation": "Side Story", "entry": [{"type": "anime", "mal_id": 200}]},
            {"relation": "Adaptation", "entry": [{"type": "manga", "mal_id": 999}]},
        ],
    }
    scraper = _FakeScraper({media_mal_id: raw_with_relations})

    await _refresh_one_anime(db_session, anime, scraper)

    # Adaptation filtered (cross-franchise), manga entry filtered (non-anime).
    assert anime.media[0].relation_edges.edges == [
        [100, "sequel"],
        [200, "side_story"],
    ]


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

    result = await _refresh_one_anime(db_session, anime, scraper)
    assert anime.media[0].freshness is not None
    _advance_anime_freshness(anime, result.volatile_changed, result.is_currently_airing)

    assert anime.freshness is not None
    assert anime.freshness.stable_check_count == 0


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
                selectinload(Anime.media).options(
                    selectinload(Media.freshness),
                    selectinload(Media.relation_edges),
                    selectinload(Media.media_genre).selectinload(MediaGenre.genre),
                    selectinload(Media.media_studio).selectinload(MediaStudio.studio),
                ),
                selectinload(Anime.freshness),
            )
        )
        rows = {a.id: a for a in result.scalars().all()}
        return [rows[i] for i in anime_ids if i in rows]

    monkeypatch.setattr(AnimeDAO, "select_due_for_sweep", fake_select)


async def _run_dispatcher_harness(
    monkeypatch,
    fake_scraper,
    anime_ids: list[int],
    *,
    patch_probe: bool = False,
    job_id: int = 999,
):
    """Bundles the four monkeypatches the per-test dispatcher setup blocks
    duplicate (JikanScraper factory, ProgressReporter, AnimeDAO selection,
    optional probe pipeline) and runs `update_sweep_dispatcher` against
    a fresh session with a synthetic FakeJob.

    Returns `(summary, attach_calls, recompute_calls)` — the latter two
    are the lists populated by `_patch_probe_pipeline` when patch_probe=True
    (None otherwise) so tests can assert on attach/recompute call counts.
    """
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.JikanScraper", lambda: fake_scraper,
    )
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.ProgressReporter", _NoopProgressReporter,
    )
    _patch_select_due(monkeypatch, anime_ids)
    attach_calls = recompute_calls = None
    if patch_probe:
        attach_calls, recompute_calls = _patch_probe_pipeline(monkeypatch)

    async with async_session_maker() as session:
        job = type("FakeJob", (), {"id": job_id})()
        summary = await update_sweep_dispatcher(session, job)

    return summary, attach_calls, recompute_calls


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
    summary, _, _ = await _run_dispatcher_harness(
        monkeypatch, fake, [a1_id, a2_id],
    )

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
    summary, _, _ = await _run_dispatcher_harness(
        monkeypatch, fake, [a1_id, a2_id, a3_id], job_id=998,
    )

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


# ---------------------------------------------------------------------------
# 7c — relations probe gate (_qualifies_for_relations_probe)
# ---------------------------------------------------------------------------


def _anime_with_freshness(stable_check_count: int) -> Anime:
    """Synthetic in-memory Anime + AnimeFreshness for gate unit tests.
    No DB round trip needed — the gate reads the loaded ORM objects."""
    a = Anime(mal_id=-1, title="A")
    a.freshness = AnimeFreshness(stable_check_count=stable_check_count)
    return a


def test_gate_rejects_currently_airing():
    a = _anime_with_freshness(stable_check_count=10)
    assert _qualifies_for_relations_probe(a, is_currently_airing=True) is False


def test_gate_rejects_stable_below_3():
    a = _anime_with_freshness(stable_check_count=2)
    assert _qualifies_for_relations_probe(a, is_currently_airing=False) is False


def test_gate_accepts_stable_at_or_above_3_and_not_airing():
    a = _anime_with_freshness(stable_check_count=3)
    assert _qualifies_for_relations_probe(a, is_currently_airing=False) is True


def test_gate_handles_missing_freshness_as_zero():
    """A bare anime row (no sidecar yet) is functionally tier-2 — counter
    treated as 0, gate rejects."""
    a = Anime(mal_id=-1, title="A")
    a.freshness = None
    assert _qualifies_for_relations_probe(a, is_currently_airing=False) is False


# ---------------------------------------------------------------------------
# 7c — relations probe behaviour (full-dispatcher integration tests)
#
# The probe seeds JikanScraper.search_title with each Main media's mal_id and
# attaches discovered media to the existing parent anime via
# `attach_search_result_to_anime`. Filter logic (Music/PV/CM/Hentai/Unknown,
# excluded mal_ids, is_main_story) lives inside search_title and is covered
# by user_scrape's existing test surface; tests here focus on the probe's
# specific responsibilities: which anime qualify, which seeds are passed,
# how attaches are routed, and how failures isolate.
# ---------------------------------------------------------------------------


def _patch_probe_pipeline(monkeypatch):
    """Patch attach_search_result_to_anime + spoiler-recompute hooks at
    the dispatcher's import surface. Returns two recorder lists."""
    attach_calls: list[dict] = []
    recompute_calls: list[int] = []

    async def fake_attach(db, parent_anime, graph, all_info, edges=None):
        attach_calls.append({
            "parent_anime_id": parent_anime.id,
            "graph_mal_ids": list(graph.keys()),
            "edges": edges or [],
        })
        existing = {m.mal_id for m in parent_anime.media}
        return sum(1 for mal_id in graph if mal_id not in existing)

    async def fake_recompute(db):
        recompute_calls.append(1)

    monkeypatch.setattr(
        "app.services.scrape_dispatcher.attach_search_result_to_anime", fake_attach,
    )
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.refresh_spoiler_cache_for_all_users",
        fake_recompute,
    )
    return attach_calls, recompute_calls


def _new_graph(seed_mal_id: int, new_mal_id: int) -> tuple:
    """Construct a synthetic search_title return tuple with one new mal_id
    plus the seed. attach (real or faked) decides which to skip. Graph
    entries omit `relation_type` — the dispatcher stamps it via the
    classifier before calling attach."""
    return (
        [
            (
                {
                    seed_mal_id: {"mal_id": seed_mal_id, "media_type": "TV"},
                    new_mal_id: {"mal_id": new_mal_id, "media_type": "TV"},
                },
                [],
                set(),
            )
        ],
        {
            seed_mal_id: {"mal_id": seed_mal_id, "title": "Seed"},
            new_mal_id: {"mal_id": new_mal_id, "title": "Discovered"},
        },
        set(),
    )


@pytest.mark.asyncio
async def test_probe_only_runs_on_tier_3_or_4(tracked_anime, monkeypatch):
    """Three anime — tier 1 (currently airing), tier 2 (stable=1),
    tier 3 (stable=5, finished). search_title must only be invoked
    for the tier-3 anime."""
    a_airing = await _real_seed(
        mal_id=-8301, last_checked_at=datetime.now(timezone.utc) - timedelta(days=10),
        stable_check_count=10, airing_status="Currently Airing",
    )
    a_unstable = await _real_seed(
        mal_id=-8302, last_checked_at=datetime.now(timezone.utc) - timedelta(days=10),
        stable_check_count=1,
    )
    a_tier3 = await _real_seed(
        mal_id=-8303, last_checked_at=datetime.now(timezone.utc) - timedelta(days=10),
        stable_check_count=5,
    )
    tracked_anime.extend([a_airing, a_unstable, a_tier3])

    payloads = {
        -8301 * 100: _payload(airing_status="Currently Airing", aired_to=None),
        -8302 * 100: _payload(),
        -8303 * 100: _payload(),
    }
    fake_scraper = _FakeScraper(payloads)
    summary, _, _ = await _run_dispatcher_harness(
        monkeypatch, fake_scraper, [a_airing, a_unstable, a_tier3],
        patch_probe=True, job_id=7301,
    )

    # search_title called only with the tier-3 anime's main media mal_id.
    assert fake_scraper.search_title_calls == [-8303 * 100]
    assert summary["probe_succeeded"] == 1
    assert summary["probe_failed"] == 0
    assert summary["anime_refreshed"] == 3


@pytest.mark.asyncio
async def test_probe_seeds_search_title_with_each_main_mal_id(
    tracked_anime, monkeypatch,
):
    """Probe must call search_title once per Main media on the parent
    anime — needed to reach disjoint sub-graphs (e.g., a side-story
    branch like Vigilante off BNHA's main). _real_seed creates one main
    per anime; we attach a second main inline. Sidecar edges seeded so
    the in-sweep classifier walks the sequel chain and keeps BOTH labeled
    Main (substance-gate + chain rules promote sequels of the anchor)."""
    from app.models.media import RelationType
    first_main_mal_id = -8410 * 100
    a_id = await _real_seed(
        mal_id=-8410, last_checked_at=datetime.now(timezone.utc) - timedelta(days=10),
        stable_check_count=5,
    )
    tracked_anime.append(a_id)

    second_main_mal_id = first_main_mal_id + 1
    async with async_session_maker() as s:
        # _real_seed media already has a freshness row; fetch its id so
        # we can stamp a sequel edge from it to media2. Stamp episodes +
        # duration_seconds on both so the classifier's substance gate
        # passes — otherwise the non-anchor in the chain gets demoted to
        # side_story and the probe only seeds the anchor.
        result = await s.execute(
            select(Media).where(Media.anime_id == a_id).options(selectinload(Media.relation_edges)),
        )
        first_media = result.scalars().first()
        first_media.episodes = 12
        first_media.duration_seconds = 1440
        s.add(MediaRelationEdges(
            media_id=first_media.id, edges=[[second_main_mal_id, "sequel"]],
        ))
        media2 = Media(**media_kwargs(
            anime_id=a_id, mal_id=second_main_mal_id,
            relation_type=RelationType.Main,
            episodes=12, duration_seconds=1440,
        ))
        s.add(media2)
        await s.flush()
        s.add(MediaFreshness(media_id=media2.id, last_checked_at=None))
        s.add(MediaRelationEdges(
            media_id=media2.id, edges=[[first_main_mal_id, "prequel"]],
        ))
        await s.commit()

    # Sweep refreshes sidecars from each payload's `relations` block, so
    # the chain edges must round-trip through the payload too — otherwise
    # _refresh_one_anime clobbers the seeded edges with [] and the
    # in-sweep classifier demotes media2 to side_story before the probe.
    payloads = {
        first_main_mal_id: {
            **_payload(),
            "relations": [
                {"relation": "Sequel", "entry": [{"type": "anime", "mal_id": second_main_mal_id}]},
            ],
        },
        second_main_mal_id: {
            **_payload(),
            "relations": [
                {"relation": "Prequel", "entry": [{"type": "anime", "mal_id": first_main_mal_id}]},
            ],
        },
    }
    fake_scraper = _FakeScraper(payloads)
    await _run_dispatcher_harness(
        monkeypatch, fake_scraper, [a_id], patch_probe=True, job_id=7410,
    )

    assert sorted(fake_scraper.search_title_calls) == sorted(
        [first_main_mal_id, second_main_mal_id]
    )


@pytest.mark.asyncio
async def test_probe_attach_routes_to_parent_anime(tracked_anime, monkeypatch):
    """search_title returns a graph with a new mal_id; the probe must
    invoke attach_search_result_to_anime with the parent anime (not a
    new one) and the same graph."""
    a_id = await _real_seed(
        mal_id=-8420, last_checked_at=datetime.now(timezone.utc) - timedelta(days=10),
        stable_check_count=5,
    )
    tracked_anime.append(a_id)

    seed_mal_id = -8420 * 100
    new_mal_id = -880_420
    payloads = {seed_mal_id: _payload()}
    fake_scraper = _FakeScraper(
        payloads,
        search_title_returns={seed_mal_id: _new_graph(seed_mal_id, new_mal_id)},
    )
    summary, attach_calls, _ = await _run_dispatcher_harness(
        monkeypatch, fake_scraper, [a_id], patch_probe=True, job_id=7420,
    )

    assert len(attach_calls) == 1
    assert attach_calls[0]["parent_anime_id"] == a_id
    assert sorted(attach_calls[0]["graph_mal_ids"]) == sorted([seed_mal_id, new_mal_id])
    assert summary["probe_succeeded"] == 1


@pytest.mark.asyncio
async def test_spoiler_cache_recomputes_once_per_sweep(tracked_anime, monkeypatch):
    """Two probe-eligible anime, each surfaces a new mal_id via
    search_title. Recompute must fire exactly ONCE at the end of the
    sweep — never per-attach."""
    a1_id = await _real_seed(
        mal_id=-8601, last_checked_at=datetime.now(timezone.utc) - timedelta(days=10),
        stable_check_count=5,
    )
    a2_id = await _real_seed(
        mal_id=-8602, last_checked_at=datetime.now(timezone.utc) - timedelta(days=10),
        stable_check_count=5,
    )
    tracked_anime.extend([a1_id, a2_id])

    s1, s2 = -8601 * 100, -8602 * 100
    payloads = {s1: _payload(), s2: _payload()}
    fake_scraper = _FakeScraper(
        payloads,
        search_title_returns={
            s1: _new_graph(s1, -660_001),
            s2: _new_graph(s2, -660_002),
        },
    )
    summary, attach_calls, recompute_calls = await _run_dispatcher_harness(
        monkeypatch, fake_scraper, [a1_id, a2_id], patch_probe=True, job_id=7601,
    )

    assert len(attach_calls) == 2
    assert len(recompute_calls) == 1
    assert summary["probe_succeeded"] == 2


@pytest.mark.asyncio
async def test_no_recompute_when_probe_finds_nothing_new(tracked_anime, monkeypatch):
    """search_title returns an empty relations_list. The probe makes no
    attach calls; the dispatcher must not fire the recompute."""
    a_id = await _real_seed(
        mal_id=-8701, last_checked_at=datetime.now(timezone.utc) - timedelta(days=10),
        stable_check_count=5,
    )
    tracked_anime.append(a_id)

    # search_title default return is ([], {}, set()) — empty.
    fake_scraper = _FakeScraper({-8701 * 100: _payload()})
    _, attach_calls, recompute_calls = await _run_dispatcher_harness(
        monkeypatch, fake_scraper, [a_id], patch_probe=True, job_id=7701,
    )

    assert attach_calls == []
    assert recompute_calls == []


@pytest.mark.asyncio
async def test_spoiler_recompute_failure_does_not_fail_the_sweep(
    tracked_anime, monkeypatch,
):
    """A spoiler-cache recompute failure must not poison the whole sweep
    summary — the per-anime catalog work is already committed by that point.
    The bell should see a success entry with cache_recompute_failed=True so
    admin can act on the cache separately."""
    a_id = await _real_seed(
        mal_id=-8801, last_checked_at=datetime.now(timezone.utc) - timedelta(days=10),
        stable_check_count=5,
    )
    tracked_anime.append(a_id)

    seed_mal_id = -8801 * 100
    payloads = {seed_mal_id: _payload()}
    fake_scraper = _FakeScraper(
        payloads,
        search_title_returns={seed_mal_id: _new_graph(seed_mal_id, -880_001)},
    )

    attach_calls: list[dict] = []

    async def fake_attach(db, parent_anime, graph, all_info, edges=None):
        attach_calls.append({
            "parent_anime_id": parent_anime.id,
            "graph_mal_ids": list(graph.keys()),
            "edges": edges or [],
        })
        existing = {m.mal_id for m in parent_anime.media}
        return sum(1 for mal_id in graph if mal_id not in existing)

    async def boom_recompute(db):
        raise RuntimeError("simulated recompute failure")

    monkeypatch.setattr(
        "app.services.scrape_dispatcher.attach_search_result_to_anime", fake_attach,
    )
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.refresh_spoiler_cache_for_all_users",
        boom_recompute,
    )

    summary, _, _ = await _run_dispatcher_harness(
        monkeypatch, fake_scraper, [a_id], patch_probe=False, job_id=8801,
    )

    assert summary["cache_recompute_failed"] is True
    assert summary["anime_refreshed"] == 1
    assert summary["probe_succeeded"] == 1


@pytest.mark.asyncio
async def test_probe_persists_unwanted_media_returned_by_search_title(
    tracked_anime, monkeypatch,
):
    """search_title's BFS classifies entries as Music/PV/CM/Hentai/Unknown
    and surfaces them as `unwanted_media`. The probe must persist those
    so a subsequent sweep doesn't re-fetch them, mirroring user_scrape's
    create_unwanted_media path."""
    a_id = await _real_seed(
        mal_id=-8420 - 1, last_checked_at=datetime.now(timezone.utc) - timedelta(days=10),
        stable_check_count=5,
    )
    tracked_anime.append(a_id)

    seed_mal_id = (-8420 - 1) * 100
    unwanted_set = {(-91111, "Some Music PV", "Music")}
    fake_scraper = _FakeScraper(
        {seed_mal_id: _payload()},
        search_title_returns={seed_mal_id: ([], {}, unwanted_set)},
    )
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.JikanScraper", lambda: fake_scraper,
    )
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.ProgressReporter", _NoopProgressReporter,
    )
    _patch_select_due(monkeypatch, [a_id])
    _patch_probe_pipeline(monkeypatch)

    try:
        async with async_session_maker() as session:
            job = type("FakeJob", (), {"id": 7421})()
            await update_sweep_dispatcher(session, job)

        async with async_session_maker() as s:
            row = (await s.execute(
                select(MediaUnwanted).where(MediaUnwanted.mal_id == -91111)
            )).scalars().first()
        assert row is not None
        assert row.reason == "Music"
    finally:
        async with async_session_maker() as s:
            await s.execute(delete(MediaUnwanted).where(MediaUnwanted.mal_id == -91111))
            await s.commit()


@pytest.mark.asyncio
async def test_relations_probe_failure_preserves_field_diff_but_not_anime_freshness(
    tracked_anime, monkeypatch,
):
    """search_title raises mid-probe. Step 1 (field-diff + MediaFreshness)
    must stay committed; step 2 (AnimeFreshness) must roll back so the
    tier query re-selects the anime on the next sweep."""
    seed_ts = datetime.now(timezone.utc) - timedelta(days=10)
    a_id = await _real_seed(
        mal_id=-8801, last_checked_at=seed_ts,
        stable_check_count=5, score=7.5,
    )
    tracked_anime.append(a_id)

    seed_mal_id = -8801 * 100
    payloads = {seed_mal_id: _payload(score=8.5)}
    fake_scraper = _FakeScraper(
        payloads,
        search_title_error_for_seed=seed_mal_id,
    )
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.JikanScraper", lambda: fake_scraper,
    )
    monkeypatch.setattr(
        "app.services.scrape_dispatcher.ProgressReporter", _NoopProgressReporter,
    )
    _patch_select_due(monkeypatch, [a_id])
    _attach, recompute_calls = _patch_probe_pipeline(monkeypatch)

    async with async_session_maker() as session:
        job = type("FakeJob", (), {"id": 7801})()
        summary = await update_sweep_dispatcher(session, job)

    assert summary["probe_failed"] == 1
    assert summary["probe_succeeded"] == 0
    assert summary["anime_refreshed"] == 0
    assert recompute_calls == []

    async with async_session_maker() as s:
        result = await s.execute(
            select(Anime).where(Anime.id == a_id).options(
                selectinload(Anime.media).selectinload(Media.freshness),
                selectinload(Anime.freshness),
            )
        )
        anime = result.scalars().first()

    # Field-diff committed in step 1.
    assert anime.media[0].score == 8.5
    assert anime.media[0].freshness.last_checked_at > seed_ts
    # AnimeFreshness step rolled back — left at seeded values.
    assert anime.freshness.last_checked_at == seed_ts
    assert anime.freshness.stable_check_count == 5


