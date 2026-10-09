"""Search ranking — title, description and notes — and sorting.

A title query keeps the rows where some title variant — the anime's own or any of
its media's — contains the query or fuzzy-matches it, substring hits first. No
title fixture carries a search embedding: a title search that still finds them
proves the title path joins none.

A description query ranks the media whose titles or description hold every query
word first, then semantic neighbours down to a cutoff set against the whole
catalogue, and retries with typo-tolerant words only when nothing matched. Its fixtures carry real
embeddings, and each test first asserts the distances it relies on, so a model or
catalogue change fails there instead of silently voiding the test.

A notes query runs the description tiers over the caller's own notes, and the anime
grain matches on its nearest note.

A sort orders the rows a query matched, or the whole catalogue without one.

The caller's own ratings and watchlist filter and sort it too. Their fixtures rate and
list through the real endpoints, as the caller and, where another user's rating must
not count, as the admin.

Every query goes through `_ordered_fixture_titles`, which scopes it to the fixture.
"""

import hashlib
import re
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select

from app.daos import search_filters
from app.daos.anime_dao import AnimeDAO
from app.daos.media_dao import MediaDAO
from app.daos.rating_dao import _note_distance, note_cutoff
from app.daos.search_filters import (
    ASCENDING_SORTS,
    _escape_like,
    description_cutoff,
    weighted_mean_score_expr,
    weighted_mean_votes_expr,
    weighted_score_expr,
)
from app.models.anime import Anime
from app.models.genre import Genre, GenreType
from app.models.media import (
    AIRING_STATUS_CURRENTLY_AIRING,
    AIRING_STATUS_NOT_YET_AIRED,
    Media,
    MediaType,
    RelationType,
    SeasonType,
)
from app.models.media_genre import MediaGenre
from app.models.media_search import MediaSearch
from app.models.media_studio import MediaStudio
from app.models.rating_search import RatingSearch
from app.models.ratings import Ratings
from app.models.studio import Studio
from app.services import anime_search_service, media_search_service
from app.services.media_search_service import media_title_texts
from app.services.vector_embedding_service import (
    create_media_embedding,
    generate_query_embedding,
)
from tests._helpers import SentinelSeason, list_media, media_kwargs, rate_media

ANIME_SEARCH_URL = "/search/anime"
MEDIA_SEARCH_URL = "/search/media"

_RANK_SEASON = SentinelSeason(1902)

_BOTH_VIEWS = pytest.mark.parametrize("url", [ANIME_SEARCH_URL, MEDIA_SEARCH_URL], ids=["anime", "media"])


async def _make_anime(
    db_session, *, mal_id: int, title: str, media: list[dict] | None = None,
    in_season: bool = True, **columns,
) -> Anime:
    """An anime and its media, stamped with the sentinel season unless `in_season` is
    off or the media's overrides carry a season of their own. `media` holds each media's
    `media_kwargs` overrides; by default one Main media carrying the anime's own title,
    so the fixture serves the media view unchanged. `columns` are the anime's own beyond
    its title."""
    anime = Anime(mal_id=mal_id, title=title, **columns)
    db_session.add(anime)
    await db_session.flush()
    season = _RANK_SEASON.columns if in_season else {}
    for i, overrides in enumerate(media or [{"title": title}]):
        db_session.add(Media(**media_kwargs(anime.id, mal_id * 10 + i, **{**season, **overrides})))
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


@_BOTH_VIEWS
async def test_query_cap_counts_the_stripped_query(client, user_auth_headers, url):
    """A query over the cap only by its padding is accepted: the cap (see
    `test_out_of_range_is_rejected`) measures what reaches the SQL."""
    resp = await client.get(url, params={"query": f"  {'x' * 200}  "}, headers=user_auth_headers)
    assert resp.status_code == 200, resp.text


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


async def _describe(db_session, *titles: str) -> None:
    """One single-media anime per title, in the order given (so in id order), its
    embedding written by the save path's own encoder."""
    for title in titles:
        overrides, embedded = _DESCRIBED[title]
        anime = await _make_anime(
            db_session, mal_id=87401 + list(_DESCRIBED).index(title), title=title,
            media=[{"title": title, **overrides}],
        )
        media = (await db_session.execute(select(Media).where(Media.anime_id == anime.id))).scalar_one()
        if embedded:
            await create_media_embedding(db_session, media.id, media_title_texts(media), media.description)


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


@_BOTH_VIEWS
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
        db_session,
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
        db_session,
        _CLOSE, _HUB, _INFIX, _LITERAL_UNEMBEDDED, _LITERAL, *_FAR,
    )
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect={_LITERAL, _LITERAL_UNEMBEDDED, _CLOSE},
        query="izumi", search_type="description", sort="score",
    )
    assert ordered == [_CLOSE, _LITERAL_UNEMBEDDED, _LITERAL]


@_BOTH_VIEWS
async def test_description_search_keeps_close_rows_and_cuts_far_ones(
    client, user_auth_headers, db_session, url,
):
    """No description holds every word of the query ("Fixture Tankery" has "girls'"
    and nothing else), so every row here is semantic: "Fixture Summer" sits under the
    cutoff and stays, the rest sit above it and go."""
    await _describe(db_session, _LEAP, _INFIX, *_FAR)
    query = "a girl who travels back in time"
    dist, cutoff = await _distances_and_cutoff(db_session, query)
    assert dist[_LEAP] <= cutoff < min(dist[_INFIX], *(dist[t] for t in _FAR))

    await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect={_LEAP}, query=query, search_type="description",
    )


