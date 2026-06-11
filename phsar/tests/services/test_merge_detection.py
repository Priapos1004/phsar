"""Tests for the title+studio merge candidate detector."""

import logging
from typing import NamedTuple

import pytest
from sqlalchemy import select

from app.models.anime import Anime
from app.models.media import Media
from app.models.media_relation_edges import MediaRelationEdges
from app.models.media_studio import MediaStudio
from app.models.media_unwanted import MediaUnwanted
from app.models.merge_candidate import MergeCandidate, MergeCandidateStatus
from app.models.studio import Studio
from app.services.merge_detection_service import (
    DETECTOR_RELATION_LINK,
    DETECTOR_TITLE_DESC,
    DETECTOR_TITLE_STUDIO,
    TITLE_ALONE_THRESHOLD,
    _cosine_similarity,
    _title_score,
    backfill_merge_candidates,
    detect_merge_candidates,
    find_cross_anime_relation_pairs,
    normalize_title,
)
from tests._helpers import media_kwargs

logger = logging.getLogger(__name__)


async def _make_anime_with_studio(db_session, *, mal_id: int, title: str, studio_name: str) -> Anime:
    anime = Anime(mal_id=mal_id, title=title)
    db_session.add(anime)
    await db_session.flush()

    studio = (await db_session.execute(select(Studio).where(Studio.name == studio_name))).scalars().first()
    if studio is None:
        studio = Studio(name=studio_name)
        db_session.add(studio)
        await db_session.flush()

    media = Media(**media_kwargs(anime.id, mal_id * 10, title=f"{title} M1"))
    db_session.add(media)
    await db_session.flush()
    db_session.add(MediaStudio(media_id=media.id, studio_id=studio.id))
    await db_session.flush()
    return anime


def test_normalize_title_strips_season_markers():
    assert normalize_title("Naruto Season 2") == "naruto"
    assert normalize_title("Bleach 2nd Season") == "bleach"
    assert normalize_title("Kara no Kyoukai Part 3") == "kara no kyoukai"
    assert normalize_title("Code Geass III") == "code geass"
    assert normalize_title("  HUNTER x HUNTER  ") == "hunter x hunter"


def test_normalize_title_keeps_distinguishing_words():
    # "Shippuuden" should stay so distinct franchises don't collapse
    norm = normalize_title("Naruto Shippuuden")
    assert "shippuuden" in norm


def test_title_score_catches_subtitle_via_containment():
    """Dr. Stone case: shorter title is a contiguous prefix of the longer.
    SequenceMatcher.ratio() alone would score ~0.62; containment lifts it
    to 1.0 so the title-alone rule fires."""
    a = normalize_title("Dr. Stone")
    b = normalize_title("Dr. Stone: New World")
    assert _title_score(a, b) == 1.0


def test_title_score_low_for_different_franchises():
    """Random shows that share a prefix word shouldn't cross the threshold."""
    assert _title_score("naruto", "bleach") < 0.5
    assert _title_score("boku no hero academia", "boku no pico") < TITLE_ALONE_THRESHOLD


def test_title_score_short_substring_blocked():
    """Single-letter title 'K' must not flag against unrelated 'Knights'.
    Without the size floor + word-boundary check, containment would hit 1.0
    just because the letter 'k' appears at position 0."""
    assert _title_score("k", "knights of sidonia") < 0.5


def test_title_score_two_letter_full_match_blocked():
    """Two-letter shorter title fully matched isn't long enough to be
    diagnostic — common 2-char strings appear inside many longer titles."""
    assert _title_score("ef", "ef a tale of memories") < 0.5


def test_title_score_three_letter_full_match_passes():
    """Three-character title fully contained at word boundaries should still
    flag — len('air') == 3 hits the (full_match AND min_len >= 3) branch."""
    assert _title_score("air", "air the movie") == 1.0


def test_title_score_word_boundary_required():
    """Match without a word boundary on the right side of the longer string
    (size hits 4+ but runs straight into another word) must not count as
    containment. SequenceMatcher.ratio still applies and stays below the
    alone-rule threshold for these distinct strings."""
    assert _title_score("naruto", "narutoshippuuden") < TITLE_ALONE_THRESHOLD


