"""Search ranking — title and description.

A title query keeps the rows where some title variant — the anime's own or any of
its media's — contains the query or fuzzy-matches it, substring hits first. No
title fixture carries a search embedding: a title search that still finds them
proves the title path joins none.

A description query ranks the media whose titles or description hold every query
word first, then semantic neighbours down to a cutoff set against the whole
catalogue, and retries with typo-tolerant words only when nothing matched. Its fixtures carry real
embeddings, and each test first asserts the distances it relies on, so a model or
catalogue change fails there instead of silently voiding the test.

Fixture rows are scoped to a `SentinelSeason`; every query goes through
`_ordered_fixture_titles`.
"""

import pytest
from sqlalchemy import select

from app.daos.search_filters import _escape_like, description_cutoff
from app.models.anime import Anime
from app.models.media import Media, RelationType
from app.models.media_search import MediaSearch
from app.services.media_search_service import media_title_texts
from app.services.vector_embedding_service import (
    create_media_embedding,
    generate_query_embedding,
)
from tests._helpers import SentinelSeason, media_kwargs

ANIME_SEARCH_URL = "/search/anime"
MEDIA_SEARCH_URL = "/search/media"
RATINGS_SEARCH_URL = "/search/ratings"

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
# Description search: literal hits first, semantic ones down to the cutoff,
# a typo-tolerant retry only when nothing matched
# ---------------------------------------------------------------------------

_DESCRIPTION_VIEWS = pytest.mark.parametrize(
    "url", [ANIME_SEARCH_URL, MEDIA_SEARCH_URL, RATINGS_SEARCH_URL], ids=["anime", "media", "ratings"],
)

_LITERAL = "Fixture Garden"
_LITERAL_UNEMBEDDED = "Fixture Letters"
_CLOSE = "Izumo"
_HUB = "Izumo Shrine"
_INFIX = "Fixture Tankery"
_LEAP = "Fixture Summer"
_FAR = ("Fixture Kitchen", "Fixture Ledger")
_TITLE_HIT = "Fixture Court"

# title → (its media's column overrides, whether it gets an embedding); one
# single-media anime each.
_DESCRIBED = {
    _LITERAL: ({
        "description": "Izumi tends a quiet garden behind the old shrine and trades seeds with the "
        "neighbours over the fence every spring.",
    }, True),
    _LITERAL_UNEMBEDDED: ({"description": "Izumi writes letters to a pen pal she has never met."}, False),
    _CLOSE: ({"description": "Izumo and Izuna."}, True),
    _HUB: ({"description": ""}, True),
    _INFIX: ({"description": "Miho Nishizumi commands a tank crew at a girls' academy."}, True),
    _LEAP: ({
        "description": "A schoolgirl discovers she can leap back into the past and relive the same "
        "summer day again and again.",
    }, True),
    _FAR[0]: ({"description": "Rival chefs compete in a seaside restaurant's annual cooking contest, judged by the town mayor."}, True),
    _FAR[1]: ({"description": "An accountant audits quarterly tax filings for a mid-sized logistics company."}, True),
    _TITLE_HIT: ({
        "name_eng": "Though I Am an Inept Villainess",
        "description": "Two consorts-in-training swap bodies on the night of a comet.",
    }, False),
}


async def _describe(client, headers, db_session, url: str, *titles: str) -> None:
    """One single-media anime per title, in the order given (so in id order), its
    embedding written by the save path's own encoder. On the ratings view the caller
    rates every one, since that search only sees rated media."""
    for title in titles:
        overrides, embedded = _DESCRIBED[title]
        anime = await _make_anime(
            db_session, mal_id=87401 + list(_DESCRIBED).index(title), title=title,
            media=[{"title": title, **overrides}],
        )
        media = (await db_session.execute(select(Media).where(Media.anime_id == anime.id))).scalar_one()
        if embedded:
            await create_media_embedding(db_session, media.id, media_title_texts(media), media.description)
        if url == RATINGS_SEARCH_URL:
            resp = await client.put(f"/ratings/media/{media.uuid}", json={"rating": 7.0}, headers=headers)
            assert resp.status_code == 200, resp.text


async def _distances_and_cutoff(db_session, query: str) -> tuple[dict[str, float], float]:
    """Each embedded fixture media's raw description distance to `query` — the empty
    description included, which the search itself never measures — and the cutoff
    the search applies."""
    query_embedding = await generate_query_embedding(query)
    rows = await db_session.execute(
        select(Media.title, MediaSearch.description_embedding.cosine_distance(query_embedding))
        .join(MediaSearch, MediaSearch.media_id == Media.id)
        .where(Media.anime_season_year == _RANK_SEASON.year)
    )
    cutoff = (await db_session.execute(select(description_cutoff(query_embedding)))).scalar_one()
    return dict(rows.tuples().all()), cutoff


