import pytest

from app.services.jikan_scraper import JikanScraper


def _relations_response(*pairs: tuple[int, str]) -> dict:
    """Build a `/anime/{id}/relations` response from `(target_mal_id, relation_label)`
    pairs. Groups same-label pairs into one block — matches MAL's wire shape
    where a single "Side Story" block can carry multiple entries."""
    by_relation: dict[str, list[int]] = {}
    for target, rel in pairs:
        by_relation.setdefault(rel, []).append(target)
    return {
        "data": [
            {"relation": rel, "entry": [{"type": "anime", "mal_id": m} for m in mids]}
            for rel, mids in by_relation.items()
        ]
    }


def _make_anime(
    mal_id: int,
    title: str,
    *,
    media_type: str = "TV",
    duration: str = "23 min per ep",
    episodes: int = 12,
    aired_from: str = "2020-04-01T00:00:00+00:00",
) -> dict:
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
        "episodes": episodes,
        "season": "Spring",
        "year": 2020,
        "aired": {"from": aired_from, "to": "2020-06-30T00:00:00+00:00"},
        "status": "Finished Airing",
        "duration": duration,
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
    graph, edges, cross_link_mal_ids = relations[0]

    # Crossover anime IS in the graph and the edge to it is recorded...
    assert 99 in graph
    assert (1, 99, "crossover") in edges
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
    graph, _edges, cross_link_mal_ids = relations[0]

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

    _graph, _edges, cross_link_mal_ids = relations[0]
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
async def test_search_title_seed_empty_data_raises_transient_not_permanent(monkeypatch):
    """When MAL returns 200 OK with empty `data` (observed in practice
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
        # case observed in production (job 2617 for mal_id=64060).
        if "/anime/" in url and url.rsplit("/", 1)[-1].isdigit():
            return {"data": {}}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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
            return {"data": [_make_anime(1, "Origin TV")]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            if mal_id == 1:
                return {"data": [{"relation": "Other", "entry": [{"type": "anime", "mal_id": 2}]}]}
            if mal_id == 2:
                return {"data": [{"relation": "Other", "entry": [{"type": "anime", "mal_id": 3}]}]}
            return {"data": []}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return {"data": _make_anime(mal_id, f"Anime {mal_id}", media_type="ONA")}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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
    The BFS must NOT walk it — otherwise distinct donghua get
    conflated into one Anime row and the merge detector fires
    false positives on every sweep.

    Setup: seed has Sequel → 2 (legit branch, BFS walks) AND
    Alternative Setting → 99 (separate franchise, BFS must NOT walk).
    If 99 ever gets fetched, the test fails."""
    fetched_anime: list[int] = []
    fetched_relations: list[int] = []

    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [_make_anime(1, "Origin Anime")]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            fetched_relations.append(mal_id)
            if mal_id == 1:
                return {
                    "data": [
                        {"relation": "Sequel", "entry": [{"type": "anime", "mal_id": 2}]},
                        {"relation": "Alternative Setting", "entry": [{"type": "anime", "mal_id": 99}]},
                    ]
                }
            if mal_id == 2:
                return {"data": [{"relation": "Prequel", "entry": [{"type": "anime", "mal_id": 1}]}]}
            # mal_id == 99 should never be requested. If it is, test fails.
            raise AssertionError(
                f"Alternative-setting branch was walked into mal_id={mal_id}"
            )
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            fetched_anime.append(mal_id)
            return {"data": _make_anime(mal_id, f"Anime {mal_id}")}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Origin", excluded_mal_ids=set(),
        )

    assert len(relations) == 1
    graph, _edges, _cross_links = relations[0]
    # The sequel branch was walked; the alt-setting branch wasn't.
    assert 2 in graph
    assert 99 not in graph
    assert 99 not in fetched_anime
    assert 99 not in fetched_relations


