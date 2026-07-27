"""Anime-view search filter coverage.

The rule under test: every filter must match the value the anime CARD
displays, not the per-media WHERE value. The card's derivation lives in
`_compute_anime_aggregates` (anime_search_service.py). These tests
construct anime where per-media values and card-derived values DISAGREE,
then assert the filter follows the card.

For filters where any-media WHERE happens to coincide with the card's
semantics (genre majority, studio union, season range bounds collapsing
to any-season membership), we still pin behavior so a future refactor
doesn't drift one without the other.

Test pattern: the dev DB has hundreds of real anime catalog rows, so a
no-query filter call returns the top 50 by weighted-score and our fresh
fixtures (scored_by=0) never make the cut. Each test passes a unique
title `query=` token so vector search scopes results to the fixture set,
then asserts which fixture titles survive the filter via set
intersection — independent of whatever other catalog rows the vector
search returned.
"""

import pytest

from app.models.anime import Anime
from app.models.genre import Genre, GenreType
from app.models.media import Media, MediaType, RelationType
from app.models.media_genre import MediaGenre
from app.models.media_studio import MediaStudio
from app.models.studio import Studio
from app.services.anime_search_service import anime_title_texts
from app.services.vector_embedding_service import create_anime_embedding
from tests._helpers import media_kwargs

ANIME_SEARCH_URL = "/search/anime"


async def _make_anime(db_session, *, mal_id: int, title: str) -> Anime:
    anime = Anime(mal_id=mal_id, title=title, description=title)
    db_session.add(anime)
    await db_session.flush()
    await create_anime_embedding(
        db_session, anime_id=anime.id,
        title_texts=anime_title_texts(anime),
        description_text=anime.description or "",
    )
    return anime


async def _add_media(db_session, anime: Anime, mal_id: int, **overrides) -> Media:
    media = Media(**media_kwargs(anime.id, mal_id, **overrides))
    db_session.add(media)
    await db_session.flush()
    return media


