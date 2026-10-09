"""Search ranking — title and description — and sorting.

A title query keeps the rows where some title variant — the anime's own or any of
its media's — contains the query or fuzzy-matches it, substring hits first. No
title fixture carries a search embedding: a title search that still finds them
proves the title path joins none.

A description query ranks the media whose titles or description hold every query
word first, then semantic neighbours down to a cutoff set against the whole
catalogue, and retries with typo-tolerant words only when nothing matched. Its fixtures carry real
embeddings, and each test first asserts the distances it relies on, so a model or
catalogue change fails there instead of silently voiding the test.

A sort orders the rows a query matched, or the whole catalogue without one.

Every query goes through `_ordered_fixture_titles`, which scopes it to the fixture.
"""

import hashlib
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from sqlalchemy import select

from app.daos import search_filters
from app.daos.search_filters import _escape_like, description_cutoff
from app.models.anime import Anime
from app.models.media import (
    AIRING_STATUS_NOT_YET_AIRED,
    Media,
    RelationType,
    SeasonType,
)
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
    in_season: bool = True, **columns,
) -> Anime:
    """An anime and its media, stamped with the sentinel season unless `in_season` is
    off. `media` holds each media's `media_kwargs` overrides; by default one Main media
    carrying the anime's own title, so the fixture serves the media view unchanged.
    `columns` are the anime's own beyond its title."""
    anime = Anime(mal_id=mal_id, title=title, **columns)
    db_session.add(anime)
    await db_session.flush()
    season = _RANK_SEASON.columns if in_season else {}
    for i, overrides in enumerate(media or [{"title": title}]):
        db_session.add(Media(**media_kwargs(anime.id, mal_id * 10 + i, **season, **overrides)))
    await db_session.flush()
    return anime


async def _ordered_fixture_titles(
    client, headers, *, url: str, expect: set[str], in_season: bool = True, **params,
) -> list[str]:
    """The fixture's rows in response order, checked to be exactly `expect`.

    Every caller's assertion passes on an empty or truncated list, so the check
    that makes them mean anything belongs here rather than in each test that
    remembers to write it. `expect` is the subset of the fixture the query must
    match: equality catches a match lost and a non-match let through alike, and
    a season string that stopped parsing — which is logged and dropped, silently
    widening the response to the catalogue.

    `in_season=False` drops the season scope, for rows that carry no season; the
    caller's title query scopes them instead."""
    if in_season:
        params["anime_season"] = _RANK_SEASON.filter
    resp = await client.get(url, params=params, headers=headers)
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
async def test_title_search_sorts_the_rows_it_matched(client, user_auth_headers, lord_of_set, url):
    """By score the fuzzy hit (9.0) leads the substring hit (5.0), and the non-match
    stays out although it scores highest."""
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url,
        expect={_SUBSTRING_HIT, _FUZZY_HIT}, query="lord of", sort="score",
    )
    assert ordered == [_FUZZY_HIT, _SUBSTRING_HIT]


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
        "score": 6.0,
    }, True),
    _LITERAL_UNEMBEDDED: ({"description": "Izumi writes letters to a pen pal she has never met.", "score": 7.0}, False),
    _CLOSE: ({"description": "Izumo and Izuna.", "score": 8.0}, True),
    _HUB: ({"description": "", "score": 9.5}, True),
    _INFIX: ({"description": "Miho Nishizumi commands a tank crew at a girls' academy.", "score": 9.5}, True),
    _LEAP: ({
        "description": "A schoolgirl discovers she can leap back into the past and relive the same "
        "summer day again and again.",
    }, True),
    _FAR[0]: ({
        "description": "Rival chefs compete in a seaside restaurant's annual cooking contest, judged by the town mayor.",
        "score": 9.5,
    }, True),
    _FAR[1]: ({
        "description": "An accountant audits quarterly tax filings for a mid-sized logistics company.",
        "score": 9.5,
    }, True),
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


@_BOTH_VIEWS
async def test_description_search_sorts_the_rows_it_matched(
    client, user_auth_headers, db_session, url,
):
    """By score the three "izumi" hits come out in the reverse of their relevance
    order. The rows the query does not match all score higher, so a sort that
    reached past the match set would put them first."""
    await _describe(
        client, user_auth_headers, db_session, url,
        _CLOSE, _HUB, _INFIX, _LITERAL_UNEMBEDDED, _LITERAL, *_FAR,
    )
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect={_LITERAL, _LITERAL_UNEMBEDDED, _CLOSE},
        query="izumi", search_type="description", sort="score",
    )
    assert ordered == [_CLOSE, _LITERAL_UNEMBEDDED, _LITERAL]


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
# Sorting
# ---------------------------------------------------------------------------