@_BOTH_VIEWS
async def test_description_search_retries_typos_only_when_nothing_matched(
    client, user_auth_headers, db_session, url,
):
    """"izumy" starts no word and sits beyond the cutoff from every vector here, so the
    strict pass is empty and the typo-tolerant retry finds the two descriptions naming
    Izumi. Nishizumi stays under its threshold."""
    await _describe(
        db_session, _INFIX, _LITERAL_UNEMBEDDED, _LITERAL, *_FAR,
    )
    dist, cutoff = await _distances_and_cutoff(db_session, "izumy")
    assert min(dist.values()) > cutoff

    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect={_LITERAL, _LITERAL_UNEMBEDDED},
        query="izumy", search_type="description",
    )
    assert ordered == [_LITERAL, _LITERAL_UNEMBEDDED]


@_BOTH_VIEWS
async def test_description_literal_tier_reads_titles_too(
    client, user_auth_headers, db_session, url,
):
    """"villainess" appears only in the English title, never in the synopsis — the
    shape of "Though I Am an Inept Villainess". Without an embedding the row
    can only surface through the literal tier, so a tier reading the description
    alone returns nothing."""
    await _describe(db_session, _TITLE_HIT, *_FAR)
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
# Notes search: the description tiers over the caller's own notes, the anime grain
# on its nearest note, the matched note quoted on the card
# ---------------------------------------------------------------------------

_NOTE_LITERAL = "Izumi's speech at the end got me."
_NOTE_NEAR = "Izumo and Izuna."
_NOTE_QUOTED = "Izumi was the best part, her speech at the end got me."

# Anime → its media (title, the caller's note); the admin notes "Nt Theirs" instead.
_NOTED = {
    "Nt Literal": [("Nt Literal", _NOTE_LITERAL)],
    "Nt Near": [("Nt Near", _NOTE_NEAR)],
    "Nt Far": [("Nt Far", "The tax audit subplot dragged on forever.")],
    "Nt Far Too": [("Nt Far Too", "Mecha battles were loud and the pilots kept screaming.")],
    "Nt Pair": [("Nt Pair", _NOTE_NEAR), ("Nt Pair 2", "The villain's backstory reveal in the finale felt rushed.")],
    "Nt Quote": [("Nt Quote", _NOTE_NEAR), ("Nt Quote 2", _NOTE_QUOTED)],
    "Nt Theirs": [("Nt Theirs", None)],
}


@pytest.fixture
async def noted_set(db_session, client, user_auth_headers, admin_auth_headers):
    await _make_franchises(
        db_session, {anime: [(title, {}) for title, _ in media] for anime, media in _NOTED.items()}, mal_id=87861,
    )
    notes = {title: note for media in _NOTED.values() for title, note in media}
    uuids = await _media_uuids(db_session, notes)
    for title, note in notes.items():
        if note:
            await rate_media(client, user_auth_headers, uuids[title], _DONE, note=note)
    await rate_media(client, admin_auth_headers, uuids["Nt Theirs"], _DONE, note="Izumi again.")


async def _note_distances_and_cutoff(db_session, query: str) -> tuple[dict[str, float], float]:
    """Each of the caller's fixture notes' distance to `query`, by media title, and the
    cutoff the search applies."""
    query_embedding = await generate_query_embedding(query)
    caller = (await db_session.execute(
        select(Ratings.user_id).join(Media, Media.id == Ratings.media_id).where(Media.title == "Nt Near")
    )).scalar_one()
    rows = await db_session.execute(
        select(Media.title, _note_distance(query_embedding))
        .join(Ratings, Ratings.media_id == Media.id)
        .join(RatingSearch, RatingSearch.rating_id == Ratings.id)
        .where(Ratings.user_id == caller, Media.anime_season_year == _RANK_SEASON.year)
    )
    cutoff = (await db_session.execute(select(note_cutoff(query_embedding, caller)))).scalar_one()
    return dict(rows.tuples().all()), cutoff


@pytest.mark.parametrize(("url", "literal", "semantic"), [
    (ANIME_SEARCH_URL, {"Nt Literal", "Nt Quote"}, {"Nt Near", "Nt Pair"}),
    (MEDIA_SEARCH_URL, {"Nt Literal", "Nt Quote 2"}, {"Nt Near", "Nt Pair", "Nt Quote"}),
], ids=["anime", "media"])
async def test_notes_search_ranks_literal_hits_first(
    client, user_auth_headers, db_session, noted_set, url, literal, semantic,
):
    """For "izumi" the vector prefers "Izumo and Izuna.", yet the notes naming Izumi
    lead; the near notes follow under the cutoff and the far ones go. The admin's note
    names Izumi too, but it is not the caller's."""
    dist, cutoff = await _note_distances_and_cutoff(db_session, "izumi")
    assert dist["Nt Near"] < dist["Nt Literal"]
    assert dist["Nt Near"] <= cutoff < min(dist["Nt Far"], dist["Nt Far Too"], dist["Nt Pair 2"])

    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect=literal | semantic, query="izumi", search_type="rating_notes",
    )
    assert set(ordered[:len(literal)]) == literal