@_DESCRIPTION_VIEWS
async def test_description_name_query_ranks_literal_hits_first(
    client, user_auth_headers, db_session, url,
):
    """For "izumi" the vector prefers "Izumo", which was also created first, yet the
    two descriptions naming Izumi lead: the embedded one, then the one without an
    embedding, which only an outer join keeps. "Izumo" follows as a semantic hit under
    the cutoff.

    Two rows stay out that a looser rule would let in. "Izumo Shrine" has an empty
    description, and its title-only vector sits nearer than "Izumo"'s. "Fixture
    Tankery" names Nishizumi, which contains the query, but no word of it starts with
    it."""
    await _describe(
        client, user_auth_headers, db_session, url,
        _CLOSE, _HUB, _INFIX, _LITERAL_UNEMBEDDED, _LITERAL, *_FAR,
    )
    dist, cutoff = await _distances_and_cutoff(db_session, "izumi")
    assert dist[_CLOSE] < dist[_LITERAL]
    assert max(dist[_CLOSE], dist[_HUB]) <= cutoff < min(dist[_INFIX], *(dist[t] for t in _FAR))

    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect={_LITERAL, _LITERAL_UNEMBEDDED, _CLOSE},
        query="izumi", search_type="description",
    )
    assert ordered == [_LITERAL, _LITERAL_UNEMBEDDED, _CLOSE]


@_DESCRIPTION_VIEWS
async def test_description_search_keeps_close_rows_and_cuts_far_ones(
    client, user_auth_headers, db_session, url,
):
    """No description holds every word of the query ("Fixture Tankery" has "girls'"
    and nothing else), so every row here is semantic: "Fixture Summer" sits under the
    cutoff and stays, the rest sit above it and go."""
    await _describe(client, user_auth_headers, db_session, url, _LEAP, _INFIX, *_FAR)
    query = "a girl who travels back in time"
    dist, cutoff = await _distances_and_cutoff(db_session, query)
    assert dist[_LEAP] <= cutoff < min(dist[_INFIX], *(dist[t] for t in _FAR))

    await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect={_LEAP}, query=query, search_type="description",
    )


@_DESCRIPTION_VIEWS
async def test_description_search_retries_typos_only_when_nothing_matched(
    client, user_auth_headers, db_session, url,
):
    """"izumy" starts no word and sits beyond the cutoff from every vector here, so the
    strict pass is empty and the typo-tolerant retry finds the two descriptions naming
    Izumi. Nishizumi stays under its threshold."""
    await _describe(
        client, user_auth_headers, db_session, url, _INFIX, _LITERAL_UNEMBEDDED, _LITERAL, *_FAR,
    )
    dist, cutoff = await _distances_and_cutoff(db_session, "izumy")
    assert min(dist.values()) > cutoff

    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect={_LITERAL, _LITERAL_UNEMBEDDED},
        query="izumy", search_type="description",
    )
    assert ordered == [_LITERAL, _LITERAL_UNEMBEDDED]


@_DESCRIPTION_VIEWS
async def test_description_literal_tier_reads_titles_too(
    client, user_auth_headers, db_session, url,
):
    """"villainess" appears only in the English title, never in the synopsis — the
    shape of "Though I Am an Inept Villainess". Without an embedding the row
    can only surface through the literal tier, so a tier reading the description
    alone returns nothing."""
    await _describe(client, user_auth_headers, db_session, url, _TITLE_HIT, *_FAR)
    await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect={_TITLE_HIT}, query="villainess", search_type="description",
    )


async def test_description_literal_hit_on_a_side_story_reaches_its_anime(
    client, user_auth_headers, db_session,
):
    """Only the side story's description names Izumi. The match is decided in HAVING
    over all the anime's media; deciding it in WHERE would narrow the grouped rows to
    the side story, whose relation weight is 0, leaving avg_score NULL — so
    `score_min` would drop the anime."""
    await _make_anime(db_session, mal_id=87501, title="Hagane Garden", media=[
        {
            "title": "Hagane Garden", "description": "A gardener restores an abandoned greenhouse.",
            "score": 8.0, "scored_by": 1000,
        },
        {
            "title": "Hagane Garden Special", "description": "Izumi visits the greenhouse.",
            "relation_type": RelationType.SideStory, "score": 6.0, "scored_by": 1000,
        },
    ])
    await _ordered_fixture_titles(
        client, user_auth_headers, url=ANIME_SEARCH_URL, expect={"Hagane Garden"},
        query="izumi", search_type="description", score_min=7,
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
