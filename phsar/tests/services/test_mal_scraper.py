import re

import pytest

from app.services.mal_scraper import (
    MalScraper,
    _mal_date_to_iso,
    is_hentai,
    parse_relation_edges,
)

# MAL v2 emits media_type lowercase/snake_case; the test builders keep the
# Jikan-era display strings as their public keyword so callers don't churn,
# and translate INTERNALLY to the MAL wire value here.
_MEDIA_TYPE_DISPLAY_TO_MAL = {
    "TV": "tv",
    "Movie": "movie",
    "OVA": "ova",
    "ONA": "ona",
    "Special": "special",
    "TVSpecial": "tv_special",
    "Music": "music",
    "PV": "pv",
    "CM": "cm",
}


def _media_type_to_mal(display: str | None) -> str:
    """Display-case media_type → MAL v2 wire value. None/unknown → 'unknown'
    (which extract_information maps back to None)."""
    if display is None:
        return "unknown"
    return _MEDIA_TYPE_DISPLAY_TO_MAL.get(display, display.lower())


def _duration_to_seconds(duration: str | None) -> int | None:
    """Parse a Jikan-style duration string into seconds. MAL v2 has no such
    string (it ships `average_episode_duration` as an int), so this now lives
    in the test layer: it converts the builders' human `duration=` keyword
    into the MAL `average_episode_duration` field. Signs and stray fragments
    are ignored; a zero total collapses to None (Unknown)."""
    if not duration:
        return None
    total = 0
    for value, unit in re.findall(r"(\d+)\s*(hr|min|sec)", duration):
        total += int(value) * {"hr": 3600, "min": 60, "sec": 1}[unit]
    return total or None


def _related(*pairs: tuple[int, str]) -> list[dict]:
    """Build a MAL v2 `related_anime` list from `(target_mal_id, relation_label)`
    pairs. Each entry is `{"node": {...}, "relation_type", "relation_type_formatted"}`
    — the shape `parse_relation_edges` consumes. Replaces the Jikan-era
    `_relations_response` (there is no `/relations` endpoint in v2; relations
    ride inside the detail response)."""
    return [
        {
            "node": {"id": target, "title": f"Anime {target}", "main_picture": {}},
            "relation_type": normalize,
            "relation_type_formatted": normalize,
        }
        for target, normalize in pairs
    ]


def _make_anime(
    mal_id: int,
    title: str | None,
    *,
    media_type: str = "TV",
    duration: str = "23 min per ep",
    episodes: int = 12,
    aired_from: str = "2020-04-01T00:00:00+00:00",
    related_anime: list | None = None,
) -> dict:
    """Minimum MAL v2 anime object accepted by extract_information without
    nulls. Keeps the Jikan-era display keywords (media_type='TV',
    duration='23 min per ep', full-ISO aired_from) and translates them to the
    MAL wire shape internally. `related_anime` rides in the SAME object (v2
    bundles relations into the detail response)."""
    start_date = aired_from.split("T")[0] if aired_from else None
    return {
        "id": mal_id,
        "title": title,
        "alternative_titles": {"en": title, "ja": title, "synonyms": []},
        "main_picture": {
            "medium": "https://example/cover.jpg",
            "large": "https://example/cover.jpg",
        },
        "start_date": start_date,
        "end_date": "2020-06-30",
        "synopsis": "",
        "mean": 7.5,
        "num_scoring_users": 1000,
        "num_episodes": episodes,
        "media_type": _media_type_to_mal(media_type),
        "status": "finished_airing",
        "genres": [{"id": 1, "name": "Action"}],
        "source": "original",
        "average_episode_duration": _duration_to_seconds(duration),
        "rating": "pg_13",
        "start_season": {"year": 2020, "season": "spring"},
        "studios": [{"id": 1, "name": "Studio Test"}],
        "related_anime": related_anime or [],
    }


@pytest.mark.asyncio
async def test_search_title_records_cross_link_for_pre_excluded_relation(monkeypatch):
    """When BFS would traverse to a media that's already in the catalog
    via a non-boundary relation, that mal_id is surfaced as a cross-link
    signal for the merge-candidate detector to use.

    Setup needs at least one non-excluded sibling so the graph stays
    non-empty; without that we'd produce an empty graph and lose the
    cross-link with it.
    """
    detail_calls: list[int] = []

    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            # 2 fresh sibling (keeps graph non-empty), 42 pre-excluded → cross-link.
            return {"data": [{"node": _make_anime(
                1, "Origin Anime",
                related_anime=_related((2, "Sequel"), (42, "Sequel")),
            )}]}

        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            detail_calls.append(mal_id)
            rels = {2: [(1, "Prequel")]}.get(mal_id, [])
            return _make_anime(mal_id, f"Anime {mal_id}", related_anime=_related(*rels))

        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids={42},
        )

    assert len(relations) == 1
    graph, _edges, cross_link_mal_ids = relations[0]

    # 42 was pre-excluded so it doesn't appear in the graph...
    assert 42 not in graph
    # ...and we never fetched its detail (it was already known).
    assert 42 not in detail_calls
    # ...but the cross-link signal captures it for the detector.
    assert cross_link_mal_ids == {42}
    # The non-excluded sibling is in the graph as expected.
    assert 1 in graph and 2 in graph


@pytest.mark.asyncio
async def test_search_title_does_not_blacklist_not_yet_aired_anime(monkeypatch):
    """Just-announced sequels (`media_type=None` + `status="Not yet aired"`)
    must skip silently — a permanent unwanted entry would block
    rediscovery once MAL fills the type."""
    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _make_anime(
                1, "Origin Anime", related_anime=_related((2, "Sequel")),
            )}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            obj = _make_anime(mal_id, f"Anime {mal_id}")
            if mal_id == 2:
                obj["media_type"] = "unknown"
                obj["status"] = "not_yet_aired"
                obj["start_date"] = None
                obj["end_date"] = None
            return obj
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        _relations, _all_info, unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids=set(),
        )

    assert all(uw[0] != 2 for uw in unwanted), (
        "Not-yet-aired anime (mal_id=2) must NOT land in unwanted_media"
    )


@pytest.mark.asyncio
async def test_search_title_seed_empty_data_raises_transient_not_permanent(monkeypatch):
    """When MAL returns 200 OK with an empty body (observed in practice
    for legitimate mal_ids on transient hiccups), search_title must
    raise TransientUpstreamError — NOT AnimeNotFoundError. The
    difference matters downstream: TransientUpstreamError is not a
    PermanentPhsarError, so the worker stamps retryable=True and the
    bell shows its retry button. The old behavior produced retryable=False
    + an opaque 'mal_id=N not found' message, locking the user out for
    the dedup window for a transient MAL anomaly."""
    from app.exceptions import AnimeNotFoundError, TransientUpstreamError

    async def fake_get(self, url: str, params=None):
        # MAL responded with 200 OK but no payload — the exact transient
        # case observed in production (job 2617 for mal_id=64060). In v2 the
        # detail call returns the object directly (no `data` wrapper), so an
        # empty body is an empty dict.
        if "/anime/" in url and url.rsplit("/", 1)[-1].isdigit():
            return {}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        with pytest.raises(TransientUpstreamError) as exc_info:
            await scraper.search_title(
                title="Re:Prism", excluded_mal_ids=set(), seed_mal_id=64060,
            )

    assert "mal_id=64060" in str(exc_info.value)
    # And critically: TransientUpstreamError is NOT a PermanentPhsarError
    # so the worker treats it as retryable.
    from app.exceptions import PermanentPhsarError
    assert not isinstance(exc_info.value, PermanentPhsarError)
    # ...and not the wrong error class either.
    assert not isinstance(exc_info.value, AnimeNotFoundError)


@pytest.mark.asyncio
async def test_search_title_seed_always_in_graph(monkeypatch):
    """Seed always appears in the graph from t=0 — no drop, no
    post-loop recovery. Works even for Rilakkuma-shaped franchises
    where the seed's only relation is `Other` and no node points back."""
    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _make_anime(
                1, "Origin TV", related_anime=_related((2, "Other")),
            )}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            rels = {2: [(3, "Other")]}.get(mal_id, [])
            return _make_anime(
                mal_id, f"Anime {mal_id}", media_type="ONA",
                related_anime=_related(*rels),
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, all_info, _unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids={3},
        )

    assert len(relations) == 1
    graph, _edges, _cross_links = relations[0]
    assert 1 in graph
    assert 1 in all_info