async def _make_single(
    db_session, *, mal_id: int, title: str, score: float | None = None, scored_by: int = 0, **columns,
) -> None:
    """An anime and its one Main media, both carrying `title` and `columns`, so one
    expected order serves both grains."""
    await _make_anime(
        db_session, mal_id=mal_id, title=title,
        media=[{"title": title, "score": score, "scored_by": scored_by, **columns}], **columns,
    )


_FEW_VOTES, _BALANCED, _CROWD, _UNSCORED = "Sort Few Votes", "Sort Balanced", "Sort Crowd", "Sort Unscored"


@pytest.fixture
async def score_set(db_session):
    """Weighted scores: Balanced 40.0, Crowd 37.8, Few Votes 18.0, Unscored none.
    Inserted so that neither id order matches any sort."""
    rows = [
        (_CROWD, 6.0, 2_000_000),
        (_FEW_VOTES, 9.0, 100),
        (_UNSCORED, None, 0),
        (_BALANCED, 8.0, 100_000),
    ]
    for offset, (title, score, votes) in enumerate(rows):
        await _make_single(db_session, mal_id=87601 + offset, title=title, score=score, scored_by=votes)


@_BOTH_VIEWS
@pytest.mark.parametrize(("params", "expected"), [
    ({}, [_BALANCED, _CROWD, _FEW_VOTES, _UNSCORED]),
    ({"sort": "relevance"}, [_BALANCED, _CROWD, _FEW_VOTES, _UNSCORED]),
    ({"sort": "relevance", "sort_dir": "asc"}, [_BALANCED, _CROWD, _FEW_VOTES, _UNSCORED]),
    ({"sort": "top_rated"}, [_BALANCED, _CROWD, _FEW_VOTES, _UNSCORED]),
    ({"sort": "score"}, [_FEW_VOTES, _BALANCED, _CROWD, _UNSCORED]),
    ({"sort": "score", "sort_dir": "asc"}, [_CROWD, _BALANCED, _FEW_VOTES, _UNSCORED]),
    ({"sort": "popularity"}, [_CROWD, _BALANCED, _FEW_VOTES, _UNSCORED]),
], ids=["default", "relevance", "relevance_asc", "top_rated", "score", "score_asc", "popularity"])
async def test_score_sorts_disagree_and_keep_the_unscored_last(
    client, user_auth_headers, score_set, url, params, expected,
):
    """Without a query, relevance is top rated, and ignores a direction. An unscored
    row goes last in either direction."""
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect=set(expected), **params,
    )
    assert ordered == expected


@_BOTH_VIEWS
async def test_limit_cuts_the_sorted_list(client, user_auth_headers, score_set, url):
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect={_FEW_VOTES, _BALANCED}, sort="score", limit=2,
    )
    assert ordered == [_FEW_VOTES, _BALANCED]


@pytest.mark.parametrize("url", [ANIME_SEARCH_URL, MEDIA_SEARCH_URL, RATINGS_SEARCH_URL])
@pytest.mark.parametrize("limit", [0, 1001])
async def test_limit_out_of_range_is_rejected(client, user_auth_headers, url, limit):
    resp = await client.get(url, params={"limit": limit}, headers=user_auth_headers)
    assert resp.status_code == 422


# (title, name_eng, name_jap). Latin "Japanese" names, so the order never depends on
# how the collation ranks kana against Latin.
_NAMED = {
    "Delta": ("Alpha", "Kilo"),
    "Charlie": (None, "Hotel"),
    "Bravo": ("", None),
    "Echo": ("Able", ""),
}


