"""Unit tests for the spoiler frontier algorithm.

Tests compute_visible_media() — a pure function with no DB dependency.
"""

from uuid import uuid4

from app.services.spoiler_service import _MediaEntry, compute_visible_media


def _entry(
    id: int,
    anime_id: int = 1,
    relation_type: str = "main",
    season_year: int | None = None,
    season_name: str | None = None,
    mal_id: int | None = None,
) -> _MediaEntry:
    """Helper to create a _MediaEntry with defaults."""
    return _MediaEntry(
        id=id,
        uuid=uuid4(),
        anime_id=anime_id,
        relation_type=relation_type,
        season_year=season_year,
        season_name=season_name,
        mal_id=mal_id or id,
    )


def _group(*entries: _MediaEntry) -> dict[int, list[_MediaEntry]]:
    """Group entries by anime_id."""
    groups: dict[int, list[_MediaEntry]] = {}
    for e in entries:
        groups.setdefault(e.anime_id, []).append(e)
    return groups


def test_no_ratings_first_main_visible():
    """No ratings → only first main media visible."""
    s1 = _entry(1, season_year=2020, season_name="Winter")
    s2 = _entry(2, season_year=2021, season_name="Winter")
    s3 = _entry(3, season_year=2022, season_name="Winter")

    visible = compute_visible_media(_group(s1, s2, s3), rated_media_ids=set())
    assert visible == {1}


def test_no_ratings_no_main_first_media_visible():
    """No main media and no ratings → first media overall visible."""
    ova = _entry(1, relation_type="side_story", season_year=2020)
    special = _entry(2, relation_type="summary", season_year=2021)

    visible = compute_visible_media(_group(ova, special), rated_media_ids=set())
    assert visible == {1}


def test_all_main_rated_everything_visible():
    """All main media rated → all media visible."""
    s1 = _entry(1, season_year=2020, season_name="Winter")
    ova = _entry(2, relation_type="side_story", season_year=2020, season_name="Summer")
    s2 = _entry(3, season_year=2021, season_name="Winter")

    visible = compute_visible_media(_group(s1, ova, s2), rated_media_ids={1, 3})
    assert visible == {1, 2, 3}


def test_partial_progress_frontier():
    """Partial progress: S1+S2 rated, S3 is frontier, S4+S5 hidden."""
    s1 = _entry(1, season_year=2020, season_name="Winter")
    s2 = _entry(2, season_year=2021, season_name="Winter")
    s3 = _entry(3, season_year=2022, season_name="Winter")
    s4 = _entry(4, season_year=2023, season_name="Winter")
    s5 = _entry(5, season_year=2024, season_name="Winter")

    visible = compute_visible_media(_group(s1, s2, s3, s4, s5), rated_media_ids={1, 2})
    assert visible == {1, 2, 3}  # S3 is frontier (next to watch)


def test_side_stories_between_rated_mains_visible():
    """Side stories between rated main media and frontier are visible."""
    s1 = _entry(1, season_year=2020, season_name="Winter")
    s2 = _entry(2, season_year=2021, season_name="Winter")
    ona = _entry(3, relation_type="side_story", season_year=2021, season_name="Summer")
    summary = _entry(4, relation_type="summary", season_year=2021, season_name="Fall")
    s3 = _entry(5, season_year=2022, season_name="Winter")
    ova = _entry(6, relation_type="side_story", season_year=2022, season_name="Summer")
    s4 = _entry(7, season_year=2023, season_name="Winter")

    visible = compute_visible_media(
        _group(s1, s2, ona, summary, s3, ova, s4),
        rated_media_ids={1, 2},
    )
    # S1, S2 rated; ONA, Summary before frontier; S3 is frontier
    # OVA and S4 are after frontier → hidden
    assert visible == {1, 2, 3, 4, 5}


def test_single_media_anime_no_rating():
    """Single media anime with no rating → it's the first main, so visible."""
    s1 = _entry(1, season_year=2023, season_name="Spring")

    visible = compute_visible_media(_group(s1), rated_media_ids=set())
    assert visible == {1}


def test_single_media_anime_rated():
    """Single media anime already rated → visible."""
    s1 = _entry(1, season_year=2023, season_name="Spring")

    visible = compute_visible_media(_group(s1), rated_media_ids={1})
    assert visible == {1}


def test_multiple_anime_independent():
    """Multiple anime are computed independently."""
    # Anime 1: S1 rated, S2 is frontier
    a1_s1 = _entry(1, anime_id=1, season_year=2020)
    a1_s2 = _entry(2, anime_id=1, season_year=2021)
    a1_s3 = _entry(3, anime_id=1, season_year=2022)

    # Anime 2: no ratings, first main visible
    a2_s1 = _entry(4, anime_id=2, season_year=2020)
    a2_s2 = _entry(5, anime_id=2, season_year=2021)

    visible = compute_visible_media(
        _group(a1_s1, a1_s2, a1_s3, a2_s1, a2_s2),
        rated_media_ids={1},
    )
    assert visible == {1, 2, 4}  # anime1: S1+S2; anime2: S1 only


def test_rating_on_non_main_does_not_advance_frontier():
    """Rating a side story doesn't advance the main-story frontier,
    but the rated side story itself is still visible."""
    s1 = _entry(1, season_year=2020, season_name="Winter")
    ova = _entry(2, relation_type="side_story", season_year=2020, season_name="Summer")
    s2 = _entry(3, season_year=2021, season_name="Winter")

    # Only the OVA is rated, not S1
    visible = compute_visible_media(_group(s1, ova, s2), rated_media_ids={2})
    # No main rated → frontier is first main (S1), but rated OVA is also visible
    assert visible == {1, 2}


def test_rated_side_story_beyond_frontier_visible():
    """A rated side story beyond the frontier is visible even though
    the frontier hasn't reached it."""
    s1 = _entry(1, season_year=2020, season_name="Winter")
    s2 = _entry(2, season_year=2021, season_name="Winter")
    ova = _entry(3, relation_type="side_story", season_year=2022, season_name="Winter")
    s3 = _entry(4, season_year=2023, season_name="Winter")

    # S1 rated, OVA rated (beyond frontier S2)
    visible = compute_visible_media(_group(s1, s2, ova, s3), rated_media_ids={1, 3})
    # Frontier: S1 rated, next unrated main is S2 → visible up to S2
    # OVA is rated → also visible despite being beyond frontier
    # S3 is not rated and beyond frontier → hidden
    assert visible == {1, 2, 3}


def test_null_seasons_sorted_to_end():
    """Media with no season info are sorted after those with seasons."""
    s1 = _entry(1, season_year=2020, season_name="Winter")
    unknown = _entry(2, season_year=None, season_name=None)
    s2 = _entry(3, season_year=2021, season_name="Winter")

    # S1 rated → S2 is next main → frontier at S2
    # unknown has no season, sorted to end (after S2)
    visible = compute_visible_media(_group(s1, unknown, s2), rated_media_ids={1})
    # S1 (rated) + S2 (frontier) + unknown (between? no, sorted to end after S2)
    # Sorted: S1(2020), S2(2021), unknown(9999) → frontier is S2 (index 1)
    # visible: S1, S2 (index 0, 1) — unknown at index 2 is after frontier
    assert visible == {1, 3}


def test_empty_anime():
    """Empty media list for an anime doesn't crash."""
    visible = compute_visible_media({1: []}, rated_media_ids=set())
    assert visible == set()


def test_empty_input():
    """No anime at all."""
    visible = compute_visible_media({}, rated_media_ids=set())
    assert visible == set()