@pytest.mark.asyncio
async def test_search_title_skips_alternative_setting_relations(monkeypatch):
    """`alternative_setting` is a separate-franchise marker on MAL
    (e.g., Zhe Tian ↔ Wanmei Shijie, Madoka Magica ↔ Magia Record).
    The BFS must NOT walk it — `parse_relation_edges` drops the edge
    entirely — otherwise distinct donghua get conflated into one Anime
    row and the merge detector fires false positives on every sweep.

    Setup: seed has Sequel → 2 (legit branch, BFS walks) AND
    Alternative Setting → 99 (separate franchise, BFS must NOT walk).
    If 99 ever gets fetched, the test fails."""
    detail_calls: list[int] = []

    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _make_anime(
                1, "Origin Anime",
                related_anime=_related((2, "Sequel"), (99, "Alternative Setting")),
            )}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            detail_calls.append(mal_id)
            if mal_id == 99:
                raise AssertionError(
                    f"Alternative-setting branch was walked into mal_id={mal_id}"
                )
            rels = {2: [(1, "Prequel")]}.get(mal_id, [])
            return _make_anime(mal_id, f"Anime {mal_id}", related_anime=_related(*rels))
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids=set(),
        )

    assert len(relations) == 1
    graph, _edges, _cross_links = relations[0]
    # The sequel branch was walked; the alt-setting branch wasn't.
    assert 2 in graph
    assert 99 not in graph
    assert 99 not in detail_calls


@pytest.mark.asyncio
async def test_search_title_captures_normalized_edges(monkeypatch):
    """BFS captures every edge with the normalized MAL relation string.
    `normalize_relation` lowercases + underscores so the classifier sees
    a stable taxonomy.

    Naruto-shaped fixture verifies the full franchise traverses and that
    all node outgoing edges land with their normalized labels. Movies
    (side_stories) arrive as TERMINAL under the v0.14.2 strict boundary:
    they're in the graph and their outgoing edges ARE captured (so
    split-detection can later see e.g. a Movie's own sequel chain), but
    the BFS does NOT recurse from them — Movie targets stay out of the
    graph unless reached via another WALK path.

    Classification semantics (movies-via-parent_story → side_story)
    are tested in test_relation_classifier.py.
    """
    relations_by_id = {
        20: [(1735, "Sequel"), (894, "Side Story"), (936, "Side Story")],
        1735: [(20, "Prequel"), (5085, "Side Story")],
        894: [(20, "Parent story")],
        936: [(20, "Parent story")],
        5085: [(1735, "Parent story")],
    }
    type_by_id = {20: "TV", 1735: "TV", 894: "Movie", 936: "OVA", 5085: "Movie"}
    title_by_id = {
        20: "Naruto",
        1735: "Naruto: Shippuuden",
        894: "Naruto Movie 1",
        936: "Naruto OVA",
        5085: "Naruto Shippuuden Movie 1",
    }

    def _obj(mal_id: int) -> dict:
        return _make_anime(
            mal_id, title_by_id[mal_id], media_type=type_by_id[mal_id],
            related_anime=_related(*relations_by_id[mal_id]),
        )

    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _obj(20)}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return _obj(mal_id)
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Naruto", excluded_mal_ids=set(),
        )

    assert len(relations) == 1
    graph, edges, _cross_links = relations[0]

    assert set(graph.keys()) == {20, 1735, 894, 936, 5085}

    # Every node's outgoing edges land as normalized edge labels — WALK
    # AND TERMINAL nodes both contribute. 20 (Naruto TV) and 1735
    # (Shippuuden) walk; 894/936/5085 are TERMINAL but their detail is
    # fetched so the reverse parent_story edges back to TV ARE in the
    # persisted list. The BFS just doesn't recurse from them.
    edge_set = {(a, b, r) for a, b, r in edges}
    assert (20, 1735, "sequel") in edge_set
    assert (20, 894, "side_story") in edge_set
    assert (20, 936, "side_story") in edge_set
    assert (1735, 5085, "side_story") in edge_set
    # Reverse parent_story edges from the TERMINAL Movies/OVA back to TV
    # ARE captured — TERMINAL captures outgoing edges so split-detection
    # has the data it needs to see if a Movie has its own franchise chain.
    assert (894, 20, "parent_story") in edge_set
    assert (936, 20, "parent_story") in edge_set
    assert (5085, 1735, "parent_story") in edge_set


@pytest.mark.asyncio
async def test_search_title_skips_null_title_pv_silently(monkeypatch):
    """MAL occasionally leaves `title=null` on entries it's still
    populating (romanization pending, brand-new PV stubs). Skip silently
    rather than blacklisting — mirrors the Not-yet-aired pattern:
    next sweep that reaches the mal_id will re-fetch it and, once MAL
    has populated the title, normal Music/PV/CM classification produces
    a MediaUnwanted row with the real name.

    Test setup: mal_id=2 is a PV with `title=null`. It must NOT appear
    in unwanted_media — the BFS effectively treated it as a deferred
    entry, same as Not-yet-aired.
    """
    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _make_anime(
                1, "Origin Anime", related_anime=_related((2, "Other")),
            )}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            obj = _make_anime(mal_id, f"Anime {mal_id}")
            if mal_id == 2:
                # PV with no title at all — the exact production failure.
                obj["title"] = None
                obj["media_type"] = "pv"
            return obj
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        _relations, _all_info, unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids=set(),
        )

    assert all(uw[0] != 2 for uw in unwanted), (
        "Null-title PV (mal_id=2) must NOT land in unwanted_media — "
        "we wait for MAL to populate the title rather than baking a "
        "placeholder into MediaUnwanted forever"
    )
    # And critically: every tuple in unwanted_media is fully-typed
    # (no None on title or reason) so SearchResultDBExtended validation
    # passes downstream.
    for uw_mal_id, uw_title, uw_reason in unwanted:
        assert uw_title is not None
        assert uw_reason is not None


@pytest.mark.asyncio
async def test_search_title_skips_null_title_unknown_anomaly_silently(monkeypatch):
    """The non-Not-yet-aired-no-media_type branch (`Unknown` reason)
    ALSO defers a null-title entry instead of blacklisting it. A fully
    anonymous entry (title=null AND media_type=null AND not
    Not-yet-aired) is the most likely shape for an MAL placeholder
    that'll be populated later; permanently blacklisting it would
    surface as a 'why isn't this anime in the catalog?' bug forever."""
    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _make_anime(
                1, "Origin Anime", related_anime=_related((2, "Other")),
            )}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            obj = _make_anime(mal_id, f"Anime {mal_id}")
            if mal_id == 2:
                obj["title"] = None
                obj["media_type"] = "unknown"  # Unknown branch if not for title=null guard
                obj["status"] = "finished_airing"  # not Not-yet-aired
            return obj
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        _relations, _all_info, unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids=set(),
        )

    assert all(uw[0] != 2 for uw in unwanted), (
        "Fully-anonymous entry (mal_id=2) must NOT be blacklisted as "
        "Unknown — title=null is treated as transient regardless of "
        "other fields"
    )


@pytest.mark.asyncio
async def test_search_title_blacklists_other_anomalous_no_media_type(monkeypatch):
    """Anime with `media_type=None` but a non-`Not yet aired` status is
    still a MAL anomaly worth blacklisting — keeps the existing
    Music/PV/CM/Hentai pattern intact for true outliers."""
    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _make_anime(
                1, "Origin Anime", related_anime=_related((2, "Other")),
            )}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            obj = _make_anime(mal_id, f"Anime {mal_id}")
            if mal_id == 2:
                obj["media_type"] = "unknown"
                # Status is set (not "Not yet aired") — anomalous.
                obj["status"] = "finished_airing"
            return obj
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        _relations, _all_info, unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids=set(),
        )

    assert any(uw[0] == 2 and uw[2] == "Unknown" for uw in unwanted)


# ---------------------------------------------------------------------------
# is_hentai + hentai skip (v0.14.14)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "info, expected",
    [
        ({"genres": ["Action", "Hentai"]}, True),
        ({"genres": ["hentai"]}, True),  # case-insensitive genre match
        ({"genres": ["Action"], "age_rating": "Rx - Hentai"}, True),  # Rx signal
        ({"genres": [], "age_rating": None}, False),
        ({"genres": ["Ecchi"], "age_rating": "R+ - Mild Nudity"}, False),  # Ecchi/R+ ≠ hentai
        ({}, False),  # missing keys are None-safe
    ],
)
def test_is_hentai(info, expected):
    assert is_hentai(info) is expected


@pytest.mark.asyncio
async def test_search_title_blacklists_hentai_with_null_media_type(monkeypatch):
    """A hentai node with a null media_type is blacklisted as Hentai — the
    check now runs BEFORE the media_type gate, so it no longer falls through
    to the null-media_type 'Unknown' anomaly branch (v0.14.14 hardening)."""
    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _make_anime(
                1, "Origin Anime", related_anime=_related((2, "Other")),
            )}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            obj = _make_anime(mal_id, f"Anime {mal_id}")
            if mal_id == 2:
                obj["media_type"] = "unknown"  # None after translate
                obj["genres"] = [{"id": 12, "name": "Hentai"}]
                obj["status"] = "finished_airing"
            return obj
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        _relations, _all_info, unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids=set(),
        )

    assert any(uw[0] == 2 and uw[2] == "Hentai" for uw in unwanted), (
        "Null-media_type hentai node must be blacklisted as Hentai (checked "
        "before the media_type gate), not the 'Unknown' anomaly branch"
    )


