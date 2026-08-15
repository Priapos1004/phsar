"""Title-search ranking — substring-match bonus.

Pure cosine-distance ranking can promote thematically-similar shows
over titles that literally contain the user's query. Concrete case:
"Lord of" surfaces "Overlord" above "Lord of Mysteries" because the
embeddings cluster on theme, not literal token match. The
`_TITLE_MATCH_BONUS_WEIGHT` reduction in `apply_vector_ordering`
nudges substring-containing titles ahead.

Fixture rows are scoped to a `SentinelSeason`; every query goes through
`_ordered_fixture_titles`.
"""

import pytest

from app.daos.search_filters import _escape_like
from app.models.anime import Anime
from app.models.media import Media
from app.services.anime_search_service import anime_title_texts
from app.services.vector_embedding_service import (
    create_anime_embedding,
    create_media_embedding,
)
from tests._helpers import SentinelSeason, media_kwargs

ANIME_SEARCH_URL = "/search/anime"
MEDIA_SEARCH_URL = "/search/media"

_RANK_SEASON = SentinelSeason(1902)


async def _make_anime_with_media_titled(
    db_session, *, mal_id: int, anime_title: str, media_titles: list[str],
) -> Anime:
    anime = Anime(mal_id=mal_id, title=anime_title, description=anime_title)
    db_session.add(anime)
    await db_session.flush()
    await create_anime_embedding(
        db_session, anime_id=anime.id,
        title_texts=anime_title_texts(anime),
        description_text=anime.description or "",
    )
    for i, media_title in enumerate(media_titles):
        media = Media(**media_kwargs(
            anime.id, mal_id * 10 + i, title=media_title,
            **_RANK_SEASON.columns,
        ))
        db_session.add(media)
        await db_session.flush()
        await create_media_embedding(
            db_session, media_id=media.id,
            title_texts=[media.title], description_text=media.title,
        )
    return anime


# ---------------------------------------------------------------------------
# Anime view
# ---------------------------------------------------------------------------

_RANK_FIXTURE_QUERY = "FilterTestRank"


@pytest.fixture
async def lord_of_anime_set(db_session):
    """Anime sharing the `FilterTestRank` query prefix, each with a
    different relationship to the substring "Lord of":

    - 'Lord of Mysteries' contains the substring → gets the bonus
    - 'The Lord of the Rings' contains the substring → gets the bonus
    - 'Overlord Show' contains "Lord" but NOT "Lord of" as a contiguous
      substring → no bonus
    - 'Unrelated Anime' has neither → no bonus

    Returns the titles it inserted, which every consumer passes as the helper's
    `expect`. Each anime's one media carries the anime's own title, so the set
    serves the media view unchanged.
    """
    titles = [
        f"{_RANK_FIXTURE_QUERY} Lord of Mysteries",
        f"{_RANK_FIXTURE_QUERY} The Lord of the Rings",
        f"{_RANK_FIXTURE_QUERY} Overlord Show",
        f"{_RANK_FIXTURE_QUERY} Unrelated Anime",
    ]
    for offset, title in enumerate(titles):
        await _make_anime_with_media_titled(
            db_session, mal_id=87001 + offset,
            anime_title=title, media_titles=[title],
        )
    return set(titles)


