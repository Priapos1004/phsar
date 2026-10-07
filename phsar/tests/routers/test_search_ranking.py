"""Title search — a fuzzy substring filter over every title variant.

A title query keeps the rows where some title variant — the anime's own or any of
its media's — contains the query or fuzzy-matches it, substring hits first. No
fixture here carries a search embedding: a title search that still finds them
proves the title path joins none.

Fixture rows are scoped to a `SentinelSeason`; every query goes through
`_ordered_fixture_titles`.
"""

import pytest

from app.daos.search_filters import _escape_like
from app.models.anime import Anime
from app.models.media import Media, RelationType
from tests._helpers import SentinelSeason, media_kwargs

ANIME_SEARCH_URL = "/search/anime"
MEDIA_SEARCH_URL = "/search/media"

_RANK_SEASON = SentinelSeason(1902)

_BOTH_VIEWS = pytest.mark.parametrize("url", [ANIME_SEARCH_URL, MEDIA_SEARCH_URL], ids=["anime", "media"])


async def _make_anime(
    db_session, *, mal_id: int, title: str, media: list[dict] | None = None,
) -> Anime:
    """An anime and its media, stamped with the sentinel season. `media` holds
    each media's `media_kwargs` overrides; by default one Main media carrying the
    anime's own title, so the fixture serves the media view unchanged."""
    anime = Anime(mal_id=mal_id, title=title)
    db_session.add(anime)
    await db_session.flush()
    for i, overrides in enumerate(media or [{"title": title}]):
        db_session.add(Media(**media_kwargs(
            anime.id, mal_id * 10 + i, **_RANK_SEASON.columns, **overrides,
        )))
    await db_session.flush()
    return anime


async def _ordered_fixture_titles(
    client, headers, *, url: str, expect: set[str], **params,
) -> list[str]:
    """The fixture's rows in response order, checked to be exactly `expect`.

    Every caller's assertion passes on an empty or truncated list, so the check
    that makes them mean anything belongs here rather than in each test that
    remembers to write it. `expect` is the subset of the fixture the query must
    match: equality catches a match lost and a non-match let through alike, and
    a season string that stopped parsing — which is logged and dropped, silently
    widening the response to the catalogue."""
    resp = await client.get(
        url,
        params={**params, "anime_season": _RANK_SEASON.filter},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    titles = [a["title"] for a in resp.json()]
    assert set(titles) == expect, (
        f"response is not the expected match set: missing {sorted(expect - set(titles))}, "
        f"unexpected {sorted(set(titles) - expect)}"
    )
    return titles


# ---------------------------------------------------------------------------
# Substring hits first, fuzzy hits after, non-matches out
# ---------------------------------------------------------------------------

_SUBSTRING_HIT = "Overlord of Darkness"
_FUZZY_HIT = "Lord, of Ashes"
_NON_MATCH = "Unrelated Anime"


@pytest.fixture
async def lord_of_set(db_session):
    """The anime against the query "lord of":

    - "Overlord of Darkness" contains it ("over·lord of"), the substring tier;
    - "Lord, of Ashes" matches only fuzzily — the comma breaks the substring, while
      every trigram of the query is still present (word_similarity 1.0);
    - "Unrelated Anime" matches neither.

    Everything else points the other way: by weighted score the fuzzy hit leads the
    substring hit, and the non-match would lead both."""
    rows = [
        (_SUBSTRING_HIT, 5.0, 10),
        (_FUZZY_HIT, 9.0, 100_000),
        (_NON_MATCH, 9.5, 1_000_000),
    ]
    for offset, (title, score, votes) in enumerate(rows):
        await _make_anime(
            db_session, mal_id=87001 + offset, title=title,
            media=[{"title": title, "score": score, "scored_by": votes}],
        )


@_BOTH_VIEWS
async def test_title_search_keeps_matches_substring_hits_first(
    client, user_auth_headers, lord_of_set, url,
):
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url,
        expect={_SUBSTRING_HIT, _FUZZY_HIT}, query="lord of",
    )
    assert ordered == [_SUBSTRING_HIT, _FUZZY_HIT]