async def test_notes_anime_grain_matches_on_its_nearest_note(client, user_auth_headers, db_session, noted_set):
    """"Nt Pair" has one near note and one far one: it matches on the near note, as its
    media does at the media grain, where averaging the two would cut it."""
    dist, cutoff = await _note_distances_and_cutoff(db_session, "izumi")
    assert dist["Nt Pair"] <= cutoff < (dist["Nt Pair"] + dist["Nt Pair 2"]) / 2

    resp = await client.get(
        ANIME_SEARCH_URL, params={"query": "izumi", "search_type": "rating_notes", "anime_season": _RANK_SEASON.filter},
        headers=user_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert "Nt Pair" in {a["title"] for a in resp.json()}


@pytest.mark.parametrize(("url", "quoted"), [
    (ANIME_SEARCH_URL, {"Nt Literal": _NOTE_LITERAL, "Nt Near": _NOTE_NEAR, "Nt Pair": _NOTE_NEAR, "Nt Quote": _NOTE_QUOTED}),
    (MEDIA_SEARCH_URL, {
        "Nt Literal": _NOTE_LITERAL, "Nt Near": _NOTE_NEAR, "Nt Pair": _NOTE_NEAR,
        "Nt Quote": _NOTE_NEAR, "Nt Quote 2": _NOTE_QUOTED,
    }),
], ids=["anime", "media"])
async def test_notes_search_quotes_the_matched_note(client, user_auth_headers, db_session, noted_set, url, quoted):
    """An anime quotes its literal note over a nearer semantic one, as it ranked; a media
    its own note. A title search quotes nothing."""
    dist, _ = await _note_distances_and_cutoff(db_session, "izumi")
    assert dist["Nt Quote"] < dist["Nt Quote 2"]

    params = {"query": "izumi", "search_type": "rating_notes", "anime_season": _RANK_SEASON.filter}
    resp = await client.get(url, params=params, headers=user_auth_headers)
    assert resp.status_code == 200, resp.text
    assert {r["title"]: r["matched_note"] for r in resp.json()} == quoted

    resp = await client.get(url, params={**params, "query": "nt", "search_type": "title"}, headers=user_auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() and all(r["matched_note"] is None for r in resp.json())


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


@_BOTH_VIEWS
@pytest.mark.parametrize(("param", "value"), [
    ("limit", 0), ("limit", 1001), ("top_percent", 0), ("top_percent", 101), ("query", "x" * 201),
])
async def test_out_of_range_is_rejected(client, user_auth_headers, url, param, value):
    resp = await client.get(url, params={param: value}, headers=user_auth_headers)
    assert resp.status_code == 422


# (title, name_eng, name_jap). Latin "Japanese" names, so the order never depends on
# how the collation ranks kana against Latin. Mirrored by the frontend's `resolveTitle`
# test in format-string.test.ts.
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


async def _make_franchises(db_session, fixture: dict, *, mal_id: int, in_season: bool = True) -> None:
    """One anime per `fixture` key with its `(title, columns)` media, mal ids counting
    up from `mal_id`."""
    for offset, (title, media) in enumerate(fixture.items()):
        await _make_anime(
            db_session, mal_id=mal_id + offset, title=title, in_season=in_season,
            media=[{"title": media_title, **columns} for media_title, columns in media],
        )


@pytest.fixture
async def release_set(db_session):
    await _make_franchises(db_session, _RELEASE_FIXTURE, mal_id=87651, in_season=False)


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


_AIRING = {"airing_status": AIRING_STATUS_CURRENTLY_AIRING}

# Anime → its media, every title holding "Zqa". Where the latest-aired key and the release
# key part: Finished Airing has a finished main season (2017) and an airing one (Fall
# 2026), Finished Announced a finished one and an announcement — the release key would put
# them at Fall 2026 and Winter 2030.
_AIRED_FIXTURE = {
    "Zqa Finished Airing": [
        ("Zqa Finished Airing", _season(SeasonType.Spring, 2017)),
        ("Zqa Finished Airing 2", {**_season(SeasonType.Fall, 2026), **_AIRING}),
    ],
    "Zqa Nothing": [("Zqa Nothing", {})],
    "Zqa Announced Only": [
        ("Zqa Announced Only 2", {**_season(SeasonType.Fall, 2027), **_UNAIRED}),
        ("Zqa Announced Only", {**_season(SeasonType.Winter, 2027), **_UNAIRED}),
    ],
    "Zqa Side Later": [
        ("Zqa Side Later", _season(SeasonType.Spring, 2019)),
        ("Zqa Side Later OVA", {**_season(SeasonType.Fall, 2025), **_SIDE}),
    ],
    "Zqa Undated Only": [("Zqa Undated Only", _UNAIRED)],
    "Zqa Finished Announced": [
        ("Zqa Finished Announced", _season(SeasonType.Fall, 2020)),
        ("Zqa Finished Announced 2", {**_season(SeasonType.Winter, 2030), **_UNAIRED}),
    ],
    "Zqa Airing Only": [("Zqa Airing Only", {**_season(SeasonType.Spring, 2027), **_AIRING})],
}

# Undated Only at TBA · Airing Only Spring 2027 · Announced Only its closest announcement,
# Winter 2027 — its Fall 2027 would put it above Airing Only · Finished Announced Fall
# 2020, its announcement ignored · Side Later its main story's Spring 2019, not the OVA ·
# Finished Airing Spring 2017, finished before airing · Nothing, last either way.
_ANIME_AIRED_DESC = [
    "Zqa Undated Only", "Zqa Airing Only", "Zqa Announced Only", "Zqa Finished Announced",
    "Zqa Side Later", "Zqa Finished Airing", "Zqa Nothing",
]


@pytest.mark.parametrize("params", [{"sort": "aired"}, {"sort": "aired", "sort_dir": "asc"}], ids=["desc", "asc"])
async def test_aired_sort_is_the_latest_finished_main_season(client, user_auth_headers, db_session, params):
    """Newest first by default; ascending reverses every seasoned row, and the row
    without a season stays last."""
    await _make_franchises(db_session, _AIRED_FIXTURE, mal_id=87671, in_season=False)
    desc = _ANIME_AIRED_DESC
    expected = [*reversed(desc[:-1]), desc[-1]] if "sort_dir" in params else desc
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=ANIME_SEARCH_URL, expect=set(expected), in_season=False, query="zqa", **params,
    )
    assert ordered == expected


CLIENT_SEARCH = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "utils" / "search.ts"
# Anchored and `export`-pinned, as test_ratings.py reads `ratingLimits.ts`.
_CLIENT_ASCENDING = re.compile(r"^export const ASCENDING_SORTS: SortKey\[\] = \[(.*)\];$", re.M)


def test_the_search_menu_knows_which_sorts_ascend():
    """The menu names a sort's direction before the backend has ordered anything, so its
    default directions must be the backend's."""
    match = _CLIENT_ASCENDING.search(CLIENT_SEARCH.read_text())
    assert match, f"no ASCENDING_SORTS line in {CLIENT_SEARCH}"
    assert {key.strip(" '") for key in match.group(1).split(",")} == {key.value for key in ASCENDING_SORTS}


async def test_aired_sort_at_the_media_grain_is_each_media_season(client, user_auth_headers, release_set):
    """One media has one season, so the media grain orders as the release key does."""
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=MEDIA_SEARCH_URL, expect=set(_MEDIA_RELEASE_ASC), in_season=False,
        query="zqv", sort="aired", sort_dir="asc",
    )
    assert ordered == _MEDIA_RELEASE_ASC