async def _ordered_fixture_titles(
    client, headers, *, url: str, expect: set[str], **params,
) -> list[str]:
    """The fixture's rows in response order, checked to be all of them.

    Every caller's assertion passes on an empty or truncated list, so the check
    that makes them mean anything belongs here rather than in each test that
    remembers to write it. `expect` is the whole set the caller's fixture
    inserted: requiring equality catches both a row lost to a missing embedding
    or a dropped join, and a season string that stopped parsing — which is
    logged and dropped, silently widening the response to the catalogue."""
    resp = await client.get(
        url,
        params={**params, "anime_season": _RANK_SEASON.filter},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    titles = [a["title"] for a in resp.json()]
    assert set(titles) == expect, (
        f"response is not the fixture's row set: missing {sorted(expect - set(titles))}, "
        f"unexpected {sorted(set(titles) - expect)}"
    )
    return titles


def _assert_matchers_first(ordered: list[str], matchers: set[str], non_matchers: set[str]):
    """Every matcher ahead of every non-matcher — compared at the boundary
    (last matcher vs first non-matcher) so the two groups may order internally
    however the embedding distance puts them."""
    matcher_positions = [i for i, t in enumerate(ordered) if t in matchers]
    non_matcher_positions = [i for i, t in enumerate(ordered) if t in non_matchers]
    assert max(matcher_positions) < min(non_matcher_positions), (
        f"Non-matcher ranked above a matcher. Order: {ordered}"
    )


async def test_anime_substring_match_outranks_non_match(
    client, user_auth_headers, lord_of_anime_set,
):
    """The two anime whose titles contain "Lord of" must come before the
    Overlord/Unrelated rows. Pure cosine could put them in any order;
    the substring bonus forces matchers first."""
    matchers = {
        f"{_RANK_FIXTURE_QUERY} Lord of Mysteries",
        f"{_RANK_FIXTURE_QUERY} The Lord of the Rings",
    }
    non_matchers = {
        f"{_RANK_FIXTURE_QUERY} Overlord Show",
        f"{_RANK_FIXTURE_QUERY} Unrelated Anime",
    }
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers,
        url=ANIME_SEARCH_URL,
        expect=lord_of_anime_set,
        query=f"{_RANK_FIXTURE_QUERY} Lord of",
    )
    _assert_matchers_first(ordered, matchers, non_matchers)


async def test_anime_query_case_does_not_change_ranking(
    client, user_auth_headers, lord_of_anime_set,
):
    """Capitalising the query must not change results. The reported bug:
    typing "Kurokos" instead of "kurokos" buried Kuroko's Basketball
    because the cased embedding model gave the two a materially different
    vector. `generate_embedding` now folds case, and the SQL bonuses were
    already case-insensitive, so query case is irrelevant end to end."""
    lower = await _ordered_fixture_titles(
        client, user_auth_headers, url=ANIME_SEARCH_URL, expect=lord_of_anime_set,
        query=f"{_RANK_FIXTURE_QUERY} Lord of",
    )
    upper = await _ordered_fixture_titles(
        client, user_auth_headers, url=ANIME_SEARCH_URL, expect=lord_of_anime_set,
        query=f"{_RANK_FIXTURE_QUERY} Lord of".upper(),
    )
    assert lower == upper, f"Query case changed ranking: {lower} vs {upper}"


# ---------------------------------------------------------------------------
# Fuzzy / typo tolerance via pg_trgm
# ---------------------------------------------------------------------------

async def test_anime_fuzzy_typo_lifts_best_match_above_unrelated(
    client, user_auth_headers, lord_of_anime_set,
):
    """Typo "lor of" (missing 'd') doesn't substring-match anything, but
    pg_trgm trigram similarity gives "Lord of Mysteries" a strong fuzzy
    bonus. Production win: the user's mistyped query still surfaces the
    intended show near the top instead of leaving it buried by raw
    embedding distance. The strongest fuzzy matcher must rank before
    the explicitly-unrelated title.

    NOTE: weaker fuzzy matchers (Lord of Rings, Overlord) can still land
    below Unrelated depending on the multilingual MiniLM embedding's
    cosine variance — that's a test-fixture limitation, not a
    production bug. The test pins the high-confidence outcome only.
    """
    best_matcher = f"{_RANK_FIXTURE_QUERY} Lord of Mysteries"
    unrelated = f"{_RANK_FIXTURE_QUERY} Unrelated Anime"
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers,
        url=ANIME_SEARCH_URL,
        expect=lord_of_anime_set,
        query=f"{_RANK_FIXTURE_QUERY} lor of",
    )
    assert ordered.index(best_matcher) < ordered.index(unrelated), (
        f"Best fuzzy matcher ranked below the unrelated title. "
        f"pg_trgm bonus may not be firing. Order: {ordered}"
    )


# ---------------------------------------------------------------------------
# Anime-view ranking is invariant to how many media an anime has
# ---------------------------------------------------------------------------