async def _result_fixture_titles(
    client, headers, *, fixture_titles: set[str], **params,
) -> set[str]:
    """Run the search and return the subset of `fixture_titles` present in
    the response. Other catalog rows that happen to vector-match are
    ignored — the assertion is about which fixture rows survive the
    filter, not about the full result set."""
    resp = await client.get(ANIME_SEARCH_URL, params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    response_titles = {a["title"] for a in resp.json()}
    return response_titles & fixture_titles


# ---------------------------------------------------------------------------
# age_rating — card shows MAX(age_rating_numeric); filter must too
# ---------------------------------------------------------------------------

_AGE_FIXTURE_QUERY = "FilterTestAge"
_AGE_FIXTURE_TITLES = {
    f"{_AGE_FIXTURE_QUERY} UniformG Anime",
    f"{_AGE_FIXTURE_QUERY} MixedRating Anime",
}


@pytest.fixture
async def age_rating_set(db_session):
    """Two anime that disagree per-media vs per-card on age_rating:

    - Uniform-G anime: all media G → card shows G.
    - Mixed anime: one media G + one media R → card shows R (max).

    Pre-fix bug: filtering for G surfaced both anime because the WHERE
    matched the G media row inside the mixed anime.
    """
    uniform_g = await _make_anime(
        db_session, mal_id=85001, title=f"{_AGE_FIXTURE_QUERY} UniformG Anime",
    )
    await _add_media(db_session, uniform_g, 850011, age_rating="G - All Ages")
    await _add_media(db_session, uniform_g, 850012, age_rating="G - All Ages")

    mixed = await _make_anime(
        db_session, mal_id=85002, title=f"{_AGE_FIXTURE_QUERY} MixedRating Anime",
    )
    await _add_media(db_session, mixed, 850021, age_rating="G - All Ages")
    await _add_media(
        db_session, mixed, 850022, age_rating="R - 17+ (violence & profanity)",
    )

    return {"uniform_g": uniform_g, "mixed": mixed}


async def test_age_rating_g_hides_mixed_anime(client, user_auth_headers, age_rating_set):
    seen = await _result_fixture_titles(
        client, user_auth_headers,
        fixture_titles=_AGE_FIXTURE_TITLES,
        query=_AGE_FIXTURE_QUERY,
        age_rating="G - All Ages",
    )
    assert seen == {f"{_AGE_FIXTURE_QUERY} UniformG Anime"}


async def test_age_rating_r_returns_mixed_only(client, user_auth_headers, age_rating_set):
    seen = await _result_fixture_titles(
        client, user_auth_headers,
        fixture_titles=_AGE_FIXTURE_TITLES,
        query=_AGE_FIXTURE_QUERY,
        age_rating="R - 17+ (violence & profanity)",
    )
    assert seen == {f"{_AGE_FIXTURE_QUERY} MixedRating Anime"}


async def test_age_rating_g_or_r_returns_both(client, user_auth_headers, age_rating_set):
    resp = await client.get(
        ANIME_SEARCH_URL,
        params=[
            ("query", _AGE_FIXTURE_QUERY),
            ("age_rating", "G - All Ages"),
            ("age_rating", "R - 17+ (violence & profanity)"),
        ],
        headers=user_auth_headers,
    )
    assert resp.status_code == 200
    seen = {a["title"] for a in resp.json()} & _AGE_FIXTURE_TITLES
    assert seen == _AGE_FIXTURE_TITLES


# ---------------------------------------------------------------------------
# airing_status — card derives by priority (Current → Finished → Upcoming);
# filter must follow that derivation, not any-media membership.
# ---------------------------------------------------------------------------

_AIRING_FIXTURE_QUERY = "FilterTestAiring"
_AIRING_FIXTURE_TITLES = {
    f"{_AIRING_FIXTURE_QUERY} FinishedOnly Anime",
    f"{_AIRING_FIXTURE_QUERY} MixedCurrent Anime",
    f"{_AIRING_FIXTURE_QUERY} FinishedPlusUpcoming Anime",
}


@pytest.fixture
async def airing_status_set(db_session):
    """Three anime spanning the priority ladder:

    - finished_only: all media Finished → card: Finished.
    - mixed_current: Finished + Currently Airing → card: Currently Airing.
    - finished_plus_upcoming: Finished + Not yet aired → card: Finished
      (has_upcoming = True, but the primary status stays Finished).

    Pre-fix bug: filtering "Finished" returned mixed_current too, because
    its Finished side-story passed the WHERE.
    """
    finished_only = await _make_anime(
        db_session, mal_id=85101, title=f"{_AIRING_FIXTURE_QUERY} FinishedOnly Anime",
    )
    await _add_media(db_session, finished_only, 851011, airing_status="Finished Airing")
    await _add_media(db_session, finished_only, 851012, airing_status="Finished Airing")

    mixed_current = await _make_anime(
        db_session, mal_id=85102, title=f"{_AIRING_FIXTURE_QUERY} MixedCurrent Anime",
    )
    await _add_media(db_session, mixed_current, 851021, airing_status="Finished Airing")
    await _add_media(db_session, mixed_current, 851022, airing_status="Currently Airing")

    finished_plus_upcoming = await _make_anime(
        db_session, mal_id=85103,
        title=f"{_AIRING_FIXTURE_QUERY} FinishedPlusUpcoming Anime",
    )
    await _add_media(db_session, finished_plus_upcoming, 851031, airing_status="Finished Airing")
    await _add_media(db_session, finished_plus_upcoming, 851032, airing_status="Not yet aired")

    return {
        "finished_only": finished_only,
        "mixed_current": mixed_current,
        "finished_plus_upcoming": finished_plus_upcoming,
    }


async def test_airing_status_currently_airing_returns_mixed_current(
    client, user_auth_headers, airing_status_set,
):
    seen = await _result_fixture_titles(
        client, user_auth_headers,
        fixture_titles=_AIRING_FIXTURE_TITLES,
        query=_AIRING_FIXTURE_QUERY,
        airing_status="Currently Airing",
    )
    assert seen == {f"{_AIRING_FIXTURE_QUERY} MixedCurrent Anime"}


async def test_airing_status_finished_excludes_mixed_current(
    client, user_auth_headers, airing_status_set,
):
    seen = await _result_fixture_titles(
        client, user_auth_headers,
        fixture_titles=_AIRING_FIXTURE_TITLES,
        query=_AIRING_FIXTURE_QUERY,
        airing_status="Finished Airing",
    )
    # FinishedPlusUpcoming: card priority is Finished (no current), so it
    # must be included. MixedCurrent: card collapses to Currently Airing,
    # must be excluded.
    assert seen == {
        f"{_AIRING_FIXTURE_QUERY} FinishedOnly Anime",
        f"{_AIRING_FIXTURE_QUERY} FinishedPlusUpcoming Anime",
    }


async def test_airing_status_not_yet_aired_excludes_all_fixtures(
    client, user_auth_headers, airing_status_set,
):
    """None of the fixture anime collapse to "Not yet aired" — each has
    at least one Finished or Currently Airing media. The filter must
    exclude all of them."""
    seen = await _result_fixture_titles(
        client, user_auth_headers,
        fixture_titles=_AIRING_FIXTURE_TITLES,
        query=_AIRING_FIXTURE_QUERY,
        airing_status="Not yet aired",
    )
    assert seen == set()


# ---------------------------------------------------------------------------
# Filters that already match the card (any-media WHERE semantics align).
# Pin behavior so future drift is caught.
# ---------------------------------------------------------------------------

_STUDIO_FIXTURE_QUERY = "FilterTestStudio"
_STUDIO_FIXTURE_TITLES = {
    f"{_STUDIO_FIXTURE_QUERY} WithStudio Anime",
    f"{_STUDIO_FIXTURE_QUERY} WithoutStudio Anime",
}


@pytest.fixture
async def studio_set(db_session):
    """Two anime, only one has 'Pinned Studio' on any media. Card shows
    studios as the union — filter is any-media membership."""
    studio = Studio(name="Pinned Studio")
    db_session.add(studio)
    await db_session.flush()

    with_studio = await _make_anime(
        db_session, mal_id=85201, title=f"{_STUDIO_FIXTURE_QUERY} WithStudio Anime",
    )
    media = await _add_media(db_session, with_studio, 852011)
    db_session.add(MediaStudio(media_id=media.id, studio_id=studio.id))
    await db_session.flush()

    without_studio = await _make_anime(
        db_session, mal_id=85202, title=f"{_STUDIO_FIXTURE_QUERY} WithoutStudio Anime",
    )
    await _add_media(db_session, without_studio, 852021)

    return {"with_studio": with_studio, "without_studio": without_studio}


async def test_studio_filter_matches_card_union(client, user_auth_headers, studio_set):
    seen = await _result_fixture_titles(
        client, user_auth_headers,
        fixture_titles=_STUDIO_FIXTURE_TITLES,
        query=_STUDIO_FIXTURE_QUERY,
        studio_name="Pinned Studio",
    )
    assert seen == {f"{_STUDIO_FIXTURE_QUERY} WithStudio Anime"}


_MEDIA_TYPE_FIXTURE_QUERY = "FilterTestMediaType"
_MEDIA_TYPE_FIXTURE_TITLES = {
    f"{_MEDIA_TYPE_FIXTURE_QUERY} HasTV Anime",
    f"{_MEDIA_TYPE_FIXTURE_QUERY} MovieOnly Anime",
}


@pytest.fixture
async def media_type_set(db_session):
    """Anime with at least one TV media vs anime with only Movie media.
    Card's `media_types` list reflects any-media membership; filter
    semantics match."""
    has_tv = await _make_anime(
        db_session, mal_id=85301, title=f"{_MEDIA_TYPE_FIXTURE_QUERY} HasTV Anime",
    )
    await _add_media(db_session, has_tv, 853011, media_type=MediaType.TV)
    await _add_media(db_session, has_tv, 853012, media_type=MediaType.Movie)

    movie_only = await _make_anime(
        db_session, mal_id=85302, title=f"{_MEDIA_TYPE_FIXTURE_QUERY} MovieOnly Anime",
    )
    await _add_media(db_session, movie_only, 853021, media_type=MediaType.Movie)

    return {"has_tv": has_tv, "movie_only": movie_only}


async def test_media_type_filter_matches_any_media_membership(
    client, user_auth_headers, media_type_set,
):
    seen = await _result_fixture_titles(
        client, user_auth_headers,
        fixture_titles=_MEDIA_TYPE_FIXTURE_TITLES,
        query=_MEDIA_TYPE_FIXTURE_QUERY,
        media_type="TV",
    )
    assert seen == {f"{_MEDIA_TYPE_FIXTURE_QUERY} HasTV Anime"}


# ---------------------------------------------------------------------------
# Combo test: HAVING-clause stacking
# ---------------------------------------------------------------------------

_COMBO_FIXTURE_QUERY = "FilterTestCombo"
_COMBO_FIXTURE_TITLES = {
    f"{_COMBO_FIXTURE_QUERY} RFinished Anime",
    f"{_COMBO_FIXTURE_QUERY} RCurrently Anime",
}


@pytest.fixture
async def combo_set(db_session):
    """Two anime: both R-rated card-wise; only one has Currently Airing
    on the card. Stacked age_rating + airing_status filter must apply both
    HAVING conditions correctly."""
    r_finished = await _make_anime(
        db_session, mal_id=85401, title=f"{_COMBO_FIXTURE_QUERY} RFinished Anime",
    )
    await _add_media(
        db_session, r_finished, 854011,
        age_rating="R - 17+ (violence & profanity)",
        airing_status="Finished Airing",
    )

    r_currently = await _make_anime(
        db_session, mal_id=85402, title=f"{_COMBO_FIXTURE_QUERY} RCurrently Anime",
    )
    await _add_media(
        db_session, r_currently, 854021,
        age_rating="R - 17+ (violence & profanity)",
        airing_status="Currently Airing",
    )

    return {"r_finished": r_finished, "r_currently": r_currently}


async def test_age_rating_and_airing_status_stacked(client, user_auth_headers, combo_set):
    resp = await client.get(
        ANIME_SEARCH_URL,
        params=[
            ("query", _COMBO_FIXTURE_QUERY),
            ("age_rating", "R - 17+ (violence & profanity)"),
            ("airing_status", "Currently Airing"),
        ],
        headers=user_auth_headers,
    )
    assert resp.status_code == 200
    seen = {a["title"] for a in resp.json()} & _COMBO_FIXTURE_TITLES
    assert seen == {f"{_COMBO_FIXTURE_QUERY} RCurrently Anime"}


# ---------------------------------------------------------------------------
# Filter-independence of the score — a filter selects WHICH ANIME, never which
# media feed the aggregates. When the filter narrowed the grouped media rows,
# `avg_score`/`avg_scored_by` (and thus the no-query weighted-score ordering)
# were computed over the filter-matched media while the CARD showed the mean
# over all of the anime's main media, so results came back out of order:
#   - side-story-only credit → weight 0 → NULL metric → sorted last
#   - partial main credit    → metric drifted off the shown score
# See compound-docs/2026-07-19-anime-score-main-only.md.
# ---------------------------------------------------------------------------

_SCOPE_STUDIO = "Scope Independence Studio"


@pytest.fixture
async def scope_independence_set(db_session):
    """Two anime credited to one studio through media that are NOT their whole
    main story, so the filter-matched subset and the main-story set disagree:

    - SideStoryCredited: studio only on a SideStory (weight 0) — the matched
      subset holds no scored main at all, so a narrowed aggregate is NULL.
    - PartiallyCredited: studio on one of two mains — the matched subset's mean
      (6.0) is lower than the card's mean over both (7.0).

    Card scores order them 9.0 > 7.0; both narrowed aggregates invert that
    (NULL sorts last, 6.0 outranks nothing).
    """
    studio = Studio(name=_SCOPE_STUDIO)
    db_session.add(studio)
    await db_session.flush()

    side_credited = await _make_anime(
        db_session, mal_id=85501, title="ScopeTest SideStoryCredited Anime",
    )
    await _add_media(db_session, side_credited, 855011, score=9.0, scored_by=1_000)
    side_story = await _add_media(
        db_session, side_credited, 855012,
        relation_type=RelationType.SideStory, score=5.0, scored_by=1_000,
    )
    db_session.add(MediaStudio(media_id=side_story.id, studio_id=studio.id))

    partially_credited = await _make_anime(
        db_session, mal_id=85502, title="ScopeTest PartiallyCredited Anime",
    )
    credited_main = await _add_media(
        db_session, partially_credited, 855021, score=6.0, scored_by=1_000,
    )
    db_session.add(MediaStudio(media_id=credited_main.id, studio_id=studio.id))
    await _add_media(db_session, partially_credited, 855022, score=8.0, scored_by=1_000)
    await db_session.flush()


async def test_studio_filter_does_not_rescope_score_or_ordering(
    client, user_auth_headers, scope_independence_set,
):
    """No query → ordering is the weighted score, and it must be the score the
    card shows: the filter picks anime, not the media the score averages.

    The unique studio name scopes the result set to exactly the fixtures, so the
    whole response is asserted (no limit-50 window to clear).
    """
    resp = await client.get(
        ANIME_SEARCH_URL,
        params={"studio_name": _SCOPE_STUDIO},
        headers=user_auth_headers,
    )
    assert resp.status_code == 200, resp.text

    assert [
        (a["title"], a["avg_score"], a["avg_scored_by"]) for a in resp.json()
    ] == [
        ("ScopeTest SideStoryCredited Anime", 9.0, 1_000),
        ("ScopeTest PartiallyCredited Anime", 7.0, 1_000),
    ]


_MAJORITY_STUDIO = "Majority Scope Studio"
_MAJORITY_GENRE = "ScopeTestGenre"


@pytest.fixture
async def genre_majority_with_prefilter_set(db_session):
    """One anime, 3 media, the genre on only 1 of them — a minority, so the card
    does not list it and the genre filter must not match. The studio is credited
    to that single genre-carrying media, which is what makes the pairing sharp:
    `media_count` is the denominator of the `count * 2 > media_count` majority
    check, so a filter that narrowed the grouped rows to the one credited media
    would compare 1 against 1 and let the minority genre pass.
    """
    studio = Studio(name=_MAJORITY_STUDIO)
    genre = Genre(
        name=_MAJORITY_GENRE, genre_type=GenreType.Genres, description="scope test",
    )
    db_session.add_all([studio, genre])
    await db_session.flush()

    anime = await _make_anime(
        db_session, mal_id=85601, title="ScopeTest MinorityGenre Anime",
    )
    credited = await _add_media(db_session, anime, 856011, score=8.0, scored_by=1_000)
    await _add_media(db_session, anime, 856012, score=8.0, scored_by=1_000)
    await _add_media(db_session, anime, 856013, score=8.0, scored_by=1_000)

    db_session.add(MediaStudio(media_id=credited.id, studio_id=studio.id))
    db_session.add(MediaGenre(media_id=credited.id, genre_id=genre.id))
    await db_session.flush()


async def test_genre_majority_denominator_survives_a_pre_filter(
    client, user_auth_headers, genre_majority_with_prefilter_set,
):
    """The genre-majority HAVING counts over all of the anime's media, so its
    `media_count` denominator has to as well — a stacked studio filter must not
    shrink it into agreeing that a 1-of-3 genre is a majority."""
    resp = await client.get(
        ANIME_SEARCH_URL,
        params=[("studio_name", _MAJORITY_STUDIO), ("genre_name", _MAJORITY_GENRE)],
        headers=user_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