@_BOTH_VIEWS
@pytest.mark.parametrize(("language", "params", "expected"), [
    ("english", {"sort": "title"}, ["Echo", "Delta", "Bravo", "Charlie"]),
    ("english", {"sort": "title", "sort_dir": "desc"}, ["Charlie", "Bravo", "Delta", "Echo"]),
    ("japanese", {"sort": "title"}, ["Bravo", "Echo", "Charlie", "Delta"]),
    ("romaji", {"sort": "title"}, ["Bravo", "Charlie", "Delta", "Echo"]),
], ids=["english", "english_desc", "japanese", "romaji"])
async def test_title_sort_follows_the_name_language(
    client, user_auth_headers, db_session, url, language, params, expected,
):
    """English sorts Able, Alpha, then the two rows whose English name is missing or
    empty under their romaji titles. Japanese falls back to romaji, not English: Echo's
    empty Japanese name puts it at "Echo", where English would put it first. Weighted
    scores rank Delta, Charlie, Bravo, Echo — none of the expected orders."""
    for offset, (title, (name_eng, name_jap)) in enumerate(_NAMED.items()):
        await _make_single(
            db_session, mal_id=87611 + offset, title=title, score=9.0 - offset, scored_by=1000,
            name_eng=name_eng, name_jap=name_jap,
        )
    resp = await client.put("/users/settings", json={"name_language": language}, headers=user_auth_headers)
    assert resp.status_code == 200, resp.text

    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect=set(_NAMED), **params,
    )
    assert ordered == expected


def _at(day: int) -> datetime:
    return datetime(2024, 1, day, tzinfo=UTC)


@_BOTH_VIEWS
@pytest.mark.parametrize(("params", "expected"), [
    ({"sort": "added"},
     ["Added 3", "Added 2", "Added 1", "Tied Better", "Tied Worse", "Tied D", "Tied C", "Tied B", "Tied A"]),
    ({"sort": "added", "sort_dir": "asc"},
     ["Tied A", "Tied B", "Tied C", "Tied D", "Tied Better", "Tied Worse", "Added 1", "Added 2", "Added 3"]),
], ids=["newest_first", "oldest_first"])
async def test_added_sort_breaks_ties_by_score_then_id(
    client, user_auth_headers, db_session, url, params, expected,
):
    """"Added 1-3" order by their timestamps against their weighted scores. "Tied
    Better" and "Tied Worse" share a timestamp and order by score, newest-first against
    their ids.
    "Tied A-D" share both, unscored, so only the id orders them, in the sort's
    direction: newest-first puts the last inserted first, against insertion order."""
    rows = [
        ("Added 1", _at(10), 9.0),
        ("Added 2", _at(11), 8.0),
        ("Added 3", _at(12), 7.0),
        ("Tied Better", _at(5), 8.0),
        ("Tied Worse", _at(5), 6.0),
        *((f"Tied {letter}", _at(1), None) for letter in "ABCD"),
    ]
    for offset, (title, created_at, score) in enumerate(rows):
        await _make_single(
            db_session, mal_id=87621 + offset, title=title, score=score, scored_by=1000, created_at=created_at,
        )
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect=set(expected), **params,
    )
    assert ordered == expected


_DAY_UUIDS = [UUID(int=n * 0x1000_0000_0000_0000_0000_0000_0001) for n in range(1, 7)]


def _daily_order(day: date) -> list[str]:
    """The fixture titles as the random sort should order them on `day`: md5 of the
    uuid and the date, descending."""
    return [
        f"Shuffled {uuid}"
        for uuid in sorted(_DAY_UUIDS, key=lambda u: hashlib.md5(f"{u}{day.isoformat()}".encode()).hexdigest(), reverse=True)
    ]


@_BOTH_VIEWS
async def test_random_sort_is_one_order_per_day(
    client, user_auth_headers, admin_auth_headers, db_session, monkeypatch, url,
):
    """Every viewer gets the same order on a day, and another day gets another."""
    for offset, uuid in enumerate(_DAY_UUIDS):
        await _make_single(db_session, mal_id=87641 + offset, title=f"Shuffled {uuid}", uuid=uuid)
    first, second = date(2026, 1, 1), date(2026, 1, 2)
    assert _daily_order(first) != _daily_order(second)

    for day in (first, second):
        monkeypatch.setattr(search_filters, "utc_today", lambda day=day: day)
        for headers in (user_auth_headers, admin_auth_headers):
            ordered = await _ordered_fixture_titles(
                client, headers, url=url, expect=set(_daily_order(day)), sort="random",
            )
            assert ordered == _daily_order(day)


def _season(name: SeasonType, year: int) -> dict:
    return {"anime_season_name": name, "anime_season_year": year}


_UNAIRED = {"airing_status": AIRING_STATUS_NOT_YET_AIRED}
_SIDE = {"relation_type": RelationType.SideStory}

