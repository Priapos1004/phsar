"""Tests for the title+studio merge candidate detector."""

import logging

import pytest
from sqlalchemy import select

from app.models.anime import Anime
from app.models.media import Media
from app.models.media_studio import MediaStudio
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
async def test_detect_does_not_flag_new_against_new(db_session):
    """Two new anime saved together aren't flagged against each other —
    a scrape produces related entries that shouldn't auto-flag as duplicates."""
    a = await _make_anime_with_studio(
        db_session, mal_id=70031, title="Sibling Show", studio_name="Sibling Studio",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=70032, title="Sibling Show Season 2", studio_name="Sibling Studio",
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
    flagged on backfill."""
    a = await _make_anime_with_studio(
        db_session, mal_id=70061, title="Backfill Target", studio_name="Backfill Studio",
    )
    b = await _make_anime_with_studio(
        db_session, mal_id=70062, title="Backfill Target Season 2", studio_name="Backfill Studio",
    )

    inserted = await backfill_merge_candidates(db_session)
    assert inserted == 1

    a_id, b_id = sorted((a.id, b.id))
    rows = (await db_session.execute(
        select(MergeCandidate).where(
            MergeCandidate.anime_a_id == a_id,
            MergeCandidate.anime_b_id == b_id,
        )
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == MergeCandidateStatus.pending


@pytest.mark.asyncio
async def test_backfill_idempotent_across_restarts(db_session):
    """Subsequent backfill runs must produce zero new rows once the first
    run has flagged everything — the pre-fetched seen-pairs set is the
    optimization that keeps startup cost flat as the catalog grows."""
    await _make_anime_with_studio(
        db_session, mal_id=70071, title="Idempotent A", studio_name="Idempotent Studio",
    )
    await _make_anime_with_studio(
        db_session, mal_id=70072, title="Idempotent A Season 2", studio_name="Idempotent Studio",
    )

    first = await backfill_merge_candidates(db_session)
    second = await backfill_merge_candidates(db_session)
    assert first == 1
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
    """No-op when zero or one anime exists — nothing to compare."""
    inserted = await backfill_merge_candidates(db_session)
    assert inserted == 0

    await _make_anime_with_studio(
        db_session, mal_id=70081, title="Solo", studio_name="Solo Studio",
    )
    inserted = await backfill_merge_candidates(db_session)
    assert inserted == 0