# ---------------------------------------------------------------------------
# Upcoming main story, top N%, and any/all genres and studios
# ---------------------------------------------------------------------------


# Anime → its media (title, columns); Main and finished unless the columns say otherwise.
_UPCOMING_FIXTURE = {
    "Upm Continued": [("Upm Continued", {}), ("Upm Continued 2", _UNAIRED)],
    "Upm Airing": [
        ("Upm Airing", _AIRING),
        ("Upm Airing Alt", {**_UNAIRED, "relation_type": RelationType.AlternativeVersion}),
    ],
    "Upm Side": [("Upm Side", {}), ("Upm Side OVA", {**_UNAIRED, **_SIDE})],
    "Upm New": [("Upm New", _UNAIRED)],
    "Upm Done": [("Upm Done", {})],
}


@pytest.fixture
async def upcoming_set(db_session):
    await _make_franchises(db_session, _UPCOMING_FIXTURE, mal_id=87701)


@pytest.mark.parametrize(("url", "upcoming_main", "expected"), [
    (ANIME_SEARCH_URL, True, {"Upm Continued", "Upm Airing"}),
    (MEDIA_SEARCH_URL, True, {"Upm Continued 2", "Upm Airing Alt"}),
    (ANIME_SEARCH_URL, False, set(_UPCOMING_FIXTURE)),
    (MEDIA_SEARCH_URL, False, {title for media in _UPCOMING_FIXTURE.values() for title, _ in media}),
], ids=["anime", "media", "anime_off", "media_off"])
async def test_upcoming_main_keeps_announced_main_story_of_aired_anime(
    client, user_auth_headers, upcoming_set, url, upcoming_main, expected,
):
    """Continued (finished, then a season announced) and Airing (airing, then an
    alternative version announced — main story too) qualify. Side announces only a side
    story, New has aired nothing, Done announces nothing. The media grain keeps just the
    two announcements. Off, it filters nothing."""
    await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect=expected, upcoming_main=upcoming_main,
    )


_TOP_ANCHOR, _TOP_HIGH, _TOP_MID, _TOP_UNSCORED = "Topp Anchor", "Topp High", "Topp Mid", "Topp Unscored"
_TOP_FIXTURE = [_TOP_ANCHOR, _TOP_HIGH, _TOP_MID, _TOP_UNSCORED]


@pytest.fixture
async def top_percent_set(db_session):
    """Two scored rows and an unscored one in the sentinel season, and outside it an
    anchor that outranks any real title. The anchor counts toward every rank, so a
    ranking over only the rows a search selects disagrees with the badge.

    Three scored rows, so on CI, where they are the whole catalogue, every badge but
    the worst depends on rounding up: 34, 67 (and 100)."""
    await _make_anime(
        db_session, mal_id=87711, title=_TOP_ANCHOR, in_season=False,
        media=[{"title": _TOP_ANCHOR, "score": 10.0, "scored_by": 100_000_000}],
    )
    rows = [(_TOP_HIGH, 9.5, 1_000_000), (_TOP_UNSCORED, None, 0), (_TOP_MID, 7.5, 50_000)]
    for offset, (title, score, votes) in enumerate(rows):
        await _make_single(db_session, mal_id=87712 + offset, title=title, score=score, scored_by=votes)


async def _ids(db_session, model: type[Anime] | type[Media], titles) -> dict[str, int]:
    return dict((await db_session.execute(select(model.title, model.id).where(model.title.in_(titles)))).all())


def _grain(url: str) -> type[Anime] | type[Media]:
    return Anime if url == ANIME_SEARCH_URL else Media


async def _badges(db_session, url: str) -> dict[str, int | None]:
    """Each fixture row's "Top N%" badge, read through the badge's DAO."""
    dao = AnimeDAO() if url == ANIME_SEARCH_URL else MediaDAO()
    ids = await _ids(db_session, _grain(url), _TOP_FIXTURE)
    return {title: await dao.score_top_percent(db_session, id_) for title, id_ in ids.items()}