@pytest.mark.asyncio
async def test_search_title_captures_normalized_edges(monkeypatch):
    """BFS captures every edge with the normalized MAL relation string.
    MAL emits multi-word relations title-cased (`"Side Story"`,
    `"Parent story"`); `_normalize_relation` lowercases + underscores so
    the classifier sees a stable taxonomy.

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
        20: [
            {"relation": "Sequel", "entry": [{"type": "anime", "mal_id": 1735}]},
            {"relation": "Side Story", "entry": [{"type": "anime", "mal_id": 894}]},
            {"relation": "Side Story", "entry": [{"type": "anime", "mal_id": 936}]},
        ],
        1735: [
            {"relation": "Prequel", "entry": [{"type": "anime", "mal_id": 20}]},
            {"relation": "Side Story", "entry": [{"type": "anime", "mal_id": 5085}]},
        ],
        894: [{"relation": "Parent story", "entry": [{"type": "anime", "mal_id": 20}]}],
        936: [{"relation": "Parent story", "entry": [{"type": "anime", "mal_id": 20}]}],
        5085: [{"relation": "Parent story", "entry": [{"type": "anime", "mal_id": 1735}]}],
    }
    type_by_id = {20: "TV", 1735: "TV", 894: "Movie", 936: "OVA", 5085: "Movie"}
    title_by_id = {
        20: "Naruto",
        1735: "Naruto: Shippuuden",
        894: "Naruto Movie 1",
        936: "Naruto OVA",
        5085: "Naruto Shippuuden Movie 1",
    }

    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [_make_anime(20, "Naruto", media_type="TV")]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            return {"data": relations_by_id.get(mal_id, [])}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return {"data": _make_anime(mal_id, title_by_id[mal_id], media_type=type_by_id[mal_id])}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Naruto", excluded_mal_ids=set(),
        )

    assert len(relations) == 1
    graph, edges, _cross_links = relations[0]

    assert set(graph.keys()) == {20, 1735, 894, 936, 5085}

    # Every node's outgoing edges land as normalized edge labels — WALK
    # AND TERMINAL nodes both contribute. 20 (Naruto TV) and 1735
    # (Shippuuden) walk; 894/936/5085 are TERMINAL but their /relations
    # are fetched so the reverse parent_story edges back to TV ARE in
    # the persisted list. The BFS just doesn't recurse from them — TV's
    # sequels reached via those parent_story edges stay out of the graph
    # unless WALK already covered them.
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
    a MediaUnwanted row with the real name. Blacklisting now with a
    placeholder would (a) block re-discovery and (b) pollute the
    admin-only table with `<mal_id:NNNN>` strings.

    Test setup: mal_id=2 is a PV with `title=null`. It must NOT appear
    in unwanted_media — the BFS effectively treated it as a deferred
    entry, same as Not-yet-aired.
    """
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
                # PV with no title at all — the exact production failure.
                payload["title"] = None
                payload["type"] = "PV"
            return {"data": payload}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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
                payload["title"] = None
                payload["type"] = None  # would trigger Unknown branch if not for the title=null guard
                payload["status"] = "Finished Airing"  # not Not-yet-aired
            return {"data": payload}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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
    assert JikanScraper._clean_synopsis(raw) == expected


@pytest.mark.asyncio
async def test_rate_limiter_spaces_consecutive_requests(monkeypatch):
    """Two back-to-back calls must be spaced at least _MIN_REQUEST_INTERVAL_S
    apart. Without this, a 200-anime sweep would burst hundreds of
    requests into Jikan as fast as TCP allows."""
    from time import monotonic

    # Override to a small value so the test stays fast but still proves
    # spacing — the production constant doesn't need to be exercised.
    monkeypatch.setattr(JikanScraper, "_MIN_REQUEST_INTERVAL_S", 0.05)
    JikanScraper._last_request_at = 0.0

    t0 = monotonic()
    await JikanScraper._wait_for_rate_limit()
    await JikanScraper._wait_for_rate_limit()
    elapsed = monotonic() - t0

    assert elapsed >= 0.045  # 5% margin under the configured 50ms gap