@pytest.fixture
async def uneven_media_count_set(db_session):
    """Two substring-matching anime with wildly different media counts (6 vs 1),
    plus a non-matcher. Their titles differ, so their title embeddings differ
    too — what the pair isolates is not embedding distance but how many rows
    each contributes to the GROUP BY.

    Returns the anime titles it inserted, for the helper's `expect`. The
    franchise's media are titled per-season and so are not in that set — this
    fixture serves the anime view only.
    """
    franchise = f"{_RANK_FIXTURE_QUERY} Lord of Franchise"
    standalone = f"{_RANK_FIXTURE_QUERY} Lord of Standalone"
    non_matcher = f"{_RANK_FIXTURE_QUERY} Wholly Different Title"
    await _make_anime_with_media_titled(
        db_session, mal_id=87101, anime_title=franchise,
        media_titles=[f"{franchise} S{i}" for i in range(6)],
    )
    await _make_anime_with_media_titled(
        db_session, mal_id=87102, anime_title=standalone, media_titles=[standalone],
    )
    await _make_anime_with_media_titled(
        db_session, mal_id=87103, anime_title=non_matcher, media_titles=[non_matcher],
    )
    return {franchise, standalone, non_matcher}


async def test_anime_ranking_is_invariant_to_media_count(
    client, user_auth_headers, uneven_media_count_set,
):
    """Anime-level title search groups over the JOINed media rows, so a
    6-media anime contributes 6 identical (anime, embedding) rows and a
    1-media anime contributes 1. The ordering distance is aggregated over that
    group, and the aggregate must be one that ignores group SIZE — MIN and AVG
    both do, SUM does not, and a SUM would rank the 6-media anime six times
    worse purely for being a franchise.

    Both matchers contain the "Lord of" substring, so both earn the same
    literal bonus.
    """
    franchise = f"{_RANK_FIXTURE_QUERY} Lord of Franchise"
    standalone = f"{_RANK_FIXTURE_QUERY} Lord of Standalone"
    non_matcher = f"{_RANK_FIXTURE_QUERY} Wholly Different Title"
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers,
        url=ANIME_SEARCH_URL,
        expect=uneven_media_count_set,
        query=f"{_RANK_FIXTURE_QUERY} Lord of",
    )
    # A size-scaling aggregate multiplies the franchise's distance by its six
    # media, sinking it below the non-matcher it outranks under every
    # size-invariant one. The standalone row is the control: at one media, SUM
    # and MIN agree on it, so it holds its place either way.
    assert ordered.index(franchise) < ordered.index(non_matcher), (
        f"The 6-media anime fell below a non-matching title — the ordering "
        f"aggregate is scaling with group size. Order: {ordered}"
    )
    assert ordered.index(standalone) < ordered.index(non_matcher), (
        f"The 1-media matcher fell below a non-matching title. Order: {ordered}"
    )


# ---------------------------------------------------------------------------
# Media view (same bonus applies via media_dao)
# ---------------------------------------------------------------------------

async def test_media_substring_match_outranks_non_match(
    client, user_auth_headers, lord_of_anime_set,
):
    """Media-view title search benefits from the same bonus."""
    matchers = {
        f"{_RANK_FIXTURE_QUERY} Lord of Mysteries",
        f"{_RANK_FIXTURE_QUERY} The Lord of the Rings",
    }
    non_matchers = {f"{_RANK_FIXTURE_QUERY} Overlord Show"}
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers,
        url=MEDIA_SEARCH_URL,
        expect=lord_of_anime_set,
        query=f"{_RANK_FIXTURE_QUERY} Lord of",
    )
    _assert_matchers_first(ordered, matchers, non_matchers)


# ---------------------------------------------------------------------------
# Unit test for the LIKE-escape helper — wildcards in user queries must
# match literally, not as SQL wildcards.
# ---------------------------------------------------------------------------

def test_escape_like_neutralises_wildcards():
    assert _escape_like("100%") == "100\\%"
    assert _escape_like("a_b") == "a\\_b"
    assert _escape_like("path\\name") == "path\\\\name"
    assert _escape_like("plain text") == "plain text"


def test_escape_like_handles_combined_wildcards():
    assert _escape_like("50%_off\\sale") == "50\\%\\_off\\\\sale"
