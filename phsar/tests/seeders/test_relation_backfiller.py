"""relation_backfiller re-classifies existing media + rewrites the anime
anchor row when canonical main changes. Tests cover dry-run vs apply,
lazy MAL fetch for empty edges, and idempotency.

Fixtures use NEGATIVE mal_ids so they can't collide with the dev DB's
real (always-positive) MAL ids — the test session is transactional but
reads through the live catalog, so inserts share the unique-mal_id
namespace.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.anime import Anime
from app.models.anime_search import AnimeSearch
from app.models.media import Media, MediaType, RelationType
from app.models.media_relation_edges import MediaRelationEdges
from app.seeders.relation_backfiller import backfill_relations
from app.services.jikan_scraper import JikanScraper
from tests._helpers import media_kwargs


async def _anime_with_media(db, *, anime_mal_id: int, anime_title: str, media_specs: list[dict]) -> Anime:
    """media_specs: each dict carries mal_id, title, media_type, episodes,
    duration_seconds, aired_from, scored_by, relation_type, edges (list).
    The anime's umbrella fields mirror the matching media spec so the
    backfiller's drift detector treats the row as in-sync (matches the
    real `create_anime_from_media` flow).
    """
    anchor_spec = next(
        (s for s in media_specs if s["mal_id"] == anime_mal_id), None,
    )
    assert anchor_spec is not None, (
        f"anime_mal_id={anime_mal_id} must match one of the media_specs"
    )
    anime = Anime(
        mal_id=anime_mal_id, title=anime_title,
        name_eng=anchor_spec.get("name_eng"),
        name_jap=anchor_spec.get("name_jap"),
        other_names=anchor_spec.get("other_names", []),
        description=anchor_spec.get("description"),
        cover_image=anchor_spec.get("cover_image"),
    )
    db.add(anime)
    await db.flush()

    for spec in media_specs:
        media = Media(**media_kwargs(
            anime_id=anime.id,
            mal_id=spec["mal_id"],
            title=spec["title"],
            media_type=spec["media_type"],
            relation_type=spec["relation_type"],
            episodes=spec.get("episodes"),
            duration_seconds=spec.get("duration_seconds"),
            aired_from=spec.get("aired_from"),
            scored_by=spec.get("scored_by", 0),
            cover_image=spec.get("cover_image"),
            description=spec.get("description"),
            other_names=spec.get("other_names", []),
        ))
        db.add(media)
        await db.flush()
        # Stamp last_fetched_at on pre-populated fixtures so the
        # backfiller treats them as already synced — tests should opt
        # into the lazy-fetch path explicitly by omitting the stamp.
        db.add(MediaRelationEdges(
            media_id=media.id,
            edges=spec.get("edges", []),
            last_fetched_at=spec.get("last_fetched_at", datetime.now(timezone.utc)),
        ))
    await db.flush()
    return anime


async def _reload_anime(db, anime_id: int) -> Anime:
    stmt = (
        select(Anime).where(Anime.id == anime_id)
        .options(selectinload(Anime.media).selectinload(Media.relation_edges))
    )
    return (await db.execute(stmt)).scalar_one()


async def test_dry_run_reports_diff_without_writing(db_session, monkeypatch):
    """Evangelion-shaped fixture: anime anchored on Movie 1, Original TV
    is currently side_story. Dry-run reports the anchor change and
    reclassifications without mutating the rows."""
    async def _no_fetch(self, mal_id):
        raise AssertionError("dry-run should not hit MAL when edges are present")
    monkeypatch.setattr(JikanScraper, "fetch_relations", _no_fetch)

    anime = await _anime_with_media(
        db_session,
        anime_mal_id=-2759, anime_title="Evangelion Movie 1: Jo",
        media_specs=[
            # Anchored mal_id matches Movie 1.
            {"mal_id": -2759, "title": "Evangelion 1.0: You Are (Not) Alone",
             "media_type": MediaType.Movie, "relation_type": RelationType.Main,
             "episodes": 1, "duration_seconds": 5400,
             "aired_from": datetime(2007, 9, 1, tzinfo=timezone.utc),
             "scored_by": 600_000,
             "edges": [[-30, "alternative_version"], [2760, "sequel"]]},
            # Original 1995 TV — currently MISCLASSIFIED as SideStory.
            {"mal_id": -30, "title": "Neon Genesis Evangelion",
             "media_type": MediaType.TV, "relation_type": RelationType.SideStory,
             "episodes": 26, "duration_seconds": 1440,
             "aired_from": datetime(1995, 10, 4, tzinfo=timezone.utc),
             "scored_by": 1_200_000,
             "edges": [[-2759, "alternative_version"]]},
        ],
    )

    summary = await backfill_relations(db_session, dry_run=True, anime_ids={anime.id})

    assert summary["anime_scanned"] == 1
    assert summary["anime_changed"] == 1
    assert summary["anchor_changes"] == 1
    assert summary["media_reclassified"] == 2
    assert summary["diffs"][0]["new_anchor_mal_id"] == -30
    assert summary["diffs"][0]["old_anchor_mal_id"] == -2759

    # No writes happened.
    refreshed = await _reload_anime(db_session, anime.id)
    assert refreshed.mal_id == -2759
    by_mal = {m.mal_id: m for m in refreshed.media}
    assert by_mal[-30].relation_type == RelationType.SideStory
    assert by_mal[-2759].relation_type == RelationType.Main


async def test_apply_rewrites_anchor_and_reclassifies(db_session, monkeypatch):
    """Same Evangelion fixture, applied. Expect anchor flipped to mal=30
    (Original TV), Movie 1 reclassified to alternative_version, and the
    anime row's title fields rewritten + embedding regenerated."""
    async def _no_fetch(self, mal_id):
        raise AssertionError("apply should not hit MAL when edges are present")
    monkeypatch.setattr(JikanScraper, "fetch_relations", _no_fetch)

    anime = await _anime_with_media(
        db_session,
        anime_mal_id=-2759, anime_title="Evangelion Movie 1: Jo",
        media_specs=[
            {"mal_id": -2759, "title": "Evangelion 1.0: You Are (Not) Alone",
             "media_type": MediaType.Movie, "relation_type": RelationType.Main,
             "episodes": 1, "duration_seconds": 5400,
             "aired_from": datetime(2007, 9, 1, tzinfo=timezone.utc),
             "scored_by": 600_000,
             "cover_image": "https://example/rebuild.jpg",
             "description": "Rebuild description",
             "other_names": ["Rebuild Alt"],
             "edges": [[-30, "alternative_version"]]},
            {"mal_id": -30, "title": "Neon Genesis Evangelion",
             "media_type": MediaType.TV, "relation_type": RelationType.SideStory,
             "episodes": 26, "duration_seconds": 1440,
             "aired_from": datetime(1995, 10, 4, tzinfo=timezone.utc),
             "scored_by": 1_200_000,
             "cover_image": "https://example/originaltv.jpg",
             "description": "Original TV description",
             "other_names": ["Shin Seiki Evangelion"],
             "edges": [[-2759, "alternative_version"]]},
        ],
    )

    summary = await backfill_relations(db_session, dry_run=False, anime_ids={anime.id})

    assert summary["anime_changed"] == 1
    refreshed = await _reload_anime(db_session, anime.id)
    # All seven umbrella fields rewritten from the new anchor media.
    assert refreshed.mal_id == -30
    assert refreshed.title == "Neon Genesis Evangelion"
    assert refreshed.cover_image == "https://example/originaltv.jpg"
    assert refreshed.description == "Original TV description"
    assert refreshed.other_names == ["Shin Seiki Evangelion"]
    by_mal = {m.mal_id: m for m in refreshed.media}
    assert by_mal[-30].relation_type == RelationType.Main
    assert by_mal[-2759].relation_type == RelationType.AlternativeVersion

    # Embedding regenerated for the new anchor title.
    embed = (await db_session.execute(
        select(AnimeSearch).where(AnimeSearch.anime_id == anime.id)
    )).scalar_one_or_none()
    assert embed is not None