@pytest.mark.asyncio
async def test_get_does_not_retry_4xx(monkeypatch):
    """A 404 (or any 4xx) is deterministic — retrying wastes 31s of
    exponential backoff before failing the same way. The httpx.AsyncClient
    mock must see exactly one request."""
    import httpx

    monkeypatch.setattr(JikanScraper, "_MIN_REQUEST_INTERVAL_S", 0.0)

    call_count = 0

    async def fake_get(self, url, params=None):
        nonlocal call_count
        call_count += 1
        request = httpx.Request("GET", url)
        return httpx.Response(404, request=request, content=b'{"detail": "not found"}')

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with JikanScraper() as scraper:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await scraper._get("https://example/anime")

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

    monkeypatch.setattr(JikanScraper, "_MIN_REQUEST_INTERVAL_S", 0.0)
    # Zero out wait but DO NOT touch stop — we want to verify the
    # production stop_strategy enforces the 3-attempt cap for 429.
    from tenacity import wait_fixed
    monkeypatch.setattr(JikanScraper._get.retry, "wait", wait_fixed(0))

    call_count = 0

    async def fake_get(self, url, params=None):
        nonlocal call_count
        call_count += 1
        request = httpx.Request("GET", url)
        return httpx.Response(429, request=request, content=b"rate limited")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with JikanScraper() as scraper:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await scraper._get("https://example/anime")

    # 1 initial + 2 retries = 3 total attempts for 429.
    assert call_count == 3
    assert exc_info.value.response.status_code == 429


@pytest.mark.asyncio
async def test_fetch_current_season_paginates(monkeypatch):
    """Jikan's /seasons/now is paginated. The loop must keep requesting
    pages while `pagination.has_next_page` is true and concatenate every
    page's data. The page=N query parameter advances per iteration."""
    calls: list[dict | None] = []

    async def fake_get(self, url, params=None):
        assert url.endswith("/seasons/now")
        calls.append(params)
        page = (params or {}).get("page", 1)
        if page == 1:
            return {
                "data": [{"mal_id": 1, "title": "Show A"}, {"mal_id": 2, "title": "Show B"}],
                "pagination": {"has_next_page": True, "current_page": 1},
            }
        return {
            "data": [{"mal_id": 3, "title": "Show C"}],
            "pagination": {"has_next_page": False, "current_page": 2},
        }

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
        entries = await scraper.fetch_current_season()

    assert [e["mal_id"] for e in entries] == [1, 2, 3]
    assert [c.get("page") for c in calls] == [1, 2]


@pytest.mark.asyncio
async def test_fetch_current_season_empty(monkeypatch):
    """An empty season (off-week between cycles, or test against a fresh
    DB) returns no entries without crashing. Single page, no follow-up."""
    call_count = 0

    async def fake_get(self, url, params=None):
        nonlocal call_count
        call_count += 1
        return {"data": [], "pagination": {"has_next_page": False}}

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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

    monkeypatch.setattr(JikanScraper, "_MIN_REQUEST_INTERVAL_S", 0.0)
    from tenacity import wait_fixed
    monkeypatch.setattr(JikanScraper._get.retry, "wait", wait_fixed(0))

    call_count = 0

    async def fake_get(self, url, params=None):
        nonlocal call_count
        call_count += 1
        request = httpx.Request("GET", url)
        return httpx.Response(503, request=request, content=b"service unavailable")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with JikanScraper() as scraper:
        with pytest.raises(httpx.HTTPStatusError):
            await scraper._get("https://example/anime")

    assert call_count == 5  # 1 initial + 4 retries; strictly > 429's 3


