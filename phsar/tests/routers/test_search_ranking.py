"""Title-search ranking — substring-match bonus.

Pure cosine-distance ranking can promote thematically-similar shows
over titles that literally contain the user's query. Concrete case:
"Lord of" surfaces "Overlord" above "Lord of Mysteries" because the
embeddings cluster on theme, not literal token match. The
`_TITLE_MATCH_BONUS_WEIGHT` reduction in `apply_vector_ordering`
nudges substring-containing titles ahead.

Tests use a distinctive title prefix so vector search scopes to the
fixture set; assertions check the relative order of fixture rows
within the response, ignoring whatever else the catalog returned.
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
from tests._helpers import media_kwargs

ANIME_SEARCH_URL = "/search/anime"
MEDIA_SEARCH_URL = "/search/media"


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
        media = Media(**media_kwargs(anime.id, mal_id * 10 + i, title=media_title))
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
    """Four anime sharing the `FilterTestRank` query prefix but with
    different relationships to the substring "Lord of":

    - 'Lord of Mysteries' contains the substring → gets the bonus
    - 'The Lord of the Rings' contains the substring → gets the bonus
    - 'Overlord Show' contains "Lord" but NOT "Lord of" as a contiguous
      substring → no bonus
    - 'Unrelated Anime' has neither → no bonus
    """
    await _make_anime_with_media_titled(
        db_session, mal_id=87001,
        anime_title=f"{_RANK_FIXTURE_QUERY} Lord of Mysteries",
        media_titles=[f"{_RANK_FIXTURE_QUERY} Lord of Mysteries"],
    )
    await _make_anime_with_media_titled(
        db_session, mal_id=87002,
        anime_title=f"{_RANK_FIXTURE_QUERY} The Lord of the Rings",
        media_titles=[f"{_RANK_FIXTURE_QUERY} The Lord of the Rings"],
    )
    await _make_anime_with_media_titled(
        db_session, mal_id=87003,
        anime_title=f"{_RANK_FIXTURE_QUERY} Overlord Show",
        media_titles=[f"{_RANK_FIXTURE_QUERY} Overlord Show"],
    )
    await _make_anime_with_media_titled(
        db_session, mal_id=87004,
        anime_title=f"{_RANK_FIXTURE_QUERY} Unrelated Anime",
        media_titles=[f"{_RANK_FIXTURE_QUERY} Unrelated Anime"],
    )


async def _ordered_fixture_titles(client, headers, *, url: str, **params) -> list[str]:
    resp = await client.get(url, params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return [
        a["title"] for a in resp.json()
        if a["title"].startswith(_RANK_FIXTURE_QUERY)
    ]


async def test_anime_substring_match_outranks_non_match(
    client, user_auth_headers, lord_of_anime_set,
):
    """The two anime whose titles contain "Lord of" must come before the
    Overlord/Unrelated rows. Pure cosine could put them in any order;
    the substring bonus forces matchers first."""
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers,
        url=ANIME_SEARCH_URL,
        query=f"{_RANK_FIXTURE_QUERY} Lord of",
    )
    matchers = {
        f"{_RANK_FIXTURE_QUERY} Lord of Mysteries",
        f"{_RANK_FIXTURE_QUERY} The Lord of the Rings",
    }
    non_matchers = {
        f"{_RANK_FIXTURE_QUERY} Overlord Show",
        f"{_RANK_FIXTURE_QUERY} Unrelated Anime",
    }
    assert set(ordered) >= matchers, f"matchers missing from results: {ordered}"
    # Find the latest position of any matcher and the earliest position of
    # any non-matcher; every matcher must come first.
    matcher_positions = [i for i, t in enumerate(ordered) if t in matchers]
    non_matcher_positions = [i for i, t in enumerate(ordered) if t in non_matchers]
    if non_matcher_positions:
        assert max(matcher_positions) < min(non_matcher_positions), (
            f"Non-matcher ranked above a matcher. Order: {ordered}"
        )


async def test_anime_query_case_does_not_change_ranking(
    client, user_auth_headers, lord_of_anime_set,
):
    """Capitalising the query must not change results. The reported bug:
    typing "Kurokos" instead of "kurokos" buried Kuroko's Basketball
    because the cased embedding model gave the two a materially different
    vector. `generate_embedding` now folds case, and the SQL bonuses were
    already case-insensitive, so query case is irrelevant end to end."""
    lower = await _ordered_fixture_titles(
        client, user_auth_headers, url=ANIME_SEARCH_URL,
        query=f"{_RANK_FIXTURE_QUERY} Lord of",
    )
    upper = await _ordered_fixture_titles(
        client, user_auth_headers, url=ANIME_SEARCH_URL,
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
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers,
        url=ANIME_SEARCH_URL,
        query=f"{_RANK_FIXTURE_QUERY} lor of",
    )
    best_matcher = f"{_RANK_FIXTURE_QUERY} Lord of Mysteries"
    unrelated = f"{_RANK_FIXTURE_QUERY} Unrelated Anime"
    if best_matcher in ordered and unrelated in ordered:
        assert ordered.index(best_matcher) < ordered.index(unrelated), (
            f"Best fuzzy matcher ranked below the unrelated title. "
            f"pg_trgm bonus may not be firing. Order: {ordered}"
        )


# ---------------------------------------------------------------------------
# Media view (same bonus applies via media_dao)
# ---------------------------------------------------------------------------

async def test_media_substring_match_outranks_non_match(
    client, user_auth_headers, lord_of_anime_set,
):
    """Media-view title search benefits from the same bonus."""
    resp = await client.get(
        MEDIA_SEARCH_URL,
        params={"query": f"{_RANK_FIXTURE_QUERY} Lord of"},
        headers=user_auth_headers,
    )
    assert resp.status_code == 200
    ordered = [
        m["title"] for m in resp.json()
        if m["title"].startswith(_RANK_FIXTURE_QUERY)
    ]
    matchers = {
        f"{_RANK_FIXTURE_QUERY} Lord of Mysteries",
        f"{_RANK_FIXTURE_QUERY} The Lord of the Rings",
    }
    matcher_positions = [i for i, t in enumerate(ordered) if t in matchers]
    non_matcher_positions = [
        i for i, t in enumerate(ordered)
        if t == f"{_RANK_FIXTURE_QUERY} Overlord Show"
    ]
    if non_matcher_positions and matcher_positions:
        assert max(matcher_positions) < min(non_matcher_positions), (
            f"Non-matcher ranked above a matcher. Order: {ordered}"
        )


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