async def test_idempotent_no_op_on_clean_catalog(db_session, monkeypatch):
    """Running over a single TV with no peers does nothing — the anchor
    matches and the only main passes-through unchanged. Empty edges
    triggers a MAL fetch; stubbed to return no relations."""
    async def fake_fetch(self, mal_id):
        return []
    monkeypatch.setattr(JikanScraper, "fetch_relations", fake_fetch)

    anime = await _anime_with_media(
        db_session,
        anime_mal_id=-100, anime_title="Solo Show",
        media_specs=[
            {"mal_id": -100, "title": "Solo Show",
             "media_type": MediaType.TV, "relation_type": RelationType.Main,
             "episodes": 12, "duration_seconds": 1440,
             "aired_from": datetime(2020, 1, 1, tzinfo=timezone.utc),
             "scored_by": 10_000, "edges": []},
        ],
    )

    summary = await backfill_relations(db_session, dry_run=False, anime_ids={anime.id})

    assert summary["anime_scanned"] == 1
    assert summary["anime_changed"] == 0


async def test_lazy_fetch_populates_missing_edges(db_session, monkeypatch):
    """Media with empty `edges` triggers a lazy /relations fetch; the
    fetched edges feed into the classifier for THIS run."""
    fetch_calls: list[int] = []

    async def fake_fetch(self, mal_id):
        fetch_calls.append(mal_id)
        if mal_id == -200:
            return [
                {"relation": "Sequel",
                 "entry": [{"type": "anime", "mal_id": -201}]},
            ]
        if mal_id == -201:
            return [
                {"relation": "Prequel",
                 "entry": [{"type": "anime", "mal_id": -200}]},
            ]
        return []

    monkeypatch.setattr(JikanScraper, "fetch_relations", fake_fetch)

    anime = await _anime_with_media(
        db_session,
        anime_mal_id=-200, anime_title="Test Show",
        media_specs=[
            # last_fetched_at=None opts into the lazy MAL fetch path —
            # otherwise the fixture defaults to "already synced".
            {"mal_id": -200, "title": "Test Show",
             "media_type": MediaType.TV, "relation_type": RelationType.Main,
             "episodes": 12, "duration_seconds": 1440,
             "aired_from": datetime(2020, 1, 1, tzinfo=timezone.utc),
             "scored_by": 10_000, "edges": [], "last_fetched_at": None},
            {"mal_id": -201, "title": "Test Show S2",
             "media_type": MediaType.TV, "relation_type": RelationType.Main,
             "episodes": 12, "duration_seconds": 1440,
             "aired_from": datetime(2021, 1, 1, tzinfo=timezone.utc),
             "scored_by": 8_000, "edges": [], "last_fetched_at": None},
        ],
    )

    summary = await backfill_relations(db_session, dry_run=False, anime_ids={anime.id})

    assert sorted(fetch_calls) == [-201, -200]
    # No reclassification: both are TV in a sequel chain, both stay main.
    assert summary["anime_changed"] == 0
    # Sidecar edges now populated.
    anime = (await db_session.execute(
        select(Anime).where(Anime.mal_id == -200)
        .options(selectinload(Anime.media).selectinload(Media.relation_edges))
    )).scalar_one()
    by_mal = {m.mal_id: m for m in anime.media}
    assert by_mal[-200].relation_edges.edges == [[-201, "sequel"]]
    assert by_mal[-201].relation_edges.edges == [[-200, "prequel"]]