async def _badges_by_hand(db_session, url: str) -> dict[str, int | None]:
    """The badges counted out in Python over the whole catalogue's scored rows. The
    ranked population is written out here again rather than taken from
    `top_percent_ranking`: shared, a ranking scoped to fewer rows would pass."""
    if url == ANIME_SEARCH_URL:
        mean_score = weighted_mean_score_expr()
        stmt = (
            select(Media.anime_id, weighted_score_expr(mean_score, weighted_mean_votes_expr()))
            .group_by(Media.anime_id).having(mean_score.is_not(None))
        )
    else:
        stmt = select(Media.id, weighted_score_expr(Media.score, Media.scored_by)).where(Media.score.is_not(None))
    metrics = dict((await db_session.execute(stmt)).all())
    badges: dict[str, int | None] = {}
    for title, id_ in (await _ids(db_session, _grain(url), _TOP_FIXTURE)).items():
        if id_ not in metrics:
            badges[title] = None
            continue
        rank = 1 + sum(metric > metrics[id_] for metric in metrics.values())
        badges[title] = -(-rank * 100 // len(metrics))
    return badges


@_BOTH_VIEWS
async def test_top_percent_keeps_exactly_the_badges_it_names(client, user_auth_headers, db_session, top_percent_set, url):
    """N keeps every row whose badge reads N% or better: Mid at its own badge, not one
    point below. The badges are checked against a count by hand first, since the filter
    and the badge share one expression and would agree on any rounding. The anchor tops
    every catalogue, so it also pins the best rank to 1 + 0 better rows."""
    badges = await _badges(db_session, url)
    assert badges == await _badges_by_hand(db_session, url)
    assert badges[_TOP_UNSCORED] is None
    mid = badges[_TOP_MID]
    assert mid is not None and mid > 1

    in_season = {title: badge for title, badge in badges.items() if title != _TOP_ANCHOR}
    for top_percent in (mid, mid - 1, 100):
        expected = {title for title, badge in in_season.items() if badge is not None and badge <= top_percent}
        await _ordered_fixture_titles(
            client, user_auth_headers, url=url, expect=expected, top_percent=top_percent,
        )


_GENRE_A, _GENRE_B = "Gmode Genre A", "Gmode Genre B"
_GENRE_FIXTURE = {"Gmode Both": [_GENRE_A, _GENRE_B], "Gmode Only A": [_GENRE_A], "Gmode Only B": [_GENRE_B], "Gmode Neither": []}


@_BOTH_VIEWS
@pytest.mark.parametrize(("params", "expected"), [
    ({"genre_mode": "any"}, {"Gmode Both", "Gmode Only A", "Gmode Only B"}),
    ({"genre_mode": "all"}, {"Gmode Both"}),
    ({}, {"Gmode Both"}),
], ids=["any", "all", "default_all"])
async def test_genre_mode_needs_one_or_every_selected_genre(
    client, user_auth_headers, db_session, url, params, expected,
):
    """One media per anime, so each genre it carries is its anime's majority."""
    genres = {name: Genre(name=name, genre_type=GenreType.Genres, description="mode test") for name in (_GENRE_A, _GENRE_B)}
    db_session.add_all(genres.values())
    await db_session.flush()
    for offset, title in enumerate(_GENRE_FIXTURE):
        await _make_anime(db_session, mal_id=87721 + offset, title=title)
    media_ids = await _ids(db_session, Media, _GENRE_FIXTURE)
    db_session.add_all(
        MediaGenre(media_id=media_ids[title], genre_id=genres[name].id)
        for title, names in _GENRE_FIXTURE.items() for name in names
    )
    await db_session.flush()
    await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect=expected, genre_name=[_GENRE_A, _GENRE_B], **params,
    )


_STUDIO_X, _STUDIO_Y = "Smode Studio X", "Smode Studio Y"
_MOVIE = {"media_type": MediaType.Movie}

_STUDIO_FIXTURE = {
    "Smode Both": [("Smode Both", {})],
    "Smode Only X": [("Smode Only X", {}), ("Smode Only X 2", {})],
    "Smode Split": [("Smode Split", {}), ("Smode Split Movie", _MOVIE)],
    "Smode Neither": [("Smode Neither", {})],
}
# Media → its studios. Only X has two media, both by X, so an anime counting media
# instead of studios would reach two.
_STUDIO_CREDITS = {
    "Smode Both": [_STUDIO_X, _STUDIO_Y],
    "Smode Only X": [_STUDIO_X],
    "Smode Only X 2": [_STUDIO_X],
    "Smode Split": [_STUDIO_X],
    "Smode Split Movie": [_STUDIO_Y],
}


@pytest.fixture
async def studio_mode_set(db_session):
    studios = {name: Studio(name=name) for name in (_STUDIO_X, _STUDIO_Y)}
    db_session.add_all(studios.values())
    await db_session.flush()
    await _make_franchises(db_session, _STUDIO_FIXTURE, mal_id=87731)
    media_ids = await _ids(db_session, Media, _STUDIO_CREDITS)
    db_session.add_all(
        MediaStudio(media_id=media_ids[title], studio_id=studios[name].id)
        for title, names in _STUDIO_CREDITS.items() for name in names
    )
    await db_session.flush()


@pytest.mark.parametrize(("url", "mode", "expected"), [
    (ANIME_SEARCH_URL, "any", {"Smode Both", "Smode Only X", "Smode Split"}),
    (ANIME_SEARCH_URL, "all", {"Smode Both", "Smode Split"}),
    (MEDIA_SEARCH_URL, "any", {"Smode Both", "Smode Only X", "Smode Only X 2", "Smode Split", "Smode Split Movie"}),
    (MEDIA_SEARCH_URL, "all", {"Smode Both"}),
], ids=["anime_any", "anime_all", "media_any", "media_all"])
async def test_studio_mode_needs_one_or_every_selected_studio(
    client, user_auth_headers, studio_mode_set, url, mode, expected,
):
    """An anime carries the studios of all its media together: Split's two media, one
    by each, make it a match for both."""
    await _ordered_fixture_titles(
        client, user_auth_headers, url=url, expect=expected, studio_name=[_STUDIO_X, _STUDIO_Y], studio_mode=mode,
    )


