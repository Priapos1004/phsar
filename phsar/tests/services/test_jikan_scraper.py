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
async def test_search_title_seed_empty_data_raises_transient_not_permanent(monkeypatch):
    """When MAL returns 200 OK with empty `data` (observed in practice
    for legitimate mal_ids on transient hiccups), search_title must
    raise TransientUpstreamError — NOT AnimeNotFoundError. The
    difference matters downstream: TransientUpstreamError is not a
    PermanentPhsarError, so the worker stamps retryable=True and the
    bell shows its retry button. The old behavior produced retryable=False
    + an opaque 'mal_id=N not found' message, locking the user out for
    the 72h dedup window for a transient MAL anomaly."""
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
async def test_search_title_recovers_dropped_seed_post_loop(monkeypatch):
    """The pre-existing BFS bug (and its fix): when the seed is
    classified as is_main_story=True AND has outgoing relations, the
    BFS drops it from `visited_ids` and the graph, expecting organic
    rediscovery via a back-pointing relation. For franchises like
    Rilakkuma (60153) whose only relation is `Other` and where no
    sub-graph node points back, no rediscovery happens, AND the
    inline bottom-of-loop re-enqueue is bypassed when the last popped
    node hits a `continue` path (cross-link in our test setup).
    Post-loop net adds the seed back as main; without it, the graph
    ends with no `main` and MainMediaNotFoundError fires.

    Setup mirrors Rilakkuma exactly:
    - Seed 1 (TV, no parent_story) → Other → 2 (the related show)
    - 2's relations point forward, never back to 1
    - 3 is in excluded_mal_ids (cross-link) so the last pop hits
      `continue` and bypasses the bottom-of-loop re-enqueue.
    """
    async def fake_get(self, url: str, params=None):
        if url.endswith("/anime") and params is not None and params.get("q"):
            return {"data": [_make_anime(1, "Origin TV")]}
        if url.endswith("/relations"):
            mal_id = int(url.rsplit("/", 2)[-2])
            if mal_id == 1:
                return {"data": [{"relation": "Other", "entry": [{"type": "anime", "mal_id": 2}]}]}
            if mal_id == 2:
                # 2's only relation goes to 3 (which is pre-excluded).
                # CRITICALLY: no relation points back to 1.
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
    graph, _cross_links = relations[0]
    # The post-loop net recovered the dropped seed as main.
    assert 1 in graph
    assert graph[1]["relation_type"] == "main"
    # And all_info has the seed entry (also restored by the net).
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
    graph, _cross_links = relations[0]
    # The sequel branch was walked; the alt-setting branch wasn't.
    assert 2 in graph
    assert 99 not in graph
    assert 99 not in fetched_anime
    assert 99 not in fetched_relations


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