# ---------------------------------------------------------------------------
# extract_information + value-translation unit tests (MAL v2 → catalog shape)
# ---------------------------------------------------------------------------


def test_extract_information_maps_mal_object_to_catalog_shape():
    """A MAL v2 object round-trips through extract_information into the
    Jikan-era catalog shape: display-case media_type, full-ISO aired
    dates, the constructed mal_url, and the dropped duration string with
    duration_seconds carried through from average_episode_duration."""
    info = MalScraper().extract_information(_make_anime(1, "X"))

    assert info["mal_id"] == 1
    assert info["mal_url"] == "https://myanimelist.net/anime/1"
    assert info["media_type"] == "TV"
    assert info["age_rating"] == "PG-13 - Teens 13 or older"
    assert info["original_source"] == "Original"
    assert info["airing_status"] == "Finished Airing"
    assert info["duration"] is None
    assert info["duration_seconds"] == 23 * 60
    assert info["aired_from"] == "2020-04-01T00:00:00+00:00"
    assert info["aired_to"] == "2020-06-30T00:00:00+00:00"
    assert info["cover_image"] == "https://example/cover.jpg"


def test_extract_information_translates_mal_enums():
    """The translation maps convert MAL's snake_case/lowercase enum values
    back to the Jikan-era strings the catalog + filter surfaces store."""
    obj = {
        "id": 5,
        "title": "X",
        "alternative_titles": {"en": "X", "ja": "X", "synonyms": []},
        "main_picture": {"large": "https://example/cover.jpg"},
        "start_date": "2020-04-01",
        "end_date": "2020-06-30",
        "synopsis": "Plot.",
        "mean": 7.5,
        "num_scoring_users": 1000,
        "num_episodes": 1,
        "media_type": "tv_special",
        "status": "currently_airing",
        "genres": [{"id": 1, "name": "Action"}],
        "source": "light_novel",
        "average_episode_duration": 1380,
        "rating": "r",
        "start_season": {"year": 2020, "season": "spring"},
        "studios": [{"id": 1, "name": "Studio Test"}],
        "related_anime": [],
    }
    info = MalScraper().extract_information(obj)

    assert info["media_type"] == "TVSpecial"
    assert info["airing_status"] == "Currently Airing"
    assert info["age_rating"] == "R - 17+ (violence & profanity)"
    assert info["original_source"] == "Light novel"


def test_mal_date_to_iso_handles_partial_dates():
    """MAL emits partial dates (`YYYY`, `YYYY-MM`) for older/imprecise
    records; the missing month/day fill with 01 at midnight UTC to
    reproduce Jikan's normalization exactly."""
    assert _mal_date_to_iso("2011") == "2011-01-01T00:00:00+00:00"
    assert _mal_date_to_iso("2011-04") == "2011-04-01T00:00:00+00:00"
    assert _mal_date_to_iso("2011-04-02") == "2011-04-02T00:00:00+00:00"
    assert _mal_date_to_iso(None) is None


def test_parse_relation_edges_aliases_spinoff_and_excludes_character():
    """`parse_relation_edges` normalizes MAL relation labels: `spin_off`
    aliases to the hyphenated catalog form, and `character` (the
    cross-franchise collab route) is excluded from edge capture."""
    related = [
        {"node": {"id": 10}, "relation_type": "spin_off"},
        {"node": {"id": 20}, "relation_type": "character"},
        {"node": {"id": 30}, "relation_type": "sequel"},
    ]
    edges = parse_relation_edges(related)

    assert (10, "spin-off") in edges
    assert (30, "sequel") in edges
    assert all(target != 20 for target, _rel in edges)


@pytest.mark.asyncio
async def test_client_follows_redirects():
    """MAL v2 intermittently answers a valid `/anime/{id}` with a 307; httpx
    defaults to NOT following redirects and `raise_for_status()` then treats
    the 3xx as an error, so the client must be created with
    follow_redirects=True (a live sweep surfaced ~1-2% step-1 failures without
    it). Guards against a regression that drops the flag."""
    async with MalScraper() as scraper:
        assert scraper.client.follow_redirects is True


DURATION_EXPECTED_PAIRS = [
    # Check different string format:
    ("24 min per ep", 24 * 60),

    # Check different time intervals:
    ("4 hr 17 min 2 sec", 4 * 3600 + 17 * 60 + 2),

    ("1 hr 36 min", 3600 + 36 * 60),
    ("1 hr 10 sec", 3600 + 10),
    ("42 min 2 sec", 42 * 60 + 2),

    ("2 hr", 2 * 3600),
    ("23 min", 23 * 60),
    ("43 sec", 43),

    # Containing 0:
    ("0 sec", None),
    ("0 min", None),
    ("0 hr", None),
    ("0 hr 0 min 0 sec", None),
    ("2 hr 0 min", 2 * 3600),

    # Edge cases:
    ("Unknown", None),
    ("unknown", None),
    ("", None),
    (None, None),
    ("-1 hr 12 min", 3600 + 12 * 60), # Signs are ignored
    ("1hr 12 min", 3600 + 12 * 60), # Spaces are ignored
    ("1  hr 12 min", 3600 + 12 * 60), # Spaces are ignored
    ("hr 12 min", 12 * 60), # Fragments are ignored
    ("hr 12", None), # Bad formatted string
]

@pytest.mark.parametrize("duration_str, expected_seconds", DURATION_EXPECTED_PAIRS)
def test_parse_duration_to_seconds_exact(duration_str, expected_seconds):
    # MAL v2 ships average_episode_duration as an int, so production no
    # longer parses a duration string. The parser moved into the test
    # builders (it converts the human `duration=` keyword into the MAL
    # field); this exercises that helper directly.
    result = _duration_to_seconds(duration_str)
    assert result == expected_seconds, f"For '{duration_str}', expected {expected_seconds} but got {result}"


SYNOPSIS_CLEAN_PAIRS = [
    # No tags — unchanged.
    ("Two pilots fight in giant robots.", "Two pilots fight in giant robots."),
    # Single trailing credit tag.
    ("Plot.\n\n[Written by MAL Rewrite]", "Plot."),
    ("Plot.\n[Source: AniDB]", "Plot."),
    ("Plot. [Source: Anime News Network]", "Plot."),
    # Stacked trailing tags.
    ("Plot.\n\n[Source: AniDB]\n\n[Written by MAL Rewrite]", "Plot."),
    # Case-insensitive.
    ("Plot. [SOURCE: ANIDB]", "Plot."),
    # Mid-text tag stays — only trailing tags are credit tags.
    ("Plot [as cited in Source: A] continues.", "Plot [as cited in Source: A] continues."),
    # Non-credit bracketed content at the end is kept (avoid being too greedy).
    ("Plot ends here. [TV spoiler warning]", "Plot ends here. [TV spoiler warning]"),
    # Empty / None passthrough.
    (None, None),
    ("", ""),
    # Only-credit content collapses to None so the column stays clean.
    ("[Written by MAL Rewrite]", None),
    ("   [Source: AniDB]   ", None),
]


@pytest.mark.parametrize("raw, expected", SYNOPSIS_CLEAN_PAIRS)
def test_clean_synopsis(raw, expected):
    assert MalScraper._clean_synopsis(raw) == expected


@pytest.mark.asyncio
async def test_rate_limiter_spaces_consecutive_requests(monkeypatch):
    """Two back-to-back calls must be spaced at least _MIN_REQUEST_INTERVAL_S
    apart. Without this, a 200-anime sweep would burst hundreds of
    requests into MAL as fast as TCP allows."""
    from time import monotonic

    # Override to a small value so the test stays fast but still proves
    # spacing — the production constant doesn't need to be exercised.
    monkeypatch.setattr(MalScraper, "_MIN_REQUEST_INTERVAL_S", 0.05)
    MalScraper._last_request_at = 0.0

    t0 = monotonic()
    await MalScraper._wait_for_rate_limit()
    await MalScraper._wait_for_rate_limit()
    elapsed = monotonic() - t0

    assert elapsed >= 0.045  # 5% margin under the configured 50ms gap


@pytest.mark.asyncio
async def test_get_does_not_retry_4xx(monkeypatch):
    """A 404 (or any 4xx) is deterministic — retrying wastes 31s of
    exponential backoff before failing the same way. The httpx.AsyncClient
    mock must see exactly one request."""
    import httpx

    monkeypatch.setattr(MalScraper, "_MIN_REQUEST_INTERVAL_S", 0.0)

    call_count = 0

    async def fake_get(self, url, params=None):
        nonlocal call_count
        call_count += 1
        request = httpx.Request("GET", url)
        return httpx.Response(404, request=request, content=b'{"detail": "not found"}')

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with MalScraper() as scraper:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await scraper._get("https://api.myanimelist.net/v2/anime")

    assert call_count == 1
    assert exc_info.value.response.status_code == 404