@pytest.mark.parametrize(("studios", "expected"), [
    ([_STUDIO_X, _STUDIO_Y], {"any": {"Smode Both", "Smode Only X", "Smode Split"}, "all": {"Smode Both"}}),
    ([_STUDIO_X], {"any": {"Smode Both", "Smode Only X", "Smode Split"}, "all": {"Smode Both", "Smode Only X", "Smode Split"}}),
    ([_STUDIO_Y], {"any": {"Smode Both"}, "all": {"Smode Both"}}),
], ids=["x_and_y", "x", "y"])
async def test_studio_mode_counts_only_the_media_the_other_filters_match(
    client, user_auth_headers, studio_mode_set, studios, expected,
):
    """With type TV, an anime's studios are those of its TV media: Split's Y made only
    its movie, so Split is no TV by both. One studio then means the same in either
    mode, as it should."""
    for mode, titles in expected.items():
        await _ordered_fixture_titles(
            client, user_auth_headers, url=ANIME_SEARCH_URL, expect=titles,
            studio_name=studios, studio_mode=mode, media_type="TV",
        )


# ---------------------------------------------------------------------------
# The caller's own ratings and watchlist
# ---------------------------------------------------------------------------

_DONE, _HOLD, _DROP = "completed", "on_hold", "dropped"


async def _media_uuids(db_session, titles) -> dict[str, UUID]:
    return dict((await db_session.execute(select(Media.title, Media.uuid).where(Media.title.in_(titles)))).all())


async def _make_rated(db_session, client, headers, fixture: dict, *, mal_id: int) -> None:
    """`_make_franchises` over `fixture`, whose media are `(title, columns, status)`,
    each media with a status rated with it."""
    await _make_franchises(
        db_session, {anime: [(title, columns) for title, columns, _ in media] for anime, media in fixture.items()},
        mal_id=mal_id,
    )
    statuses = {title: status for media in fixture.values() for title, _, status in media if status}
    uuids = await _media_uuids(db_session, statuses)
    for title, status in statuses.items():
        await rate_media(client, headers, uuids[title], status)


# Anime → its media (title, columns, the caller's watch status); Main and finished unless
# the columns say otherwise.
_RATED_FIXTURE = {
    "Rst Unrated": [("Rst Unrated", {}, None)],
    "Rst Progress": [("Rst Progress", {}, _DONE), ("Rst Progress 2", {}, None)],
    "Rst Side Only": [("Rst Side Only", {}, None), ("Rst Side Only OVA", _SIDE, _DONE)],
    "Rst Main": [("Rst Main", {}, _DONE), ("Rst Main OVA", _SIDE, None)],
    "Rst All": [("Rst All", {}, _DONE), ("Rst All OVA", _SIDE, _DONE)],
    "Rst Dropped": [("Rst Dropped", {}, _DROP), ("Rst Dropped 2", {}, _HOLD)],
    "Rst On Hold": [("Rst On Hold", {}, _HOLD), ("Rst On Hold 2", {}, _DONE)],
    "Rst Side Bailed": [
        ("Rst Side Bailed", {}, _DONE), ("Rst Side Bailed 2", {}, None),
        ("Rst Side Bailed OVA", _SIDE, _DROP), ("Rst Side Bailed Special", _SIDE, _HOLD),
    ],
    "Rst Unaired Main": [("Rst Unaired Main", _UNAIRED, None), ("Rst Unaired Main OVA", _SIDE, _DONE)],
    "Rst Sequel": [("Rst Sequel", {}, _DONE), ("Rst Sequel 2", _UNAIRED, None)],
}

# The anime states, written out by hand. Each precedence case has a row where the other
# order gives another state: Dropped holds an on-hold main too, All is also main-complete.
# Side Bailed dropped and paused only side stories, so it stays in progress; Unaired Main
# has no rateable main, so its finished side story makes it neither main nor all; Sequel's
# announced main can't be rated, so it is all. Untested: dropped and on-hold count only
# rateable mains, which needs a rating on an unaired media — no write path makes one.
_ANIME_STATES = {
    "Rst Unrated": "none", "Rst Progress": "in_progress", "Rst Side Only": "in_progress",
    "Rst Main": "main", "Rst All": "all", "Rst Dropped": "dropped", "Rst On Hold": "on_hold",
    "Rst Side Bailed": "in_progress", "Rst Unaired Main": "in_progress", "Rst Sequel": "all",
}
_MEDIA_STATES = {title: status or "none" for media in _RATED_FIXTURE.values() for title, _, status in media}

# Main and All are listed through a side story only: an anime is listed when any of its
# media is.
_LISTED_MEDIA = {"Rst Unrated", "Rst Progress 2", "Rst Main OVA", "Rst All OVA"}
_LISTED_ANIME = {"Rst Unrated", "Rst Progress", "Rst Main", "Rst All"}


@pytest.fixture
async def rated_set(db_session, client, user_auth_headers):
    await _make_rated(db_session, client, user_auth_headers, _RATED_FIXTURE, mal_id=87801)
    await list_media(client, user_auth_headers, *(await _media_uuids(db_session, _LISTED_MEDIA)).values())


def _personal_expect(states: dict[str, str], listed: set[str], rated=None, watchlisted=None) -> set[str]:
    return {
        title for title, state in states.items()
        if (rated is None or state in rated) and (watchlisted is None or (title in listed) == watchlisted)
    }


def _case_id(params: dict) -> str:
    return "&".join(f"{key}={'+'.join(value) if isinstance(value, list) else value}" for key, value in params.items())