def test_title_score_naruto_shippuuden_still_passes():
    """Regression check: the canonical 'X' / 'X Y' family must still flag.
    The space after 'naruto' in the longer string is a non-alnum boundary."""
    assert _title_score("naruto", "naruto shippuuden") >= TITLE_ALONE_THRESHOLD


def test_title_score_dr_stone_still_passes():
    """Regression check: the Dr. Stone subtitle case (size 9 punctuation-
    bounded match) must continue to score 1.0 after the boundary + floor
    additions. ':' after the match is a non-alnum boundary."""
    assert _title_score("dr. stone", "dr. stone: new world") == 1.0


def test_cosine_similarity_unit_vectors():
    # Identical vectors: 1.0
    assert _cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    # Orthogonal: 0.0
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    # Opposite direction: -1.0 (we don't clamp; caller decides)
    assert _cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_handles_none_and_zero_norm():
    assert _cosine_similarity(None, [1.0, 0.0]) == 0.0
    assert _cosine_similarity([1.0, 0.0], None) == 0.0
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert _cosine_similarity([], []) == 0.0
    # Mismatched lengths: 0.0 instead of crashing
    assert _cosine_similarity([1.0], [1.0, 0.0]) == 0.0


@pytest.mark.asyncio
async def test_detect_flags_pair_with_shared_studio_and_similar_titles(db_session):
    existing = await _make_anime_with_studio(
        db_session, mal_id=70001, title="Test Franchise", studio_name="Shared Studio",
    )
    new = await _make_anime_with_studio(
        db_session, mal_id=70002, title="Test Franchise Season 2", studio_name="Shared Studio",
    )

    inserted = await detect_merge_candidates(db_session, [new.id])
    assert inserted == 1

    a_id, b_id = sorted((existing.id, new.id))
    rows = (await db_session.execute(
        select(MergeCandidate).where(
            MergeCandidate.anime_a_id == a_id,
            MergeCandidate.anime_b_id == b_id,
        )
    )).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.similarity_score >= TITLE_ALONE_THRESHOLD
    assert row.status == MergeCandidateStatus.pending
    assert row.detected_by == DETECTOR_TITLE_STUDIO


@pytest.mark.asyncio
async def test_detect_skips_when_studios_dont_overlap(db_session):
    await _make_anime_with_studio(
        db_session, mal_id=70011, title="Lonely Show", studio_name="Studio Alpha",
    )
    new = await _make_anime_with_studio(
        db_session, mal_id=70012, title="Lonely Show Season 2", studio_name="Studio Beta",
    )

    inserted = await detect_merge_candidates(db_session, [new.id])
    assert inserted == 0


@pytest.mark.asyncio
async def test_detect_skips_when_titles_too_different(db_session):
    await _make_anime_with_studio(
        db_session, mal_id=70021, title="Cowboy Bebop", studio_name="Studio Sunrise",
    )
    new = await _make_anime_with_studio(
        db_session, mal_id=70022, title="Mobile Suit Gundam", studio_name="Studio Sunrise",
    )

    inserted = await detect_merge_candidates(db_session, [new.id])
    assert inserted == 0