@pytest.mark.asyncio
async def test_get_retries_429_with_tighter_cap(monkeypatch):
    """429 IS retried (special-cased in _is_transient_mal_error), but
    capped at 3 total attempts by _stop_strategy — strictly fewer than
    the 5 attempts for 5xx/timeout/network. The tight cap is
    deliberate: 2 retries bridge a brief per-minute-window overrun;
    beyond that, retrying just masks sustained throttling and the
    right response is to slow the source rate.

    This test exercises the production _stop_strategy directly (no
    monkeypatch override on stop) — that's the load-bearing
    invariant. Wait is zeroed so the test isn't 30s long."""
    import httpx

    monkeypatch.setattr(MalScraper, "_MIN_REQUEST_INTERVAL_S", 0.0)
    # Zero out wait but DO NOT touch stop — we want to verify the
    # production stop_strategy enforces the 3-attempt cap for 429.
    from tenacity import wait_fixed
    monkeypatch.setattr(MalScraper._get.retry, "wait", wait_fixed(0))

    call_count = 0

    async def fake_get(self, url, params=None):
        nonlocal call_count
        call_count += 1
        request = httpx.Request("GET", url)
        return httpx.Response(429, request=request, content=b"rate limited")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with MalScraper() as scraper:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await scraper._get("https://api.myanimelist.net/v2/anime")

    # 1 initial + 2 retries = 3 total attempts for 429.
    assert call_count == 3
    assert exc_info.value.response.status_code == 429


@pytest.mark.asyncio
async def test_fetch_current_season_paginates(monkeypatch):
    """MAL v2's /anime/season/{year}/{season} is offset-paginated. The
    loop must keep requesting pages while `paging.next` is present and
    concatenate every page's `data[].node` into `[{mal_id, title}]`. The
    offset query parameter advances by `limit` per iteration."""
    calls: list[dict | None] = []

    async def fake_get(self, url, params=None):
        assert "/anime/season/" in url
        calls.append(params)
        offset = (params or {}).get("offset", 0)
        if offset == 0:
            return {
                "data": [
                    {"node": {"id": 1, "title": "Show A"}},
                    {"node": {"id": 2, "title": "Show B"}},
                ],
                "paging": {"next": "https://api.myanimelist.net/v2/anime/season/2020/spring?offset=100"},
            }
        return {
            "data": [{"node": {"id": 3, "title": "Show C"}}],
            "paging": {},  # no `next` → last page
        }

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        entries = await scraper.fetch_current_season()

    assert [e["mal_id"] for e in entries] == [1, 2, 3]
    assert [e["title"] for e in entries] == ["Show A", "Show B", "Show C"]
    assert [c.get("offset") for c in calls] == [0, 100]


@pytest.mark.asyncio
async def test_fetch_current_season_empty(monkeypatch):
    """An empty season (off-week between cycles, or test against a fresh
    DB) returns no entries without crashing. Single page, no follow-up."""
    call_count = 0

    async def fake_get(self, url, params=None):
        nonlocal call_count
        call_count += 1
        return {"data": [], "paging": {}}

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        entries = await scraper.fetch_current_season()

    assert entries == []
    assert call_count == 1


@pytest.mark.asyncio
async def test_get_retries_5xx_with_full_budget(monkeypatch):
    """The asymmetric retry budget: 5xx gets 5 total attempts (4
    retries), strictly more than 429's 3-attempt cap. Pins the
    invariant so a future refactor can't quietly flatten both back to
    the same budget. Wait is zeroed so the test isn't 30s long; stop
    is left at the production _stop_strategy."""
    import httpx

    monkeypatch.setattr(MalScraper, "_MIN_REQUEST_INTERVAL_S", 0.0)
    from tenacity import wait_fixed
    monkeypatch.setattr(MalScraper._get.retry, "wait", wait_fixed(0))

    call_count = 0

    async def fake_get(self, url, params=None):
        nonlocal call_count
        call_count += 1
        request = httpx.Request("GET", url)
        return httpx.Response(503, request=request, content=b"service unavailable")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with MalScraper() as scraper:
        with pytest.raises(httpx.HTTPStatusError):
            await scraper._get("https://api.myanimelist.net/v2/anime")

    assert call_count == 5  # 1 initial + 4 retries; strictly > 429's 3


@pytest.mark.asyncio
async def test_get_retries_5xx_and_surfaces_underlying_error(monkeypatch):
    """5xx IS transient — tenacity retries to the cap (5 attempts), then
    reraise=True surfaces the underlying HTTPStatusError instead of
    wrapping it in tenacity's RetryError. The bell's result_summary
    gets the human-readable upstream message, not `RetryError[<Future at 0x...>]`."""
    import httpx

    monkeypatch.setattr(MalScraper, "_MIN_REQUEST_INTERVAL_S", 0.0)
    # Tighten the backoff so the test isn't 31s long.
    from tenacity import stop_after_attempt, wait_fixed
    monkeypatch.setattr(MalScraper._get.retry, "stop", stop_after_attempt(3))
    monkeypatch.setattr(MalScraper._get.retry, "wait", wait_fixed(0))

    call_count = 0

    async def fake_get(self, url, params=None):
        nonlocal call_count
        call_count += 1
        request = httpx.Request("GET", url)
        return httpx.Response(504, request=request, content=b"gateway timeout")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with MalScraper() as scraper:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await scraper._get("https://api.myanimelist.net/v2/anime")

    assert call_count == 3
    assert exc_info.value.response.status_code == 504


# Cross-franchise contamination boundary tests (v0.14.2). Rationale in
# compound-docs/2026-05-11-jikan-scraper-quirks.md (v0.14.2 notes).


@pytest.mark.asyncio
async def test_search_title_overlord_pleiades_x_kagejitsu_does_not_bridge_to_eminence(monkeypatch):
    """Production regression. Scraping Overlord must NOT pull in The Eminence
    in Shadow.

    Trace (real MAL data, see scripts/inspect_anime_relations.py output):

        Overlord (29803, Main, WALK)
          → side_story → Ple Ple Pleiades (31138, TERMINAL)
                            → other → Ple Ple Pleiades x Kagejitsu! (57034)
                                        → other → Kagejitsu! Second (56842)
                                                    → sequel → Kage no Jitsuryokusha 2nd (54595)
                                                                → sequel → Kage no Jitsuryokusha S1 (48316)

    Pleiades arrives via `side_story` from Overlord's Main → demoted to
    TERMINAL. TERMINAL nodes capture their outgoing edges in the persisted
    list (so split-detection can see e.g. Vigilante's sequel chain
    leaking out of BNHA's row) but the BFS does NOT recurse from them —
    57034's detail is never fetched, and 56842, 54595, 48316 stay out of
    the graph entirely. Pleiades's detail IS fetched (so its outgoing
    `other` edge to 57034 is recorded), but 57034 onward are not.

    Production observation that drove the strict (vs. one-hop) state
    machine: a direct Main(Eva) → other → Main(Ultraman) edge under one-hop
    would have pulled Ultraman's full sequel chain into Eva. Under strict,
    only Ultraman's Main node leaks as a single TERMINAL — the user can
    surface that as a merge candidate without splitting a hundred sequels
    out manually.
    """
    detail_calls: list[int] = []

    relations_by_id = {
        29803: [(31138, "Side Story")],
        31138: [(57034, "Other")],   # Must never be walked past.
        57034: [(56842, "Other")],
        56842: [(54595, "Sequel")],
        54595: [(48316, "Prequel")],
        48316: [],
    }
    title_by_id = {
        29803: "Overlord",
        31138: "Overlord: Ple Ple Pleiades",
        57034: "Ple Ple Pleiades x Kagejitsu!",
        56842: "Kagejitsu! Second",
        54595: "Kage no Jitsuryokusha ni Naritakute! 2nd Season",
        48316: "Kage no Jitsuryokusha ni Naritakute!",
    }

    async def fake_get(self, url, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _make_anime(
                29803, "Overlord", related_anime=_related(*relations_by_id[29803]),
            )}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            detail_calls.append(mal_id)
            return _make_anime(
                mal_id, title_by_id[mal_id],
                related_anime=_related(*relations_by_id[mal_id]),
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Overlord", excluded_mal_ids=set(),
        )

    graph, edges, _cross_links = relations[0]

    # Pleiades (TERMINAL via side_story from Overlord's Main) IS in graph.
    assert 31138 in graph, "Pleiades (side_story of Overlord) must be in graph"

    # Everything beyond the TERMINAL boundary is out: the collab and the
    # full Eminence chain.
    bridge_and_eminence = {57034, 56842, 54595, 48316}
    assert bridge_and_eminence.isdisjoint(graph.keys()), (
        f"Nodes beyond the TERMINAL boundary leaked into Overlord: "
        f"{bridge_and_eminence & graph.keys()}"
    )

    # Pleiades's detail IS fetched (TERMINAL captures outgoing edges so
    # split-detection has the data), but the Eminence chain stays out:
    # 57034 onward are never queued because Pleiades is TERMINAL and the
    # for-loop skips queuing its targets.
    assert 31138 in detail_calls, (
        "Pleiades is TERMINAL — its detail IS fetched for sidecar edges"
    )
    for mal_id in (57034, 56842, 54595, 48316):
        assert mal_id not in detail_calls, (
            f"detail({mal_id}) was fetched — BFS crossed the boundary"
        )

    # Edge persistence: Overlord (WALK) → Pleiades + Pleiades (TERMINAL)
    # → 57034 are both in the persisted list. Edges from 57034 onward are
    # NOT — those nodes were never processed by the BFS at all.
    edge_set = {(a, b, r) for a, b, r in edges}
    assert (29803, 31138, "side_story") in edge_set
    assert (31138, 57034, "other") in edge_set, (
        "Pleiades's outgoing edge to 57034 must be captured for split-detection"
    )
    assert not any(a in {57034, 56842, 54595, 48316} for a, _, _ in edges), (
        "Nodes beyond TERMINAL must have no edges in the persisted list"
    )