# Anime → its media (title, columns), every title holding the token "Zqv" that scopes
# the query. Inserted in this order, which no sort matches.
_RELEASE_FIXTURE = {
    "Zqv Someday": [
        ("Zqv Someday", _season(SeasonType.Fall, 2018)),
        ("Zqv Someday 2", _UNAIRED),
    ],
    "Zqv Old": [("Zqv Old", _season(SeasonType.Spring, 2001))],
    "Zqv Undated": [("Zqv Undated", {})],
    "Zqv Sequel": [
        ("Zqv Sequel", _season(SeasonType.Fall, 2010)),
        ("Zqv Sequel 2", {**_season(SeasonType.Fall, 2030), **_UNAIRED}),
    ],
    "Zqv Newer": [
        ("Zqv Newer", _season(SeasonType.Fall, 2003)),
        ("Zqv Newer 2", _season(SeasonType.Winter, 2015)),
    ],
    "Zqv Announced": [
        ("Zqv Announced", _season(SeasonType.Summer, 2020)),
        ("Zqv Announced 3", {**_season(SeasonType.Spring, 2031), **_UNAIRED}),
        ("Zqv Announced 2", {**_season(SeasonType.Winter, 2030), **_UNAIRED}),
        ("Zqv Announced TBA", _UNAIRED),
    ],
    "Zqv Middle": [("Zqv Middle", _season(SeasonType.Summer, 2008))],
    "Zqv Recap": [
        ("Zqv Recap", _season(SeasonType.Spring, 2012)),
        ("Zqv Recap OVA", {**_season(SeasonType.Fall, 2025), **_SIDE}),
        ("Zqv Recap Movie", {**_season(SeasonType.Winter, 2029), **_UNAIRED, **_SIDE}),
        ("Zqv Recap Special", {**_UNAIRED, **_SIDE}),
    ],
}


@pytest.fixture
async def release_set(db_session):
    for offset, (title, media) in enumerate(_RELEASE_FIXTURE.items()):
        await _make_anime(
            db_session, mal_id=87651 + offset, title=title, in_season=False,
            media=[{"title": media_title, **columns} for media_title, columns in media],
        )


# Old Spring 2001 · Middle Summer 2008 · Recap its main story, Spring 2012 (its side
# stories aired Fall 2025, are announced for Winter 2029 and announced undated) · Newer
# its latest aired, Winter 2015 (not Fall 2003) · Announced its next announced, Winter
# 2030 (not Spring 2031, and not its undated one or its aired Summer 2020) · Sequel Fall
# 2030 · Someday TBA, though it aired Fall 2018 · Undated nothing, last either way.
_ANIME_RELEASE_ASC = [
    "Zqv Old", "Zqv Middle", "Zqv Recap", "Zqv Newer", "Zqv Announced", "Zqv Sequel", "Zqv Someday",
    "Zqv Undated",
]


# Each media at its own season, side stories included; the undated announcements tie at
# TBA and, all unscored, follow their ids.
_MEDIA_RELEASE_ASC = [
    "Zqv Old", "Zqv Newer", "Zqv Middle", "Zqv Sequel", "Zqv Recap", "Zqv Newer 2", "Zqv Someday",
    "Zqv Announced", "Zqv Recap OVA", "Zqv Recap Movie", "Zqv Announced 2", "Zqv Sequel 2",
    "Zqv Announced 3", "Zqv Someday 2", "Zqv Announced TBA", "Zqv Recap Special", "Zqv Undated",
]


@pytest.mark.parametrize(("url", "ascending"), [
    (ANIME_SEARCH_URL, _ANIME_RELEASE_ASC),
    (MEDIA_SEARCH_URL, _MEDIA_RELEASE_ASC),
], ids=["anime", "media"])
@pytest.mark.parametrize("params", [
    {"sort": "release"},
    {"sort": "release", "sort_dir": "desc"},
], ids=["asc", "desc"])
async def test_release_sort_is_one_timeline(client, user_auth_headers, release_set, url, ascending, params):
    """Ascending by default; descending reverses every dated and TBA row, and the
    row without a season stays last."""
    expected = [*reversed(ascending[:-1]), ascending[-1]] if "sort_dir" in params else ascending
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect=set(expected), in_season=False, query="zqv", **params,
    )
    assert ordered == expected


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