@pytest.mark.asyncio
async def test_get_retries_5xx_and_surfaces_underlying_error(monkeypatch):
    """5xx IS transient — tenacity retries to the cap (5 attempts), then
    reraise=True surfaces the underlying HTTPStatusError instead of
    wrapping it in tenacity's RetryError. The bell's result_summary
    gets the human-readable upstream message, not `RetryError[<Future at 0x...>]`."""
    import httpx

    monkeypatch.setattr(JikanScraper, "_MIN_REQUEST_INTERVAL_S", 0.0)
    # Tighten the backoff so the test isn't 31s long.
    from tenacity import stop_after_attempt, wait_fixed
    monkeypatch.setattr(JikanScraper._get.retry, "stop", stop_after_attempt(3))
    monkeypatch.setattr(JikanScraper._get.retry, "wait", wait_fixed(0))

    call_count = 0

    async def fake_get(self, url, params=None):
        nonlocal call_count
        call_count += 1
        request = httpx.Request("GET", url)
        return httpx.Response(504, request=request, content=b"gateway timeout")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    async with JikanScraper() as scraper:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await scraper._get("https://example/anime")

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
    57034's anime info is never fetched, and 56842, 54595, 48316 stay out
    of the graph entirely. Pleiades's `/relations` IS fetched (so its
    outgoing `other` edge to 57034 is recorded), but 57034 onward are not.

    Production observation that drove the strict (vs. one-hop) state
    machine: a direct Main(Eva) → other → Main(Ultraman) edge under one-hop
    would have pulled Ultraman's full sequel chain into Eva. Under strict,
    only Ultraman's Main node leaks as a single TERMINAL — the user can
    surface that as a merge candidate without splitting a hundred sequels
    out manually.
    """
    fetched_relations: list[int] = []

    relations_by_id = {
        29803: [(31138, "Side Story")],
        31138: [(57034, "Other")],   # Must never be fetched.
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
            return {"data": [_make_anime(29803, "Overlord")]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            fetched_relations.append(mal_id)
            return _relations_response(*relations_by_id[mal_id])
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return {"data": _make_anime(mal_id, title_by_id[mal_id])}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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

    # Pleiades's relations ARE fetched (TERMINAL captures outgoing edges
    # so split-detection has the data), but the Eminence chain stays out:
    # 57034 onward are never queued because Pleiades is TERMINAL and the
    # for-loop skips queuing its targets.
    assert 31138 in fetched_relations, (
        "Pleiades is TERMINAL — its /relations IS fetched for sidecar edges"
    )
    for mal_id in (57034, 56842, 54595, 48316):
        assert mal_id not in fetched_relations, (
            f"fetch_relations({mal_id}) was called — BFS crossed the boundary"
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
    by anchor discovery (target IS the canonical ancestor). See
    `test_search_title_anchor_discovery_promotes_via_parent_story_and_full_story`
    for that path.

    This is the strict boundary the pre-v0.14.0 BFS enforced; v0.14.1's
    two-pass classifier doesn't need the deeper graph for correct
    classification, so we restore the tight membership and prevent
    cross-franchise contamination — both the chained-bridge shape
    (Overlord → Pleiades → other → Kagejitsu) and the direct
    main → other → main shape (Eva → other → Ultraman's full sequel chain).
    """
    fetched_relations: list[int] = []

    async def fake_get(self, url, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [_make_anime(1, "Root")]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            fetched_relations.append(mal_id)
            if mal_id == 1:
                return _relations_response((2, rel_label))
            if mal_id == 2:
                return _relations_response((3, "Sequel"))
            if mal_id == 3:
                return _relations_response((4, "Sequel"))
            return {"data": []}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return {"data": _make_anime(mal_id, f"Anime {mal_id}")}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Root", excluded_mal_ids=set(),
        )

    graph, edges, _ = relations[0]

    # Root walked normally and recorded the edge to A.
    assert 1 in graph and 1 in fetched_relations
    # A is in the graph (info recorded) AND its relations ARE fetched —
    # TERMINAL nodes capture outgoing edges for sidecar persistence so
    # split-detection can later see A's franchise chain. The boundary
    # holds at A's targets: the BFS does NOT queue them.
    assert 2 in graph, (
        f"A (queued via {rel_normalized}) must be in graph as TERMINAL"
    )
    assert 2 in fetched_relations, (
        "A's relations must be fetched — TERMINAL captures outgoing "
        "edges for sidecar persistence, even though BFS doesn't recurse"
    )
    # Therefore B (A's sequel) and C (B's sequel) are unreachable — the
    # BFS never queues them, never fetches their info or relations.
    assert 3 not in graph
    assert 4 not in graph
    assert 3 not in fetched_relations
    assert 4 not in fetched_relations

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
    - Vigilante S1's /relations IS fetched (so the (60593, 61942, "sequel")
      edge lands in the persisted list).
    - Vigilante S2 is NOT in the graph (TERMINAL doesn't queue its targets).
    - Vigilante S2's /relations is NEVER fetched.
    - Split-detection downstream sees the sequel edge in the sidecar and
      flags the Vigilante cluster for admin review.
    """
    fetched_relations: list[int] = []

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
            return {"data": [_make_anime(31964, "Boku no Hero Academia")]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            fetched_relations.append(mal_id)
            return _relations_response(*relations_by_id.get(mal_id, []))
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return {"data": _make_anime(mal_id, title_by_id[mal_id])}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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

    # Vigilante S1's /relations IS fetched (TERMINAL captures outgoing
    # edges) but Vigilante S2's is NOT (never queued).
    assert 60593 in fetched_relations, (
        "Vigilante S1 is TERMINAL — its /relations must be fetched so the "
        "sequel edge to S2 lands in the persisted edge list for split-detection"
    )
    assert 61942 not in fetched_relations

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
    fetched_relations: list[int] = []

    async def fake_get(self, url, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [_make_anime(1, "Root")]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            fetched_relations.append(mal_id)
            chain = {1: 2, 2: 3, 3: 4}
            target = chain.get(mal_id)
            return _relations_response((target, rel_label)) if target else {"data": []}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return {"data": _make_anime(mal_id, f"Anime {mal_id}")}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Root", excluded_mal_ids=set(),
        )

    graph, edges, _ = relations[0]
    # Full chain walked.
    assert set(graph.keys()) == {1, 2, 3, 4}
    # Every node fetched relations — proves WALK status all the way.
    assert set(fetched_relations) == {1, 2, 3, 4}
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
        root → Side Story → X     (would mark X as ONE_HOP)
        root → Sequel → X         (marks X as WALK)

    Result: X is WALK, X's relations are fetched, X's sequel Y is queued and
    fetched (WALK). Without promotion, X stays ONE_HOP, Y is TERMINAL, and
    Y's relations aren't fetched — caught by the assertion that Y IS fetched.
    """
    fetched_relations: list[int] = []

    async def fake_get(self, url, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [_make_anime(1, "Root")]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            fetched_relations.append(mal_id)
            if mal_id == 1:
                # X (2) reached via BOTH side_story AND sequel from root.
                return _relations_response((2, "Side Story"), (2, "Sequel"))
            if mal_id == 2:
                return _relations_response((3, "Sequel"))
            if mal_id == 3:
                return _relations_response((4, "Sequel"))
            return {"data": []}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return {"data": _make_anime(mal_id, f"Anime {mal_id}")}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Root", excluded_mal_ids=set(),
        )

    graph, _, _ = relations[0]
    # X (2) was promoted to WALK by the sequel edge → its relations fetched
    # → its sequel target (3) is WALK → 3's relations fetched → 4 reached.
    assert {1, 2, 3, 4}.issubset(set(graph.keys())), (
        "X must be WALK (promoted by sequel edge), so its sequel chain is walked"
    )
    assert 2 in fetched_relations
    assert 3 in fetched_relations
    assert 4 in fetched_relations


@pytest.mark.asyncio
async def test_search_title_no_cross_link_to_deep_other_chain_target(monkeypatch):
    """A catalog member sitting behind a chain of identity-breaking edges from
    the seed is NOT reached by the BFS (TERMINAL truncates), so it does NOT
    surface as a cross_link.

    Codifies the cost-asymmetry tradeoff: a deep-chain catalog hit doesn't
    spam merge candidates. The merge-candidate detector sees ONLY direct
    cross-links from WALK or ONE_HOP nodes, never from TERMINAL boundaries.
    """
    deep_catalog_id = 999

    async def fake_get(self, url, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [_make_anime(1, "Root")]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            if mal_id == 1:
                return _relations_response((2, "Side Story"))  # 2: ONE_HOP
            if mal_id == 2:
                return _relations_response((3, "Other"))  # 3: TERMINAL
            if mal_id == 3:
                # Would point at a catalog member, but this is never fetched.
                return _relations_response((deep_catalog_id, "Sequel"))
            return {"data": []}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return {"data": _make_anime(mal_id, f"Anime {mal_id}")}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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
    where `state` exposes lists of mal_ids hit on each MAL endpoint for
    assertions."""
    state = {
        "fetched_relations": [],
        "fetched_by_malid": [],  # /anime/{id}
    }

    async def fake_get(self, url, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [
                _make_anime(
                    mal_id, fixture[mal_id]["title"],
                    media_type=fixture[mal_id]["type"],
                )
                for mal_id in search_result_ids
            ]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            state["fetched_relations"].append(mal_id)
            rels = fixture.get(mal_id, {}).get("rels", [])
            return _relations_response(*rels)
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            state["fetched_by_malid"].append(mal_id)
            entry = fixture.get(mal_id)
            if entry is None:
                return {"data": _make_anime(mal_id, f"Anime {mal_id}")}
            return {"data": _make_anime(
                mal_id, entry["title"], media_type=entry["type"],
            )}
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
    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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
    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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
    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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
    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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
    """The relation cache eliminates duplicate `/relations` fetches between
    anchor discovery and the main BFS. Each upward-walked node is fetched
    exactly once."""
    fixture = _overlord_relations_fixture()
    # Search Movie 1 → anchor discovery walks full_story → 29803 → no upward.
    # Both 34161 and 29803 are touched by discovery AND main BFS.
    fake_get, state = _make_fake_mal(fixture, [34161])
    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
        await scraper.search_title(
            title="Overlord Movie 1", excluded_mal_ids=set(),
        )

    counts: dict[int, int] = {}
    for mal_id in state["fetched_relations"]:
        counts[mal_id] = counts.get(mal_id, 0) + 1
    for mal_id, n in counts.items():
        assert n == 1, (
            f"mal_id={mal_id} /relations fetched {n} times — cache failed"
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
    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
        relations, _all_info, _unwanted = await scraper.search_title(
            title="Deep", excluded_mal_ids=set(),
        )

    # Loop terminated; we got a result. Start node landed in the graph.
    all_mal_ids: set[int] = set()
    for graph, _edges, _cl in relations:
        all_mal_ids.update(graph.keys())
    assert 1000 in all_mal_ids
    # Total /relations fetches bounded — generous upper bound for a 15-deep
    # chain. (Each node fetched at most once thanks to the cache.)
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
    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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
    fetched_relations: list[int] = []

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
        )

    def _movie(mal_id: int, title: str, aired_from: str) -> dict:
        return _make_anime(
            mal_id, title,
            media_type="Movie",
            duration="1 hr 40 min",
            episodes=1,
            aired_from=aired_from,
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
            return {"data": [anime_by_id[38472], anime_by_id[61851]]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            fetched_relations.append(mal_id)
            pairs = relations_by_id.get(mal_id, [])
            return _relations_response(*pairs) if pairs else {"data": []}
        if "/anime/" in url:
            mal_id = int(url.rsplit("/", 1)[-1])
            return {"data": anime_by_id[mal_id]}
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(JikanScraper, "_get", fake_get)

    async with JikanScraper() as scraper:
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