@pytest.mark.parametrize(
    "rel_label,rel_normalized",
    [
        ("Side Story", "side_story"),
        ("Summary", "summary"),
        ("Other", "other"),
        ("Spin-off", "spin-off"),
    ],
)
@pytest.mark.asyncio
async def test_search_title_identity_breaking_relation_makes_target_terminal(
    monkeypatch, rel_label, rel_normalized,
):
    """The "pure" identity-breaking relations demote the target to TERMINAL
    in the main BFS AND are not walked by anchor discovery:
    root (WALK) → rel → A (TERMINAL). A is recorded in the graph and ITS
    outgoing edges are captured for sidecar persistence (so split-
    detection can later see whether A has its own franchise chain), but
    the BFS does NOT recurse from A — A's sequel targets B and C never
    enter the graph.

    `parent_story` and `full_story` are NOT in this list — they're walked
    by anchor discovery (target IS the canonical ancestor).

    This is the strict boundary the pre-v0.14.0 BFS enforced; v0.14.1's
    two-pass classifier doesn't need the deeper graph for correct
    classification, so we restore the tight membership and prevent
    cross-franchise contamination.
    """
    detail_calls: list[int] = []

    relations_by_id = {
        1: [(2, rel_label)],
        2: [(3, "Sequel")],
        3: [(4, "Sequel")],
        4: [],
    }

    async def fake_get(self, url, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _make_anime(
                1, "Root", related_anime=_related(*relations_by_id[1]),
            )}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            detail_calls.append(mal_id)
            return _make_anime(
                mal_id, f"Anime {mal_id}",
                related_anime=_related(*relations_by_id.get(mal_id, [])),
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Root", excluded_mal_ids=set(),
        )

    graph, edges, _ = relations[0]

    # Root walked normally and recorded the edge to A.
    assert 1 in graph
    # A is in the graph (info recorded) AND its detail IS fetched —
    # TERMINAL nodes capture outgoing edges for sidecar persistence so
    # split-detection can later see A's franchise chain. The boundary
    # holds at A's targets: the BFS does NOT queue them.
    assert 2 in graph, (
        f"A (queued via {rel_normalized}) must be in graph as TERMINAL"
    )
    assert 2 in detail_calls, (
        "A's detail must be fetched — TERMINAL captures outgoing "
        "edges for sidecar persistence, even though BFS doesn't recurse"
    )
    # Therefore B (A's sequel) and C (B's sequel) are unreachable — the
    # BFS never queues them, never fetches their detail.
    assert 3 not in graph
    assert 4 not in graph
    assert 3 not in detail_calls
    assert 4 not in detail_calls

    # Edge data-shape: root's outgoing edge to A IS recorded AND A's
    # outgoing edge to B is recorded (TERMINAL captures edges). B's
    # outgoing edges are NOT recorded — B was never visited.
    edge_set = {(a, b, r) for a, b, r in edges}
    assert (1, 2, rel_normalized) in edge_set
    assert (2, 3, "sequel") in edge_set, (
        "TERMINAL node A's outgoing sequel edge to B must be captured "
        "so split-detection can later see A's franchise chain"
    )
    assert not any(a == 3 for a, _, _ in edges), (
        "B was never visited — no outgoing edges captured for it"
    )


@pytest.mark.asyncio
async def test_search_title_terminal_captures_sequel_chain_for_split_detection(monkeypatch):
    """Production case for the split-detection data dependency: scraping
    BNHA must capture Vigilante S1's outgoing sequel edge to Vigilante S2
    in the persisted edges list — so split-detection can later see the
    "this side_story has its own franchise chain" signal — WITHOUT pulling
    Vigilante S2 into BNHA's anime row.

    Fixture mirrors the real MAL relations (per dev DB inspect):
        BNHA S1 (31964, TV, Main, WALK)
          → sequel → BNHA S2 (33486, TV, WALK)
          → spin-off → Vigilante S1 (60593, TV, TERMINAL)
                         → sequel → Vigilante S2 (61942, TV, would-be-WALK
                                                     except parent is TERMINAL)

    Under the v0.14.2 split-candidates TERMINAL semantics:
    - Vigilante S1 IS in the graph.
    - Vigilante S1's detail IS fetched (so the (60593, 61942, "sequel")
      edge lands in the persisted list).
    - Vigilante S2 is NOT in the graph (TERMINAL doesn't queue its targets).
    - Vigilante S2's detail is NEVER fetched.
    - Split-detection downstream sees the sequel edge in the sidecar and
      flags the Vigilante cluster for admin review.
    """
    detail_calls: list[int] = []

    relations_by_id = {
        31964: [(33486, "Sequel"), (60593, "Spin-off")],
        33486: [(31964, "Prequel")],
        60593: [(61942, "Sequel")],
        61942: [(60593, "Prequel")],
    }
    title_by_id = {
        31964: "Boku no Hero Academia",
        33486: "Boku no Hero Academia 2nd Season",
        60593: "Vigilante: Boku no Hero Academia Illegals",
        61942: "Vigilante: Boku no Hero Academia Illegals 2nd Season",
    }

    async def fake_get(self, url, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _make_anime(
                31964, "Boku no Hero Academia",
                related_anime=_related(*relations_by_id[31964]),
            )}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            detail_calls.append(mal_id)
            return _make_anime(
                mal_id, title_by_id[mal_id],
                related_anime=_related(*relations_by_id.get(mal_id, [])),
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Boku no Hero Academia", excluded_mal_ids=set(),
        )

    graph, edges, _ = relations[0]

    # Graph membership: BNHA chain + Vigilante S1 (TERMINAL). Vigilante S2 is
    # OUT — the contamination boundary held.
    assert {31964, 33486, 60593} <= set(graph.keys())
    assert 61942 not in graph, (
        "Vigilante S2 leaked into BNHA's anime — TERMINAL must not queue targets"
    )

    # Vigilante S1's detail IS fetched (TERMINAL captures outgoing
    # edges) but Vigilante S2's is NOT (never queued).
    assert 60593 in detail_calls, (
        "Vigilante S1 is TERMINAL — its detail must be fetched so the "
        "sequel edge to S2 lands in the persisted edge list for split-detection"
    )
    assert 61942 not in detail_calls

    # The bridge edge for split-detection: Vigilante S1 → S2 (sequel) is in
    # the persisted edges. This is what split-detection looks for: a
    # substance-passing TERMINAL with its own sequel chain to another
    # substance-passing media not in the anchor's main chain.
    edge_set = {(a, b, r) for a, b, r in edges}
    assert (31964, 60593, "spin-off") in edge_set  # BNHA → Vigilante
    assert (60593, 61942, "sequel") in edge_set, (
        "The Vigilante S1 → S2 sequel edge MUST be captured — without it, "
        "split-detection can't see Vigilante is its own franchise"
    )