@_BOTH_VIEWS
@pytest.mark.parametrize("query", ["LORD OF", "  lord of  "], ids=["upper", "padded"])
async def test_title_search_ignores_case_and_padding(
    client, user_auth_headers, lord_of_set, url, query,
):
    """Both variants would demote the substring hit if they reached the SQL as
    typed: a case-sensitive match misses "LORD OF", and the padded pattern
    `%  lord of  %` is contained in no title. The fuzzy tier ignores both, so the
    fuzzy hit would then lead."""
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url,
        expect={_SUBSTRING_HIT, _FUZZY_HIT}, query=query,
    )
    assert ordered == [_SUBSTRING_HIT, _FUZZY_HIT]


# ---------------------------------------------------------------------------
# The looser threshold runs only when the strict one matches nothing
# ---------------------------------------------------------------------------

_MID_WORD_TYPO_HIT = "Frieren Fixture"


@_BOTH_VIEWS
async def test_title_search_falls_back_when_nothing_clears_the_threshold(
    client, user_auth_headers, db_session, url,
):
    """"friren" drops a letter mid-word, so the stretch of "frieren" it matches
    shares 5 of 10 trigrams with it — 0.5, under the first threshold. Nothing
    matches at that one, so the search retries at the fallback and finds it."""
    await _make_anime(db_session, mal_id=87301, title=_MID_WORD_TYPO_HIT)
    await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect={_MID_WORD_TYPO_HIT}, query="friren",
    )


@_BOTH_VIEWS
async def test_title_search_skips_the_fallback_when_something_matches(
    client, user_auth_headers, db_session, url,
):
    await _make_anime(db_session, mal_id=87301, title=_MID_WORD_TYPO_HIT)
    await _make_anime(db_session, mal_id=87302, title="Friren Academy")
    await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect={"Friren Academy"}, query="friren",
    )


# ---------------------------------------------------------------------------
# A media's titles reach its anime, without rescoping the anime's aggregates
# ---------------------------------------------------------------------------

async def test_media_title_reaches_its_anime(client, user_auth_headers, db_session):
    """A side story's own title finds its anime, and the anime still scores over
    its main story.

    The match is decided in HAVING over all the anime's media. Deciding it in
    WHERE would narrow the grouped rows to the side story, whose relation weight is
    0, leaving avg_score NULL — so `score_min` would drop the anime."""
    await _make_anime(db_session, mal_id=87101, title="Hagane Alchemist", media=[
        {"title": "Hagane Alchemist", "score": 8.0, "scored_by": 1000},
        {
            "title": "Fullmetal Alchemist: Brotherhood",
            "relation_type": RelationType.SideStory, "score": 6.0, "scored_by": 1000,
        },
    ])
    await _ordered_fixture_titles(
        client, user_auth_headers, url=ANIME_SEARCH_URL,
        expect={"Hagane Alchemist"}, query="brotherhood", score_min=7,
    )


async def test_synonym_reaches_its_anime(client, user_auth_headers, db_session):
    """Synonyms (`other_names`, a JSONB list) are a title variant too. Placed on a
    side story, so the same WHERE-instead-of-HAVING regression fails here as well."""
    await _make_anime(db_session, mal_id=87201, title="Shingeki Fixture", media=[
        {"title": "Shingeki Fixture", "score": 8.0, "scored_by": 1000},
        {
            "title": "Shingeki Fixture OVA", "other_names": ["Attack on Titan OVA"],
            "relation_type": RelationType.SideStory,
        },
    ])
    await _ordered_fixture_titles(
        client, user_auth_headers, url=ANIME_SEARCH_URL,
        expect={"Shingeki Fixture"}, query="attack on titan", score_min=7,
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