async def test_zero_relations_sidecar_does_not_refetch(db_session, monkeypatch):
    """Anime with legitimately zero relations (standalone movie/special)
    must NOT re-fetch on subsequent restarts. Regression test for the
    v0.14.1 bug where `if sidecar.edges:` falsy-matched the empty list,
    so every restart re-fetched these rows from MAL at 1 req/s forever.
    The fix gates on `last_fetched_at is None` instead."""
    fetch_calls: list[int] = []

    async def fake_fetch(self, mal_id):
        fetch_calls.append(mal_id)
        return []

    monkeypatch.setattr(JikanScraper, "fetch_relations", fake_fetch)

    # First-fetch scenario: sidecar has empty edges and no
    # last_fetched_at stamp. Backfiller fetches MAL once, gets empty,
    # stamps last_fetched_at.
    anime = await _anime_with_media(
        db_session,
        anime_mal_id=-900, anime_title="Standalone Movie",
        media_specs=[
            {"mal_id": -900, "title": "Standalone Movie",
             "media_type": MediaType.Movie, "relation_type": RelationType.Main,
             "duration_seconds": 5400, "scored_by": 5000,
             "aired_from": datetime(2018, 1, 1, tzinfo=timezone.utc),
             "edges": [], "last_fetched_at": None},
        ],
    )

    await backfill_relations(db_session, dry_run=False, anime_ids={anime.id})
    assert fetch_calls == [-900], "first run should fetch once"
    fetch_calls.clear()

    # Second pass simulates a restart. The previous run stamped
    # last_fetched_at; the gate should now skip the MAL call entirely.
    await backfill_relations(db_session, dry_run=False, anime_ids={anime.id})
    assert fetch_calls == [], "subsequent runs must not re-fetch zero-relation rows"