@pytest.mark.parametrize(
    "rel_label,rel_normalized",
    [
        ("Sequel", "sequel"),
        ("Alternative version", "alternative_version"),
    ],
)
@pytest.mark.asyncio
async def test_search_title_identity_preserving_relations_walk_through(
    monkeypatch, rel_label, rel_normalized,
):
    """Identity-preserving relations (sequel, prequel, alternative_version)
    keep nodes in WALK status — the full chain is traversed.

    Locks in the alt-version-as-structural decision: the Eva Rebuild chain
    (TV → alt-version → Movie 1 → sequel → Movie 2 → sequel → Movie 3 → ...)
    depends on full closure through alt-version edges; demoting them would
    orphan downstream Rebuild Movies. See [relation_classifier.py:225-236].
    """
    detail_calls: list[int] = []
    chain = {1: [(2, rel_label)], 2: [(3, rel_label)], 3: [(4, rel_label)], 4: []}

    async def fake_get(self, url, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _make_anime(
                1, "Root", related_anime=_related(*chain[1]),
            )}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            detail_calls.append(mal_id)
            return _make_anime(
                mal_id, f"Anime {mal_id}", related_anime=_related(*chain.get(mal_id, [])),
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Root", excluded_mal_ids=set(),
        )

    graph, edges, _ = relations[0]
    # Full chain walked.
    assert set(graph.keys()) == {1, 2, 3, 4}
    # Every non-root node's detail fetched — proves WALK propagated through
    # the whole chain (a TERMINAL break would have stopped the fetches).
    # Root (1) comes from the search response, so it never hits detail.
    assert set(detail_calls) == {2, 3, 4}
    # Normalized edge labels persisted.
    edge_set = {(a, b, r) for a, b, r in edges}
    assert (1, 2, rel_normalized) in edge_set
    assert (2, 3, rel_normalized) in edge_set
    assert (3, 4, rel_normalized) in edge_set


@pytest.mark.asyncio
async def test_search_title_status_promoted_when_two_edges_from_same_walker(monkeypatch):
    """When the same target is reachable via both identity-breaking AND
    identity-preserving edges from the same source, the most-permissive
    status (WALK) wins.

    Setup:
        root → Side Story → X     (would mark X as TERMINAL)
        root → Sequel → X         (marks X as WALK)

    Result: X is WALK, X's detail is fetched, X's sequel Y is queued and
    fetched (WALK). Without promotion, X stays TERMINAL, Y is never
    reached — caught by the assertion that Y IS fetched.
    """
    detail_calls: list[int] = []
    relations_by_id = {
        # X (2) reached via BOTH side_story AND sequel from root.
        1: [(2, "Side Story"), (2, "Sequel")],
        2: [(3, "Sequel")],
        3: [(4, "Sequel")],
        4: [],
    }

    async def fake_get(self, url, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _make_anime(
                1, "Root", related_anime=_related(*relations_by_id[1]),
            )}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            detail_calls.append(mal_id)
            return _make_anime(
                mal_id, f"Anime {mal_id}",
                related_anime=_related(*relations_by_id.get(mal_id, [])),
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Root", excluded_mal_ids=set(),
        )

    graph, _, _ = relations[0]
    # X (2) was promoted to WALK by the sequel edge → its detail fetched
    # → its sequel target (3) is WALK → 3's detail fetched → 4 reached.
    assert {1, 2, 3, 4}.issubset(set(graph.keys())), (
        "X must be WALK (promoted by sequel edge), so its sequel chain is walked"
    )
    assert 2 in detail_calls
    assert 3 in detail_calls
    assert 4 in detail_calls


@pytest.mark.asyncio
async def test_search_title_no_cross_link_to_deep_other_chain_target(monkeypatch):
    """A catalog member sitting behind a chain of identity-breaking edges from
    the seed is NOT reached by the BFS (TERMINAL truncates), so it does NOT
    surface as a cross_link.

    Codifies the cost-asymmetry tradeoff: a deep-chain catalog hit doesn't
    spam merge candidates. The merge-candidate detector sees ONLY direct
    cross-links from WALK nodes, never from TERMINAL boundaries.
    """
    deep_catalog_id = 999
    relations_by_id = {
        1: [(2, "Side Story")],          # 2: TERMINAL (side_story)
        2: [(3, "Other")],               # 3: never queued (2 is TERMINAL)
        3: [(deep_catalog_id, "Sequel")],  # never fetched
    }

    async def fake_get(self, url, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _make_anime(
                1, "Root", related_anime=_related(*relations_by_id[1]),
            )}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return _make_anime(
                mal_id, f"Anime {mal_id}",
                related_anime=_related(*relations_by_id.get(mal_id, [])),
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Root", excluded_mal_ids={deep_catalog_id},
        )

    graph, _, cross_link_mal_ids = relations[0]
    # Deep catalog member is unreachable through the TERMINAL boundary.
    assert deep_catalog_id not in graph
    assert deep_catalog_id not in cross_link_mal_ids
    assert cross_link_mal_ids == set(), (
        f"Deep-chain catalog target leaked into cross_link_mal_ids: {cross_link_mal_ids}"
    )


# Anchor discovery + entry-point invariance tests. Rationale in
# compound-docs/2026-05-11-jikan-scraper-quirks.md (v0.14.2 split-candidates notes).


def _overlord_relations_fixture() -> dict:
    """Real Overlord franchise relations from production MAL data, plus
    Pleiades x Kagejitsu bridge → small Eminence sub-fixture so we can
    assert cross-franchise non-leak under different entry points.
    """
    return {
        # Main chain
        29803: {"type": "TV", "title": "Overlord", "rels": [
            (35073, "Sequel"), (37264, "Side Story"), (31138, "Side Story"),
            (33372, "Side Story"), (38693, "Side Story"),
            (34161, "Summary"), (34428, "Summary"),
            (36683, "Other"), (36497, "Other"),
        ]},
        35073: {"type": "TV", "title": "Overlord II", "rels": [
            (29803, "Prequel"), (37675, "Sequel"), (37087, "Other"),
        ]},
        37675: {"type": "TV", "title": "Overlord III", "rels": [
            (35073, "Prequel"), (48895, "Sequel"), (37781, "Other"),
        ]},
        48895: {"type": "TV", "title": "Overlord IV", "rels": [
            (37675, "Prequel"), (48896, "Side Story"), (48897, "Other"),
        ]},
        # Side stories with parent_story → S1 (anchor discovery walks these)
        31138: {"type": "Special", "title": "Ple Ple Pleiades", "rels": [
            (33372, "Sequel"), (37087, "Sequel"),
            (29803, "Parent story"),
            (36497, "Other"), (38693, "Other"),
            (57034, "Other"),  # ← bridge to Eminence
        ]},
        33372: {"type": "OVA", "title": "Pleiades OVA", "rels": [
            (31138, "Prequel"), (29803, "Parent story"),
        ]},
        37087: {"type": "ONA", "title": "Pleiades 2", "rels": [
            (31138, "Prequel"), (37781, "Sequel"), (35073, "Parent story"),
        ]},
        37781: {"type": "ONA", "title": "Pleiades 3", "rels": [
            (37087, "Prequel"), (48897, "Sequel"), (37675, "Parent story"),
        ]},
        48897: {"type": "ONA", "title": "Pleiades 4", "rels": [
            (37781, "Prequel"), (48895, "Other"),
        ]},
        38693: {"type": "ONA", "title": "Pleiades Clementine", "rels": [
            (29803, "Parent story"), (31138, "Other"),
        ]},
        37264: {"type": "ONA", "title": "Overlord Drama CD", "rels": [
            (29803, "Parent story"),
        ]},
        # Summary movies (full_story → S1)
        34161: {"type": "Movie", "title": "Overlord Movie 1", "rels": [
            (34428, "Sequel"), (29803, "Full story"),
            (36683, "Other"), (36497, "Other"),
        ]},
        34428: {"type": "Movie", "title": "Overlord Movie 2", "rels": [
            (34161, "Prequel"), (29803, "Full story"), (36497, "Other"),
        ]},
        # Pleiades / Manner Movies (only `other` outgoing — no upward path)
        36497: {"type": "Movie", "title": "Pleiades Movie", "rels": [
            (29803, "Other"), (31138, "Other"), (34161, "Other"), (34428, "Other"),
        ]},
        36683: {"type": "Movie", "title": "Manner Movie", "rels": [
            (34161, "Other"), (34428, "Other"),
        ]},
        # S4 side-stories
        48896: {"type": "Movie", "title": "Movie 3 Sei Oukoku-hen", "rels": [
            (48895, "Parent story"), (61345, "Other"),
        ]},
        61345: {"type": "Movie", "title": "Sei Oukoku-hen Manner Movie", "rels": [
            (48896, "Other"),
        ]},
        # Pleiades x Kagejitsu collab — the cross-franchise bridge
        57034: {"type": "ONA", "title": "Ple Ple Pleiades x Kagejitsu!", "rels": [
            (31138, "Other"), (56842, "Other"),
        ]},
        # Eminence side
        56842: {"type": "ONA", "title": "Kagejitsu! Second", "rels": [
            (53406, "Prequel"), (54595, "Parent story"), (57034, "Other"),
        ]},
        54595: {"type": "TV", "title": "Kage no Jitsuryokusha 2nd", "rels": [
            (48316, "Prequel"), (57584, "Sequel"), (56842, "Other"),
        ]},
        48316: {"type": "TV", "title": "Kage no Jitsuryokusha", "rels": [
            (54595, "Sequel"), (53406, "Other"),
        ]},
        53406: {"type": "ONA", "title": "Kagejitsu!", "rels": [
            (56842, "Sequel"), (48316, "Parent story"),
        ]},
        57584: {"type": "Movie", "title": "Kage no Jitsuryokusha Movie", "rels": [
            (54595, "Prequel"),
        ]},
    }