@pytest.mark.asyncio
async def test_detect_flags_new_against_new(db_session):
    """A single scrape can split one franchise across two anime rows
    (top-N title search returning near-duplicates). The new × new pass
    flags them so admin sees the candidate without waiting for a restart."""
    a = await _make_anime_with_studio(
        db_session, mal_id=70031, title="Sibling Show", studio_name="Sibling Studio",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=70032, title="Sibling Show Season 2", studio_name="Sibling Studio",
    )

    inserted = await detect_merge_candidates(db_session, [a.id, b.id])
    assert inserted == 1

    a_id, b_id = sorted((a.id, b.id))
    rows = (await db_session.execute(
        select(MergeCandidate).where(
            MergeCandidate.anime_a_id == a_id,
            MergeCandidate.anime_b_id == b_id,
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].detected_by == DETECTOR_TITLE_STUDIO


@pytest.mark.asyncio
async def test_detect_new_against_new_skips_disjoint_studios(db_session):
    """The studio-overlap gate still applies to new × new — unrelated
    titles sharing only a name fragment don't flag without studio overlap."""
    a = await _make_anime_with_studio(
        db_session, mal_id=70033, title="Lonely Sibling", studio_name="Studio A",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=70034, title="Lonely Sibling Season 2", studio_name="Studio B",
    )

    inserted = await detect_merge_candidates(db_session, [a.id, b.id])
    assert inserted == 0


@pytest.mark.asyncio
async def test_detect_idempotent_on_repeat_run(db_session):
    """Re-running detection on the same input flags the pair once and skips
    it on subsequent calls (pre-fetched seen-pairs short-circuits before the
    similarity check)."""
    existing = await _make_anime_with_studio(
        db_session, mal_id=70041, title="Repeat Detector", studio_name="Repeat Studio",
    )
    new = await _make_anime_with_studio(
        db_session, mal_id=70042, title="Repeat Detector Season 2", studio_name="Repeat Studio",
    )

    first = await detect_merge_candidates(db_session, [new.id])
    second = await detect_merge_candidates(db_session, [new.id])
    assert first == 1
    assert second == 0, "second pass should skip via pre-fetched seen_pairs"

    rows = (await db_session.execute(
        select(MergeCandidate).where(
            MergeCandidate.anime_a_id == min(existing.id, new.id),
            MergeCandidate.anime_b_id == max(existing.id, new.id),
        )
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_detect_skips_already_dismissed_pair(db_session):
    """An admin-dismissed pair must not get re-flagged on the next save —
    the seen-pairs filter is status-agnostic."""
    a = await _make_anime_with_studio(
        db_session, mal_id=70051, title="Already Reviewed", studio_name="Review Studio",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=70052, title="Already Reviewed Season 2", studio_name="Review Studio",
    )

    a_id, b_id = sorted((a.id, b.id))
    db_session.add(MergeCandidate(
        anime_a_id=a_id, anime_b_id=b_id,
        similarity_score=0.95, detected_by="title_studio",
        status=MergeCandidateStatus.dismissed,
    ))
    await db_session.flush()

    inserted = await detect_merge_candidates(db_session, [b.id])
    assert inserted == 0

    rows = (await db_session.execute(
        select(MergeCandidate).where(MergeCandidate.anime_a_id == a_id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == MergeCandidateStatus.dismissed


@pytest.mark.asyncio
async def test_backfill_flags_existing_catalog_pair(db_session):
    """Two anime that exist in the catalog without a candidate row get
    flagged on backfill.

    Assertion robust to shared dev-DB state: backfill's relation_link
    sidecar pass can surface pre-existing prod-data pairs in the test DB.
    We assert about OUR specific test pair, not the absolute insert count.
    """
    a = await _make_anime_with_studio(
        db_session, mal_id=70061, title="Backfill Target", studio_name="Backfill Studio",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=70062, title="Backfill Target Season 2", studio_name="Backfill Studio",
    )

    await backfill_merge_candidates(db_session)

    row = await _our_pair_exists(db_session, a.id, b.id)
    assert row is not None
    assert row.status == MergeCandidateStatus.pending


@pytest.mark.asyncio
async def test_backfill_idempotent_across_restarts(db_session):
    """Subsequent backfill runs must produce zero new rows once the first
    run has flagged everything — the pre-fetched seen-pairs set is the
    optimization that keeps startup cost flat as the catalog grows.

    Assertion robust to shared dev-DB state: the first call may flag
    prod-data pairs in addition to our test pair, but the SECOND call
    must always return 0 (idempotency is the property under test).
    """
    await _make_anime_with_studio(
        db_session, mal_id=70071, title="Idempotent A", studio_name="Idempotent Studio",
    )
    await _make_anime_with_studio(
        db_session, mal_id=70072, title="Idempotent A Season 2", studio_name="Idempotent Studio",
    )

    await backfill_merge_candidates(db_session)
    second = await backfill_merge_candidates(db_session)
    assert second == 0


@pytest.mark.asyncio
async def test_detect_relation_link_flags_unrelated_titles(db_session):
    """The relation-link signal trusts MAL: even unrelated-looking titles
    flag if the BFS surfaced one as related to the other (non-crossover).
    No title or studio gate."""
    existing = await _make_anime_with_studio(
        db_session, mal_id=70091, title="Completely Unique Show", studio_name="Studio One",
    )
    new = await _make_anime_with_studio(
        db_session, mal_id=70092, title="Totally Different Title", studio_name="Studio Two",
    )

    inserted = await detect_merge_candidates(
        db_session,
        new_anime_ids=[new.id],
        cross_link_pairs=[(new.id, existing.id)],
    )
    assert inserted == 1

    a_id, b_id = sorted((existing.id, new.id))
    rows = (await db_session.execute(
        select(MergeCandidate).where(
            MergeCandidate.anime_a_id == a_id,
            MergeCandidate.anime_b_id == b_id,
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].detected_by == DETECTOR_RELATION_LINK
    assert rows[0].similarity_score == 1.0


@pytest.mark.asyncio
async def test_detect_relation_link_skips_already_seen_pair(db_session):
    """A pair already in the table (any status) doesn't re-flag via the
    relation_link path either."""
    existing = await _make_anime_with_studio(
        db_session, mal_id=70101, title="Seen Show", studio_name="Studio Seen",
    )
    new = await _make_anime_with_studio(
        db_session, mal_id=70102, title="Seen Show Sequel", studio_name="Studio Seen",
    )

    a_id, b_id = sorted((existing.id, new.id))
    db_session.add(MergeCandidate(
        anime_a_id=a_id, anime_b_id=b_id,
        similarity_score=0.95, detected_by=DETECTOR_TITLE_DESC,
        status=MergeCandidateStatus.dismissed,
    ))
    await db_session.flush()

    inserted = await detect_merge_candidates(
        db_session,
        new_anime_ids=[new.id],
        cross_link_pairs=[(new.id, existing.id)],
    )
    assert inserted == 0


@pytest.mark.asyncio
async def test_backfill_skips_when_catalog_too_small(db_session):
    """The `len(catalog) < 2` guard is an O(1) optimization for fresh
    deployments. The test DB is shared with dev so we can't directly
    assert on it from outside — but we can assert that adding a single
    NEW solo anime (no sidecars to other anime, no studio collisions)
    doesn't trigger any merge_candidate involving it.
    """
    solo = await _make_anime_with_studio(
        db_session, mal_id=70081, title="Brand New Solo Show", studio_name="Brand New Solo Studio",
    )
    await backfill_merge_candidates(db_session)

    rows = (await db_session.execute(
        select(MergeCandidate).where(
            (MergeCandidate.anime_a_id == solo.id)
            | (MergeCandidate.anime_b_id == solo.id)
        )
    )).scalars().all()
    assert rows == []


# ---------------------------------------------------------------------------
# find_cross_anime_relation_pairs + sidecar-as-truth invariants
#
# The sidecar (`media_relation_edges`) is the single source of truth for the
# relation_link signal. These tests pin the contract: which relations fire,
# which don't, scope behavior, dismissed-pair short-circuit. Tests below
# DELIBERATELY don't share studio between A and B — we're verifying the
# relation_link path independently of title_studio / title_desc gates.
# ---------------------------------------------------------------------------


async def _attach_relation_edges(db_session, media_id: int, edges: list[list]) -> None:
    """Insert a MediaRelationEdges sidecar for `media_id` with the given
    `[[target_mal_id, normalized_relation], ...]` payload."""
    db_session.add(MediaRelationEdges(media_id=media_id, edges=edges))
    await db_session.flush()


class _MediaIdPair(NamedTuple):
    id: int
    mal_id: int


async def _media_for_anime(db_session, anime_id: int) -> _MediaIdPair:
    """Return `(media.id, media.mal_id)` for the single Media row under
    `anime_id`. `_make_anime_with_studio` creates exactly one, so the
    `.one()` is unambiguous."""
    row = (await db_session.execute(
        select(Media.id, Media.mal_id).where(Media.anime_id == anime_id)
    )).one()
    return _MediaIdPair(id=row.id, mal_id=row.mal_id)


async def _our_pair_exists(db_session, a_id: int, b_id: int) -> MergeCandidate | None:
    """Look up the merge_candidates row for the (a_id, b_id) pair (after
    sorting). Returns the row if present, else None. Tests use this helper
    instead of asserting on absolute inserted counts because the test DB
    is shared with the dev DB — pre-existing dev data triggers unrelated
    inserts that have nothing to do with the test scenario."""
    a_id, b_id = sorted((a_id, b_id))
    return (await db_session.execute(
        select(MergeCandidate).where(
            MergeCandidate.anime_a_id == a_id,
            MergeCandidate.anime_b_id == b_id,
        )
    )).scalar_one_or_none()


@pytest.mark.asyncio
async def test_sidecar_alt_version_edge_proposes_pair(db_session):
    """The Evangelion case: A's media sidecar contains an alternative_version
    edge to B's media mal_id. No shared studio (relation_link must fire
    without title/studio gates). The pair must land in merge_candidates
    with detected_by=relation_link, similarity_score=1.0."""
    a = await _make_anime_with_studio(
        db_session, mal_id=80001, title="Original NGE Equivalent", studio_name="Studio Gainax",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=80002, title="Rebuild Equivalent", studio_name="Studio Khara",
    )
    a_media = await _media_for_anime(db_session, a.id)
    b_media = await _media_for_anime(db_session, b.id)
    await _attach_relation_edges(
        db_session, a_media.id, [[b_media.mal_id, "alternative_version"]],
    )

    pairs = await find_cross_anime_relation_pairs(db_session, scope_anime_ids=[a.id, b.id])
    a_id, b_id = sorted((a.id, b.id))
    assert (a_id, b_id) in pairs

    await detect_merge_candidates(
        db_session, new_anime_ids=[], cross_link_pairs=pairs,
    )
    row = await _our_pair_exists(db_session, a.id, b.id)
    assert row is not None
    assert row.detected_by == DETECTOR_RELATION_LINK
    assert row.similarity_score == 1.0


@pytest.mark.asyncio
async def test_sidecar_sequel_edge_proposes_pair(db_session):
    """Defensive coverage: sequel/prequel chains are normally merged at scrape
    time by the BFS main-chain logic, but if the BFS leaves them dangling
    across separate jobs, the sidecar-derived path must still propose the
    pair."""
    a = await _make_anime_with_studio(
        db_session, mal_id=80011, title="Some Show A", studio_name="Studio Alpha",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=80012, title="Some Show B", studio_name="Studio Beta",
    )
    a_media = await _media_for_anime(db_session, a.id)
    b_media = await _media_for_anime(db_session, b.id)
    await _attach_relation_edges(
        db_session, a_media.id, [[b_media.mal_id, "sequel"]],
    )

    pairs = await find_cross_anime_relation_pairs(db_session, scope_anime_ids=[a.id, b.id])
    a_id, b_id = sorted((a.id, b.id))
    assert (a_id, b_id) in pairs


@pytest.mark.asyncio
async def test_sidecar_crossover_edge_does_not_propose_pair(db_session):
    """crossover edges are graph boundaries, not duplicate signals. The
    BFS's existing crossover_arrivals tracking excludes them — the SQL
    allowlist must match."""
    a = await _make_anime_with_studio(
        db_session, mal_id=80021, title="Show A", studio_name="Studio One",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=80022, title="Show B", studio_name="Studio Two",
    )
    a_media = await _media_for_anime(db_session, a.id)
    b_media = await _media_for_anime(db_session, b.id)
    await _attach_relation_edges(
        db_session, a_media.id, [[b_media.mal_id, "crossover"]],
    )

    pairs = await find_cross_anime_relation_pairs(db_session, scope_anime_ids=[a.id, b.id])
    a_id, b_id = sorted((a.id, b.id))
    assert (a_id, b_id) not in pairs


@pytest.mark.asyncio
async def test_sidecar_target_in_media_unwanted_does_not_propose_pair(db_session):
    """A target mal_id sitting in media_unwanted is filtered franchise-
    overlap evidence (Music/PV stripped by jikan_scraper at save time).
    It must not count as relation_link signal even when the relation type
    itself is in the allowlist."""
    a = await _make_anime_with_studio(
        db_session, mal_id=80031, title="Show A", studio_name="Studio One",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=80032, title="Show B", studio_name="Studio Two",
    )
    a_media = await _media_for_anime(db_session, a.id)
    b_media = await _media_for_anime(db_session, b.id)
    db_session.add(MediaUnwanted(
        mal_id=b_media.mal_id, title="filtered", reason="Music",
    ))
    await db_session.flush()
    await _attach_relation_edges(
        db_session, a_media.id, [[b_media.mal_id, "alternative_version"]],
    )

    pairs = await find_cross_anime_relation_pairs(db_session, scope_anime_ids=[a.id, b.id])
    a_id, b_id = sorted((a.id, b.id))
    assert (a_id, b_id) not in pairs


@pytest.mark.asyncio
async def test_sidecar_same_anime_target_does_not_propose_pair(db_session):
    """Intra-umbrella relations (one of an anime's media → another media
    under the same anime) are not duplicates — that's what umbrellas ARE."""
    a = await _make_anime_with_studio(
        db_session, mal_id=80041, title="Show With Many Media", studio_name="Studio Solo",
    )
    a_media = await _media_for_anime(db_session, a.id)
    # Add a second media row under the same anime.
    second = Media(**media_kwargs(a.id, 80041_99, title="Second Media"))
    db_session.add(second)
    await db_session.flush()
    await _attach_relation_edges(
        db_session, a_media.id, [[second.mal_id, "sequel"]],
    )

    pairs = await find_cross_anime_relation_pairs(db_session, scope_anime_ids=[a.id])
    # Should not propose any pair involving our test anime — same-anime
    # targets are filtered.
    assert not any(a.id in pair for pair in pairs)


@pytest.mark.asyncio
async def test_dismissed_pair_not_re_proposed_from_sidecar(db_session):
    """Pre-existing merge_candidate (any status) short-circuits the
    relation_link path — admin's prior decisions survive re-detection."""
    a = await _make_anime_with_studio(
        db_session, mal_id=80051, title="Show A", studio_name="Studio One",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=80052, title="Show B", studio_name="Studio Two",
    )
    a_id, b_id = sorted((a.id, b.id))
    db_session.add(MergeCandidate(
        anime_a_id=a_id, anime_b_id=b_id,
        similarity_score=0.95, detected_by=DETECTOR_TITLE_DESC,
        status=MergeCandidateStatus.dismissed,
    ))
    await db_session.flush()
    a_media = await _media_for_anime(db_session, a.id)
    b_media = await _media_for_anime(db_session, b.id)
    await _attach_relation_edges(
        db_session, a_media.id, [[b_media.mal_id, "alternative_version"]],
    )

    pairs = await find_cross_anime_relation_pairs(db_session, scope_anime_ids=[a.id, b.id])
    # Pair is reported by the helper (helper is purely structural)…
    assert (a_id, b_id) in pairs
    # …and detect_merge_candidates skips it because of seen_pairs — the
    # pre-existing dismissed row stays dismissed, no new row added.
    row_count_before = (await db_session.execute(
        select(MergeCandidate).where(
            MergeCandidate.anime_a_id == a_id,
            MergeCandidate.anime_b_id == b_id,
        )
    )).scalars().all()
    await detect_merge_candidates(
        db_session, new_anime_ids=[], cross_link_pairs=pairs,
    )
    row_count_after = (await db_session.execute(
        select(MergeCandidate).where(
            MergeCandidate.anime_a_id == a_id,
            MergeCandidate.anime_b_id == b_id,
        )
    )).scalars().all()
    assert len(row_count_after) == len(row_count_before) == 1


@pytest.mark.asyncio
async def test_scope_anime_ids_filters_pairs(db_session):
    """scope_anime_ids returns pairs where EITHER side is in scope, so
    save/sweep callers can pass their touched anime and still see pairs
    touching them. A pair entirely outside scope is excluded."""
    a = await _make_anime_with_studio(
        db_session, mal_id=80061, title="A", studio_name="Studio 1",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=80062, title="B", studio_name="Studio 2",
    )
    c = await _make_anime_with_studio(
        db_session, mal_id=80063, title="C", studio_name="Studio 3",
    )
    a_media = await _media_for_anime(db_session, a.id)
    b_media = await _media_for_anime(db_session, b.id)
    c_media = await _media_for_anime(db_session, c.id)
    await _attach_relation_edges(db_session, a_media.id, [[b_media.mal_id, "alternative_version"]])
    await _attach_relation_edges(db_session, b_media.id, [[c_media.mal_id, "alternative_version"]])

    a_id, b_id = sorted((a.id, b.id))
    b_id2, c_id = sorted((b.id, c.id))

    # Scope to {A, B, C} sees both test pairs.
    all_pairs = await find_cross_anime_relation_pairs(
        db_session, scope_anime_ids=[a.id, b.id, c.id],
    )
    assert (a_id, b_id) in all_pairs
    assert (b_id2, c_id) in all_pairs

    # Scope to {A} returns the (A,B) pair, NOT the (B,C) pair (B's outgoing
    # edge to C is not in scope from A's perspective).
    a_scoped = await find_cross_anime_relation_pairs(db_session, scope_anime_ids=[a.id])
    assert (a_id, b_id) in a_scoped
    assert (b_id2, c_id) not in a_scoped

    # Scope to {B} returns both pairs (B is on both sides).
    b_scoped = await find_cross_anime_relation_pairs(db_session, scope_anime_ids=[b.id])
    assert (a_id, b_id) in b_scoped
    assert (b_id2, c_id) in b_scoped


@pytest.mark.asyncio
@pytest.mark.parametrize("relation", [
    "spin-off", "side_story", "parent_story", "summary", "full_story", "other",
    # Defensive coverage — these are filtered at parse time today but the
    # SQL filter must survive a future parse-time relaxation.
    "alternative_setting", "character", "adaptation",
])
async def test_sidecar_weak_signal_relations_do_not_propose_pair(db_session, relation):
    """Allowlist contract: only sequel/prequel/alternative_version count.
    If someone later adds a weak type to the allowlist without thinking
    through the false-positive blast radius, this test breaks loudly.
    Dump testing showed these types generate 50+ noise pairs on the
    prod catalog."""
    a = await _make_anime_with_studio(
        db_session, mal_id=80071, title="Show A", studio_name="Studio One",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=80072, title="Show B", studio_name="Studio Two",
    )
    a_media = await _media_for_anime(db_session, a.id)
    b_media = await _media_for_anime(db_session, b.id)
    await _attach_relation_edges(
        db_session, a_media.id, [[b_media.mal_id, relation]],
    )

    pairs = await find_cross_anime_relation_pairs(
        db_session, scope_anime_ids=[a.id, b.id],
    )
    a_id, b_id = sorted((a.id, b.id))
    assert (a_id, b_id) not in pairs, (
        f"relation={relation!r} unexpectedly produced our test pair"
    )


@pytest.mark.asyncio
async def test_backfill_surfaces_relation_link_from_sidecar(db_session):
    """End-to-end: backfill_merge_candidates feeds find_cross_anime_relation_pairs
    into detect_merge_candidates. A catalog-only pair (no live BFS, no
    matching titles, no shared studio) must surface — pre-sidecar
    backfill skipped relation_link entirely."""
    a = await _make_anime_with_studio(
        db_session, mal_id=80081, title="Catalog-Only A", studio_name="Studio Aa",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=80082, title="Catalog-Only B", studio_name="Studio Bb",
    )
    a_media = await _media_for_anime(db_session, a.id)
    b_media = await _media_for_anime(db_session, b.id)
    await _attach_relation_edges(
        db_session, a_media.id, [[b_media.mal_id, "alternative_version"]],
    )

    await backfill_merge_candidates(db_session)
    row = await _our_pair_exists(db_session, a.id, b.id)
    assert row is not None
    assert row.detected_by == DETECTOR_RELATION_LINK