async def test_per_anime_failure_does_not_abort_loop(db_session, monkeypatch):
    """When MAL returns a persistent 5xx for one anime's media, the
    backfiller must rollback + skip that anime and continue with the
    rest. Regression for the v0.14.1 prod incident where the rollback
    expired the anime instance, the subsequent log.exception call
    triggered a lazy reload on expired attributes, and the resulting
    MissingGreenlet escaped the except clause — killing the whole
    backfill loop on the first MAL hiccup."""
    import httpx

    fetch_calls: list[int] = []

    async def fake_fetch(self, mal_id):
        fetch_calls.append(mal_id)
        if mal_id == -700:
            # Simulate a Jikan 504 that bypasses tenacity's retry budget.
            request = httpx.Request("GET", f"https://api.jikan.moe/v4/anime/{mal_id}/relations")
            response = httpx.Response(504, request=request)
            raise httpx.HTTPStatusError("Gateway Timeout", request=request, response=response)
        return []

    monkeypatch.setattr(JikanScraper, "fetch_relations", fake_fetch)

    # Two anime: the first triggers a 504 chain, the second has a
    # populated sidecar and shouldn't be touched.
    bad = await _anime_with_media(
        db_session,
        anime_mal_id=-700, anime_title="Bad MAL Anime",
        media_specs=[
            {"mal_id": -700, "title": "Bad", "media_type": MediaType.Movie,
             "relation_type": RelationType.Main, "duration_seconds": 5400,
             "scored_by": 1000,
             "aired_from": datetime(2019, 1, 1, tzinfo=timezone.utc),
             "edges": [], "last_fetched_at": None},
        ],
    )
    good = await _anime_with_media(
        db_session,
        anime_mal_id=-701, anime_title="Good Anime",
        media_specs=[
            {"mal_id": -701, "title": "Good", "media_type": MediaType.TV,
             "relation_type": RelationType.Main, "episodes": 12,
             "duration_seconds": 1440, "scored_by": 5000,
             "aired_from": datetime(2020, 1, 1, tzinfo=timezone.utc),
             "edges": []},
        ],
    )

    summary = await backfill_relations(
        db_session, dry_run=False, anime_ids={bad.id, good.id},
    )

    # Bad anime tripped the 504; the loop survived and reached the good one.
    assert summary["anime_scanned"] == 2
    assert summary.get("anime_failed") == 1
    assert -700 in fetch_calls
    # Good anime's sidecar already stamped — no MAL fetch attempted.
    assert -701 not in fetch_calls


async def test_anime_without_media_is_skipped(db_session, monkeypatch):
    async def fake_fetch(self, mal_id):
        return []
    monkeypatch.setattr(JikanScraper, "fetch_relations", fake_fetch)

    anime = Anime(
        mal_id=-500, title="Empty",
        name_eng=None, name_jap=None, other_names=[],
        description=None, cover_image=None,
    )
    db_session.add(anime)
    await db_session.flush()

    summary = await backfill_relations(db_session, dry_run=False, anime_ids={anime.id})
    assert summary["anime_scanned"] == 1
    assert summary["anime_changed"] == 0