def _make_fake_mal(fixture: dict, search_result_ids: list[int]):
    """Build a fake `_get` coroutine driven by `fixture` + a list of mal_ids
    that MAL's `/anime?q=...` search returns. Returns `(fake_get, state)`
    where `state` exposes lists of mal_ids hit on each MAL detail path.

    In MAL v2 both `search_by_malid` and `fetch_relations` hit the same
    `/anime/{id}` detail endpoint; they differ only by the `fields` param.
    `fetch_relations` requests `fields=id,related_anime`, so we split the
    tracking on that: `fetched_relations` = fetch_relations calls (anchor
    discovery + BFS fallback), `fetched_by_malid` = full-detail calls
    (search_by_malid for anchors + non-root BFS nodes)."""
    state = {
        "fetched_relations": [],
        "fetched_by_malid": [],
    }

    def _obj(mal_id: int) -> dict:
        entry = fixture.get(mal_id)
        if entry is None:
            return _make_anime(mal_id, f"Anime {mal_id}")
        return _make_anime(
            mal_id, entry["title"], media_type=entry["type"],
            related_anime=_related(*entry.get("rels", [])),
        )

    async def fake_get(self, url, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [{"node": _obj(mal_id)} for mal_id in search_result_ids]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            fields = (params or {}).get("fields", "")
            if fields == "id,related_anime":
                state["fetched_relations"].append(mal_id)
            else:
                state["fetched_by_malid"].append(mal_id)
            return _obj(mal_id)
        raise AssertionError(f"Unexpected URL: {url}")

    return fake_get, state


_OVERLORD_MAIN_CHAIN = {29803, 35073, 37675, 48895}
_EMINENCE_MAL_IDS = {48316, 53406, 54595, 56842, 57584}


@pytest.mark.parametrize(
    "search_result_ids,case_label",
    [
        ([29803], "S1 root"),
        ([35073], "S2 root (prequel → S1)"),
        ([37675], "S3 root (prequel chain → S1)"),
        ([48895], "S4 root (prequel chain → S1)"),
        ([34161], "Movie 1 root (full_story → S1)"),
        ([34428], "Movie 2 root (prequel → Movie 1 → full_story → S1)"),
        ([31138], "Pleiades 1 root (parent_story → S1)"),
        ([29803, 48895], "S1 + S4 (both anchor at S1)"),
        ([61345, 34161, 34428], "the real q=overlor case"),
    ],
)
@pytest.mark.asyncio
async def test_search_title_overlord_entry_point_invariance(monkeypatch, search_result_ids, case_label):
    """Same Overlord franchise produces the same Main-chain regardless of
    which mal_id MAL's fuzzy search returns. Anchor discovery walks
    structural-upward relations from each search root, finds the
    canonical S1 (29803), and prepends it as an additional root so the
    main BFS walks the full sequel chain.

    Eminence (reachable only via `other` from Pleiades × Kagejitsu) must
    not leak in under any entry point — Phase 1's strict bound holds
    through the main BFS even after anchor discovery adds roots.
    """
    fixture = _overlord_relations_fixture()
    fake_get, _state = _make_fake_mal(fixture, search_result_ids)
    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Overlord", excluded_mal_ids=set(),
        )

    all_mal_ids: set[int] = set()
    for graph, _edges, _cl in relations:
        all_mal_ids.update(graph.keys())

    # Full Overlord main chain is reachable from every parameterised entry.
    missing = _OVERLORD_MAIN_CHAIN - all_mal_ids
    assert not missing, (
        f"[{case_label}] Missing main chain members: {missing} "
        f"(got {sorted(all_mal_ids)})"
    )

    # Eminence stays out — cross-franchise invariant from Phase 1.
    eminence_leak = _EMINENCE_MAL_IDS & all_mal_ids
    assert not eminence_leak, (
        f"[{case_label}] Eminence leaked into Overlord: {eminence_leak}"
    )


@pytest.mark.asyncio
async def test_search_title_overlord_manner_movie_only_entry_stays_isolated(monkeypatch):
    """When the ONLY search root is a deep `other`-connected node
    (Sei Oukoku-hen Manner Movie 61345) with no structural-upward edges,
    anchor discovery cannot find the canonical Main. The franchise is
    unreachable from this entry point.

    This is the explicit "user has to make a more precise query" tradeoff
    locked in as expected behavior — we prefer incompleteness over silent
    cross-franchise merging.
    """
    fixture = _overlord_relations_fixture()
    fake_get, _ = _make_fake_mal(fixture, [61345])
    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Manner Movie", excluded_mal_ids=set(),
        )

    all_mal_ids: set[int] = set()
    for graph, _edges, _cl in relations:
        all_mal_ids.update(graph.keys())

    # Overlord main chain NOT reached (no upward edges from 61345).
    assert not _OVERLORD_MAIN_CHAIN.issubset(all_mal_ids), (
        f"Expected Overlord main chain to be unreachable from [61345] only; "
        f"got {sorted(all_mal_ids)}"
    )
    # Eminence stays out too (no `other` chain followed).
    assert _EMINENCE_MAL_IDS.isdisjoint(all_mal_ids)


@pytest.mark.parametrize(
    "search_root,other_franchise_secondary",
    [
        (30, 5001),     # search Eva → Ultraman S2 must stay out
        (5000, 32),     # search Ultraman → Eva End-of-Eva must stay out
    ],
)
@pytest.mark.asyncio
async def test_search_title_anchor_discovery_does_not_cross_other_franchise(
    monkeypatch, search_root, other_franchise_secondary,
):
    """Anchor discovery walks only structural-upward relations; `other`
    is NOT in that set. So scraping from one franchise via a node connected
    to another franchise only via `other` (Evangelion ↔ Ultraman) must
    NOT pull the other franchise's secondary chain in.

    The other-franchise Main may appear as a single TERMINAL leak via the
    `other` edge in the main BFS (existing Phase 1 cost-asymmetry behavior)
    — we don't assert on that. We assert the SECONDARY chain is unreachable.
    """
    fixture = {
        30: {"type": "TV", "title": "Evangelion", "rels": [
            (32, "Sequel"), (5000, "Other"),
        ]},
        32: {"type": "Movie", "title": "End of Eva", "rels": [
            (30, "Prequel"),
        ]},
        5000: {"type": "TV", "title": "Ultraman", "rels": [
            (5001, "Sequel"), (30, "Other"),
        ]},
        5001: {"type": "TV", "title": "Ultraman S2", "rels": [
            (5000, "Prequel"),
        ]},
    }
    fake_get, _ = _make_fake_mal(fixture, [search_root])
    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="X", excluded_mal_ids=set(),
        )

    all_mal_ids: set[int] = set()
    for graph, _edges, _cl in relations:
        all_mal_ids.update(graph.keys())

    assert other_franchise_secondary not in all_mal_ids, (
        f"Other franchise's secondary chain leaked from search root "
        f"{search_root}: got {sorted(all_mal_ids)}"
    )


@pytest.mark.asyncio
async def test_search_title_anchor_discovery_stops_at_catalog(monkeypatch):
    """When the upward walk reaches an `excluded_ids` (catalog) mal_id,
    discovery stops — does NOT promote that mal_id as a new BFS root.
    The main BFS then surfaces it as a cross_link so save_service routes
    new media via attach-action under the existing anime.
    """
    fixture = _overlord_relations_fixture()
    # Pretend S1 is already in catalog.
    excluded = {29803}
    fake_get, state = _make_fake_mal(fixture, [34161])
    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Overlord Movie 1", excluded_mal_ids=excluded,
        )

    all_mal_ids: set[int] = set()
    cross_links: set[int] = set()
    for graph, _edges, cl in relations:
        all_mal_ids.update(graph.keys())
        cross_links.update(cl)

    # 29803 NOT in graph (excluded → main BFS treats it as cross-link).
    assert 29803 not in all_mal_ids
    # 29803 IS surfaced as cross-link for save_service's attach routing.
    assert 29803 in cross_links
    # Anchor discovery did NOT fetch 29803 via search_by_malid (would have
    # if discovery had promoted it as a new anchor root).
    assert 29803 not in state["fetched_by_malid"]


@pytest.mark.asyncio
async def test_search_title_anchor_discovery_caches_relations(monkeypatch):
    """The relation cache eliminates duplicate `fetch_relations` fetches
    between anchor discovery and the main BFS. Each upward-walked node is
    fetched at most once."""
    fixture = _overlord_relations_fixture()
    # Search Movie 1 → anchor discovery walks full_story → 29803 → no upward.
    # Both 34161 and 29803 are touched by discovery AND main BFS.
    fake_get, state = _make_fake_mal(fixture, [34161])
    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        await scraper.search_title(
            title="Overlord Movie 1", excluded_mal_ids=set(),
        )

    counts: dict[int, int] = {}
    for mal_id in state["fetched_relations"]:
        counts[mal_id] = counts.get(mal_id, 0) + 1
    for mal_id, n in counts.items():
        assert n == 1, (
            f"mal_id={mal_id} fetch_relations called {n} times — cache failed"
        )


