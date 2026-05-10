import pytest

from app.services.jikan_scraper import JikanScraper


def _make_anime(mal_id: int, title: str, *, media_type: str = "TV") -> dict:
    """Minimum anime payload accepted by extract_information without nulls."""
    return {
        "mal_id": mal_id,
        "url": f"https://example/{mal_id}",
        "title": title,
        "title_english": title,
        "title_japanese": title,
        "title_synonyms": [],
        "type": media_type,
        "genres": [{"name": "Action"}],
        "explicit_genres": [],
        "themes": [],
        "demographics": [],
        "studios": [{"name": "Studio Test"}],
        "rating": "PG-13",
        "synopsis": "",
        "source": "Original",
        "images": {"jpg": {"large_image_url": "https://example/cover.jpg"}},
        "score": 7.5,
        "scored_by": 1000,
        "episodes": 12,
        "season": "Spring",
        "year": 2020,
        "aired": {"from": "2020-04-01T00:00:00+00:00", "to": "2020-06-30T00:00:00+00:00"},
        "status": "Finished Airing",
        "duration": "23 min per ep",
    }


@pytest.mark.asyncio
async def test_search_title_skips_relations_for_crossover_node(monkeypatch):
    """A crossover relation is recorded in the graph but not BFS'd into.

    Setup:
    - Search returns one anime (id 1).
    - Anime 1's relations include a Crossover to anime 99.
    - Anime 99's `extract_information` works (TV/Movie), but if we ever
      called fetch_relations(99) the test would record it and fail.
    - Anime 1 also has a sequel (id 2) whose relations include anime 3,
      so the BFS still runs for non-crossover branches — proving the
      crossover skip is targeted, not a global suppression.
    """
    relations_calls: list[int] = []
    by_id_calls: list[int] = []

    async def fake_get(self, url: str, params=None):
        # Search request — returns the entry anime.
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [_make_anime(1, "Origin Anime")]}

        # /anime/{id}/relations
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            relations_calls.append(mal_id)
            if mal_id == 1:
                return {
                    "data": [
                        {"relation": "Crossover", "entry": [{"type": "anime", "mal_id": 99}]},
                        {"relation": "Sequel", "entry": [{"type": "anime", "mal_id": 2}]},
                    ]
                }
            if mal_id == 2:
                return {"data": [{"relation": "Prequel", "entry": [{"type": "anime", "mal_id": 1}]}]}
            # Anime 99's relations should NEVER be requested. Still answer
            # so a bug doesn't crash the test before the assert.
            return {"data": []}

        # /anime/{id}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            by_id_calls.append(mal_id)
            return {"data": _make_anime(mal_id, f"Anime {mal_id}")}

        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids=set(),
        )

    assert len(relations) == 1, "Expected exactly one relation graph from one search hit"
    graph, cross_link_mal_ids = relations[0]

    # Crossover anime IS in the graph...
    assert 99 in graph
    assert graph[99]["relation_type"] == "crossover"
    # ...but its relations were never fetched.
    assert 99 not in relations_calls
    # Non-crossover branch (sequel chain) still BFS'd: anime 2 was traversed.
    assert 2 in graph
    assert 2 in relations_calls
    # Nothing was pre-excluded, so no cross-links were recorded.
    assert cross_link_mal_ids == set()