@pytest.mark.parametrize("params", [
    {"rated": ["none"]}, {"rated": ["in_progress"]}, {"rated": ["on_hold"]}, {"rated": ["dropped"]},
    {"rated": ["main"]}, {"rated": ["all"]},
    {"rated": ["none", "main"]}, {"rated": ["in_progress", "on_hold"]},
    {"rated": ["none", "in_progress", "on_hold", "dropped", "main", "all"]},
    {"watchlisted": True}, {"watchlisted": False},
    {"rated": ["none"], "watchlisted": True}, {"rated": ["in_progress"], "watchlisted": True},
    {"rated": ["none", "dropped"], "watchlisted": False}, {"rated": ["all"], "watchlisted": False},
], ids=_case_id)
async def test_anime_rated_states_and_watchlist(client, user_auth_headers, rated_set, params):
    """Each state alone and in unions, listed or not, and both together."""
    await _ordered_fixture_titles(
        client, user_auth_headers, url=ANIME_SEARCH_URL,
        expect=_personal_expect(_ANIME_STATES, _LISTED_ANIME, **params), **params,
    )


@pytest.mark.parametrize("params", [
    {"rated": ["none"]}, {"rated": ["completed"]}, {"rated": ["on_hold"]}, {"rated": ["dropped"]},
    {"rated": ["none", "dropped"]}, {"rated": ["completed", "on_hold"]},
    {"rated": ["none", "completed", "on_hold", "dropped"]},
    {"watchlisted": True}, {"watchlisted": False},
    {"rated": ["none"], "watchlisted": True}, {"rated": ["completed"], "watchlisted": True},
    {"rated": ["completed"], "watchlisted": False},
], ids=_case_id)
async def test_media_rated_states_and_watchlist(client, user_auth_headers, rated_set, params):
    """A media's state is its own rating's watch status, whatever its anime's is."""
    await _ordered_fixture_titles(
        client, user_auth_headers, url=MEDIA_SEARCH_URL,
        expect=_personal_expect(_MEDIA_STATES, _LISTED_MEDIA, **params), **params,
    )


@pytest.mark.parametrize(("url", "rated"), [
    (MEDIA_SEARCH_URL, ["in_progress"]), (MEDIA_SEARCH_URL, ["none", "main"]), (MEDIA_SEARCH_URL, ["all"]),
    (ANIME_SEARCH_URL, ["completed"]),
], ids=["media_in_progress", "media_main", "media_all", "anime_completed"])
async def test_rated_state_of_the_other_grain_is_rejected(client, user_auth_headers, url, rated):
    resp = await client.get(url, params={"rated": rated}, headers=user_auth_headers)
    assert resp.status_code == 400, resp.text


@_BOTH_VIEWS
@pytest.mark.parametrize(("params", "status"), [
    ({}, 200),
    ({"rated": ["none"]}, 403),
    ({"watchlisted": True}, 403),
    ({"watchlisted": False}, 403),
    ({"sort": "your_rating"}, 403),
    ({"search_type": "rating_notes", "query": "izumi"}, 403),
    ({"search_type": "rating_notes"}, 403),
], ids=["plain", "rated", "watchlisted", "not_watchlisted", "your_rating", "notes", "notes_no_query"])
async def test_personal_filters_and_sort_are_closed_to_guests(
    client, restricted_user_auth_headers, url, params, status,
):
    """A guest searches, but has no ratings, notes or watchlist to search by."""
    resp = await client.get(
        url, params={"anime_season": _RANK_SEASON.filter, **params}, headers=restricted_user_auth_headers,
    )
    assert resp.status_code == status, resp.text