@pytest.mark.asyncio
async def test_search_title_anchor_discovery_respects_max_hops(monkeypatch):
    """A pathological prequel chain longer than `_ANCHOR_DISCOVERY_MAX_HOPS`
    terminates the upward walk gracefully — no infinite loop, fetch count
    bounded. Defensive against MAL data cycles or absurdly long chains.
    """
    fixture: dict[int, dict] = {}
    chain_length = 15
    for i in range(chain_length):
        mal_id = 1000 - i
        rels = [(mal_id - 1, "Prequel")] if i < chain_length - 1 else []
        fixture[mal_id] = {"type": "TV", "title": f"Anime{mal_id}", "rels": rels}

    fake_get, state = _make_fake_mal(fixture, [1000])
    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Deep", excluded_mal_ids=set(),
        )

    # Loop terminated; we got a result. Start node landed in the graph.
    all_mal_ids: set[int] = set()
    for graph, _edges, _cl in relations:
        all_mal_ids.update(graph.keys())
    assert 1000 in all_mal_ids
    # Total fetch_relations calls bounded — generous upper bound for a
    # 15-deep chain. (Each node fetched at most once thanks to the cache.)
    assert len(state["fetched_relations"]) <= chain_length, (
        f"Too many fetches: {len(state['fetched_relations'])} — cache/loop bound failed"
    )


@pytest.mark.asyncio
async def test_search_title_eva_chao_xianshi_first_does_not_lose_main_chain(monkeypatch):
    """Production regression: MAL's `q=Evangelion` returns
    `[Chao Xianshi (63018, ONA), 3.0 (-46h) (53246, Special), Eva TV (30, TV)]`.
    Without root sorting, iter 1 (root=63018) walks `other → 30` which
    demotes Eva TV to TERMINAL and locks it into `visited_ids`. Iter 3
    (root=30) then skips, and the entire Eva chain (End of Eva, Rebuilds,
    side-stories) is lost.

    Fix: sort roots by anchor tier so Eva TV (TV) processes before the
    ONA / Special hits. WALK then propagates through Eva's alt_version
    chain to the Rebuild Movies and sequel chain to End of Eva. No
    `other` edge is followed by anchor discovery (none would help here:
    63018 has only `other` outgoing, 53246 has only `other` outgoing).
    """
    fixture = {
        30: {"type": "TV", "title": "Evangelion", "rels": [
            (32, "Sequel"),
            (31, "Summary"),
            (2759, "Alternative version"),
            (3784, "Alternative version"),
            (3785, "Alternative version"),
            (3786, "Alternative version"),
            (4130, "Spin-off"),
            (63018, "Other"),  # ← Chao Xianshi
            (53246, "Other"),  # ← 3.0 (-46h)
        ]},
        32: {"type": "Movie", "title": "End of Eva", "rels": [
            (30, "Prequel"),
        ]},
        31: {"type": "Movie", "title": "Death and Rebirth", "rels": [
            (30, "Full story"), (32, "Summary"),
        ]},
        2759: {"type": "Movie", "title": "Rebuild 1.0", "rels": [
            (30, "Alternative version"), (3784, "Sequel"),
        ]},
        3784: {"type": "Movie", "title": "Rebuild 2.0", "rels": [
            (30, "Alternative version"), (2759, "Prequel"), (3785, "Sequel"),
        ]},
        3785: {"type": "Movie", "title": "Rebuild 3.0", "rels": [
            (30, "Alternative version"), (3784, "Prequel"), (3786, "Sequel"),
            (53246, "Other"),
        ]},
        3786: {"type": "Movie", "title": "Shin Eva 3.0+1.0", "rels": [
            (30, "Alternative version"), (3785, "Prequel"), (53246, "Other"),
        ]},
        4130: {"type": "ONA", "title": "Petit Eva", "rels": [
            (30, "Parent story"),
        ]},
        63018: {"type": "ONA", "title": "Chao Xianshi", "rels": [
            (30, "Other"),
        ]},
        53246: {"type": "Special", "title": "Eva 3.0 (-46h)", "rels": [
            (3785, "Other"), (3786, "Other"),
        ]},
    }
    # MAL returns the ONA first, then Special, then TV — the exact shape
    # the user observed in dev DB.
    fake_get, _state = _make_fake_mal(fixture, [63018, 53246, 30])
    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Evangelion", excluded_mal_ids=set(),
        )

    all_mal_ids: set[int] = set()
    for graph, _edges, _cl in relations:
        all_mal_ids.update(graph.keys())

    # The Eva main chain — TV + End of Eva (sequel) + all 4 Rebuilds
    # (alternative_version, identity-preserving) — must be in the graph.
    eva_main_chain = {30, 32, 2759, 3784, 3785, 3786}
    missing = eva_main_chain - all_mal_ids
    assert not missing, (
        f"Eva main chain incomplete: missing {missing}, got {sorted(all_mal_ids)}"
    )
    # Eva TV's outgoing edges must be captured (it was WALK, not TERMINAL).
    for graph, edges, _cl in relations:
        if 30 in graph:
            assert any(a == 30 for a, _, _ in edges), (
                "Eva TV must have outgoing edges captured — was processed as TERMINAL"
            )
            break


@pytest.mark.asyncio
async def test_search_title_weak_anchor_root_releases_visited_ids(monkeypatch):
    """Regression: a search root whose graph would be weak-anchor-skipped by
    search_service must release its visited_ids claims so subsequent roots
    walking through the same chain can include the released mal_ids.

    Production-shaped fixture: short-form franchise with empty-relations
    first season. Uses 5-min episodes so the TVs fail substance below
    any reasonable gate; Movie is full-length and passes. Fuzzy search
    returns [S1, S3] — anchor-tier sort processes S1 first (oldest TV).
    S1's BFS produces a 1-node graph that fails substance AND has no
    cross-link, so search_service drops it. Pre-fix: S1 stayed claimed
    in visited_ids, S3's BFS walked Movie → S2 → S1 but S1 was already
    visited → silently skipped → S1 permanently lost from the catalog.
    Post-fix: S1's claim is rolled back when its graph is detected as
    weak-anchor-without-cross-link, letting S3's BFS include it.
    """
    relations_by_id = {
        38472: [],  # Isekai Quartet S1 — empty (real MAL behavior)
        39988: [(38472, "Prequel"), (41567, "Sequel")],
        41567: [(39988, "Prequel"), (61851, "Sequel")],
        61851: [(41567, "Prequel")],
    }

    def _short_tv(mal_id: int, title: str, aired_from: str) -> dict:
        return _make_anime(
            mal_id, title,
            media_type="TV",
            duration="5 min per ep",
            episodes=12,
            aired_from=aired_from,
            related_anime=_related(*relations_by_id[mal_id]),
        )

    def _movie(mal_id: int, title: str, aired_from: str) -> dict:
        return _make_anime(
            mal_id, title,
            media_type="Movie",
            duration="1 hr 40 min",
            episodes=1,
            aired_from=aired_from,
            related_anime=_related(*relations_by_id[mal_id]),
        )

    anime_by_id = {
        38472: _short_tv(38472, "Isekai Quartet", "2019-04-09T00:00:00+00:00"),
        39988: _short_tv(39988, "Isekai Quartet 2", "2020-01-14T00:00:00+00:00"),
        41567: _movie(41567, "Isekai Quartet Movie", "2022-06-10T00:00:00+00:00"),
        61851: _short_tv(61851, "Isekai Quartet 3", "2025-04-09T00:00:00+00:00"),
    }

    async def fake_get(self, url, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            # Search returns S1 + S3 (omit S2 + Movie to keep the test
            # focused on the S1-as-root weak-anchor case). Anchor-tier
            # sort puts S1 first (older TV beats newer TV; both tier 1).
            return {"data": [{"node": anime_by_id[38472]}, {"node": anime_by_id[61851]}]}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return anime_by_id[mal_id]
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(MalScraper, "_get", fake_get)

    async with MalScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Isekai Quartet", excluded_mal_ids=set(),
        )

    # One graph survives — the S3 root's, which walked the full chain.
    # S1's root produced a weak-anchor singleton that got dropped + rolled
    # back; without the rollback, S3's graph would be missing S1.
    assert len(relations) == 1, (
        f"Expected 1 surviving graph (S3's, with full chain) — got {len(relations)}"
    )
    graph, _edges, _cross_links = relations[0]
    assert set(graph.keys()) == {38472, 39988, 41567, 61851}, (
        f"Surviving graph must include S1 (38472) via S3's BFS walk through "
        f"the prequel chain — got {sorted(graph.keys())}. If S1 is missing, "
        f"the rollback didn't fire and S1 stayed claimed in visited_ids."
    )