@pytest.mark.asyncio
async def test_search_title_records_cross_link_for_pre_excluded_relation(monkeypatch):
    """When BFS would traverse to a media that's already in the catalog
    via a non-crossover relation, that mal_id is surfaced as a cross-link
    signal for the merge-candidate detector to use.

    Setup needs at least one non-excluded sibling so the entry node gets
    re-discovered organically (the BFS deliberately drops and re-finds the
    first node when it has relations); without that we'd produce an empty
    graph and lose the cross-link with it.
    """
    relations_calls: list[int] = []

    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [_make_anime(1, "Origin Anime")]}

        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            relations_calls.append(mal_id)
            if mal_id == 1:
                return {
                    "data": [
                        # Fresh sibling — keeps the graph non-empty.
                        {"relation": "Sequel", "entry": [{"type": "anime", "mal_id": 2}]},
                        # 42 is pre-excluded → cross-link signal.
                        {"relation": "Sequel", "entry": [{"type": "anime", "mal_id": 42}]},
                    ]
                }
            if mal_id == 2:
                return {"data": [{"relation": "Prequel", "entry": [{"type": "anime", "mal_id": 1}]}]}
            return {"data": []}

        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return {"data": _make_anime(mal_id, f"Anime {mal_id}")}

        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids={42},
        )

    assert len(relations) == 1
    graph, cross_link_mal_ids = relations[0]

    # 42 was pre-excluded so it doesn't appear in the graph...
    assert 42 not in graph
    # ...and we never fetched its relations (it was already known).
    assert 42 not in relations_calls
    # ...but the cross-link signal captures it for the detector.
    assert cross_link_mal_ids == {42}
    # The non-excluded sibling is in the graph as expected.
    assert 1 in graph and 2 in graph


@pytest.mark.asyncio
async def test_search_title_no_cross_link_for_crossover_relation(monkeypatch):
    """A pre-excluded media reached via a crossover relation is NOT a
    cross-link — crossovers are explicit franchise boundaries, not duplicate
    signals."""
    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [_make_anime(1, "Origin Anime")]}

        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            if mal_id == 1:
                return {
                    "data": [
                        {"relation": "Sequel", "entry": [{"type": "anime", "mal_id": 2}]},
                        # 99 is pre-excluded AND reached via Crossover.
                        {"relation": "Crossover", "entry": [{"type": "anime", "mal_id": 99}]},
                    ]
                }
            if mal_id == 2:
                return {"data": [{"relation": "Prequel", "entry": [{"type": "anime", "mal_id": 1}]}]}
            return {"data": []}

        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return {"data": _make_anime(mal_id, f"Anime {mal_id}")}

        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids={99},
        )

    _graph, cross_link_mal_ids = relations[0]
    assert cross_link_mal_ids == set()


@pytest.mark.asyncio
async def test_search_title_does_not_blacklist_not_yet_aired_anime(monkeypatch):
    """Just-announced sequels (`media_type=None` + `status="Not yet aired"`)
    must skip silently — a permanent unwanted entry would block
    rediscovery once MAL fills the type."""
    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [_make_anime(1, "Origin Anime")]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            if mal_id == 1:
                return {"data": [{"relation": "Sequel", "entry": [{"type": "anime", "mal_id": 2}]}]}
            return {"data": []}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            payload = _make_anime(mal_id, f"Anime {mal_id}")
            if mal_id == 2:
                payload["type"] = None
                payload["status"] = "Not yet aired"
                payload["aired"] = {"from": None, "to": None}
            return {"data": payload}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
        _relations, _all_info, unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids=set(),
        )

    assert all(uw[0] != 2 for uw in unwanted), (
        "Not-yet-aired anime (mal_id=2) must NOT land in unwanted_media"
    )


@pytest.mark.asyncio
async def test_search_title_blacklists_other_anomalous_no_media_type(monkeypatch):
    """Anime with `media_type=None` but a non-`Not yet aired` status is
    still a MAL anomaly worth blacklisting — keeps the existing
    Music/PV/CM/Hentai pattern intact for true outliers."""
    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [_make_anime(1, "Origin Anime")]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            if mal_id == 1:
                return {"data": [{"relation": "Other", "entry": [{"type": "anime", "mal_id": 2}]}]}
            return {"data": []}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            payload = _make_anime(mal_id, f"Anime {mal_id}")
            if mal_id == 2:
                payload["type"] = None
                # Status is set (not "Not yet aired") — anomalous.
                payload["status"] = "Finished Airing"
            return {"data": payload}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
        _relations, _all_info, unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids=set(),
        )

    assert any(uw[0] == 2 and uw[2] == "Unknown" for uw in unwanted)


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
    result = JikanScraper._parse_duration_to_seconds(duration_str)
    assert result == expected_seconds, f"For '{duration_str}', expected {expected_seconds} but got {result}"