@pytest.mark.parametrize(("url", "dao", "method"), [
    (ANIME_SEARCH_URL, anime_search_service.anime_dao, "search_anime_aggregated"),
    (MEDIA_SEARCH_URL, media_search_service.media_dao, "search_media_with_filters"),
], ids=["anime", "media"])
async def test_an_empty_personal_scope_skips_the_search(client, user_auth_headers, monkeypatch, url, dao, method):
    """Nothing dropped, so nothing can match, and no search query runs."""
    async def never(*args, **kwargs):
        raise AssertionError("searched an empty scope")
    monkeypatch.setattr(dao, method, never)
    resp = await client.get(url, params={"rated": ["dropped"]}, headers=user_auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


# Anime → its media (title, columns, the caller's rating); Main unless the columns say
# otherwise. Inserted in an order no expected one follows.
_YOURS = {
    "Yr Six": [("Yr Six", {"score": 8.5}, 6.0)],
    "Yr Mixed": [
        ("Yr Mixed", {"score": 8.0}, 9.0), ("Yr Mixed 2", {"score": 8.0}, 5.0),
        ("Yr Mixed Side", {**_SIDE, "score": 6.0}, None),
    ],
    "Yr Unrated": [("Yr Unrated", {"score": 9.0}, None)],
    "Yr Eight": [("Yr Eight", {"score": 7.0}, 8.0)],
}


@pytest.mark.parametrize(("url", "descending", "unrated"), [
    (ANIME_SEARCH_URL, ["Yr Eight", "Yr Mixed", "Yr Six"], ["Yr Unrated"]),
    (MEDIA_SEARCH_URL, ["Yr Mixed", "Yr Eight", "Yr Six", "Yr Mixed 2"], ["Yr Unrated", "Yr Mixed Side"]),
], ids=["anime", "media"])
@pytest.mark.parametrize("sort_dir", [None, "desc", "asc"], ids=["default", "desc", "asc"])
async def test_your_rating_sorts_by_the_callers_mean(
    client, user_auth_headers, admin_auth_headers, db_session, url, descending, unrated, sort_dir,
):
    """An anime sorts at the mean of the caller's ratings over its rated media: Mixed's 9
    and 5 make 7, between Eight and Six, where the max, min, sum or an unrated side
    story counted as 0 would put it elsewhere. A media sorts at its own rating. Top rated
    runs the other way (Unrated, Six, Mixed, Eight). Unrated rows come last both ways —
    Unrated although the admin rated it 10 — in the weighted score's order."""
    await _make_franchises(db_session, {
        anime: [(title, {**columns, "scored_by": 100_000}) for title, columns, _ in media]
        for anime, media in _YOURS.items()
    }, mal_id=87821)
    ratings = {title: rating for media in _YOURS.values() for title, _, rating in media if rating}
    uuids = await _media_uuids(db_session, [*ratings, "Yr Unrated"])
    for title, rating in ratings.items():
        await rate_media(client, user_auth_headers, uuids[title], _DONE, rating)
    await rate_media(client, admin_auth_headers, uuids["Yr Unrated"], _DONE, 10.0)

    expected = [*(reversed(descending) if sort_dir == "asc" else descending), *unrated]
    params = {"sort": "your_rating"} | ({"sort_dir": sort_dir} if sort_dir else {})
    ordered = await _ordered_fixture_titles(client, user_auth_headers, url=url, expect=set(expected), **params)
    assert ordered == expected


@pytest.mark.parametrize("params", [
    {"rated": ["in_progress"]}, {"watchlisted": True}, {"sort": "your_rating"},
    {"query": "greenhouse", "search_type": "rating_notes"},
], ids=["rated", "watchlisted", "your_rating", "notes"])
async def test_personal_filters_and_sort_do_not_rescope_the_aggregates(
    client, user_auth_headers, db_session, params,
):
    """The caller rated, noted and listed only the side story (weight 0) of an anime
    whose main story scores 8.0. Narrowing the grouped rows to those media would leave
    the anime unscored, and `score_min` — a HAVING over Phase A's aggregates, which the
    card's refetch never sees — would drop it."""
    await _make_anime(db_session, mal_id=87831, title="Rsc Scoped", media=[
        {"title": "Rsc Scoped", "score": 8.0, "scored_by": 1000},
        {"title": "Rsc Scoped OVA", "relation_type": RelationType.SideStory, "score": 5.0, "scored_by": 1000},
    ])
    side = (await _media_uuids(db_session, ["Rsc Scoped OVA"]))["Rsc Scoped OVA"]
    await rate_media(client, user_auth_headers, side, _DONE, note="The greenhouse special was charming.")
    await list_media(client, user_auth_headers, side)
    await _ordered_fixture_titles(
        client, user_auth_headers, url=ANIME_SEARCH_URL, expect={"Rsc Scoped"}, score_min=7, **params,
    )


def _announced(name: SeasonType, year: int) -> dict:
    return {**_season(name, year), **_UNAIRED}


# Inserted latest announcement first; Dropped and Unrated announce earliest, so either
# would lead if it slipped in, and Finished is all done but announces nothing.
_CONTINUATIONS = {
    "Anc Later": [("Anc Later", {}, _DONE), ("Anc Later 2", _announced(SeasonType.Fall, 2031), None)],
    "Anc Hold": [("Anc Hold", {}, _HOLD), ("Anc Hold 2", _announced(SeasonType.Spring, 2031), None)],
    "Anc Main": [
        ("Anc Main", {}, _DONE), ("Anc Main OVA", _SIDE, None),
        ("Anc Main 2", _announced(SeasonType.Summer, 2030), None),
    ],
    "Anc Progress": [
        ("Anc Progress", {}, _DONE), ("Anc Progress 2", {}, None),
        ("Anc Progress 3", _announced(SeasonType.Winter, 2030), None),
    ],
    "Anc Dropped": [("Anc Dropped", {}, _DROP), ("Anc Dropped 2", _announced(SeasonType.Winter, 2029), None)],
    "Anc Unrated": [("Anc Unrated", {}, None), ("Anc Unrated 2", _announced(SeasonType.Winter, 2029), None)],
    "Anc Finished": [("Anc Finished", {}, _DONE)],
}
_CONTINUATIONS_QUERY = {
    "sort": "release", "upcoming_main": True, "rated": ["in_progress", "on_hold", "main", "all"], "limit": 25,
}


async def test_announced_continuations_carousel(
    client, user_auth_headers, restricted_user_auth_headers, db_session,
):
    """The anime you have rated, short of dropping them, with a main story announced —
    the next season first."""
    await _make_rated(db_session, client, user_auth_headers, _CONTINUATIONS, mal_id=87841)
    expected = ["Anc Progress", "Anc Main", "Anc Hold", "Anc Later"]
    ordered = await _ordered_fixture_titles(
        client, user_auth_headers, url=ANIME_SEARCH_URL, expect=set(expected), **_CONTINUATIONS_QUERY,
    )
    assert ordered == expected

    resp = await client.get(ANIME_SEARCH_URL, params=_CONTINUATIONS_QUERY, headers=restricted_user_auth_headers)
    assert resp.status_code == 403, resp.text


@pytest.mark.parametrize("params", [{"watchlisted": True}, {"rated": ["none"]}], ids=["watchlisted", "unrated"])
async def test_media_personal_filters_stay_inside_the_spoiler_frontier(
    client, user_auth_headers, db_session, params,
):
    """In hide mode, rating Spf 1 reveals it and the next main, Spf 2; Spf 3 lies beyond
    the frontier. Listed and unrated, Spf 3 still stays hidden: the personal filters
    narrow the visible set, never replace it."""
    await _make_anime(db_session, mal_id=87851, title="Spf", media=[{"title": f"Spf {n}"} for n in (1, 2, 3)])
    uuids = await _media_uuids(db_session, ["Spf 1", "Spf 2", "Spf 3"])
    await rate_media(client, user_auth_headers, uuids["Spf 1"], _DONE)
    await list_media(client, user_auth_headers, uuids["Spf 2"], uuids["Spf 3"])
    resp = await client.put("/users/settings", json={"spoiler_level": "hide"}, headers=user_auth_headers)
    assert resp.status_code == 200, resp.text
    await _ordered_fixture_titles(client, user_auth_headers, url=MEDIA_SEARCH_URL, expect={"Spf 2"}, **params)


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
