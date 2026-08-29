# Scraping

How anime data enters the catalogue. Current behaviour; the decisions behind it are
in the compound-docs linked at the bottom.

**Code**: `services/mal_scraper.py` (client + BFS) → `services/search_service.py`
(save/attach/merge decisions) → `services/save_service.py` (persistence) →
`services/scrape_dispatcher.py` (job handler).

## Source

The official **MyAnimeList API v2**. Auth is a single header,
`X-MAL-CLIENT-ID`, set once on the `httpx.AsyncClient` so it cannot be forgotten
per-call; public data needs no OAuth. The client fails closed when
`MY_ANIME_LIST_CLIENT_ID` is unset.

## One MAL call per node

`/anime/{id}` with `_DETAIL_FIELDS` returns the record **and** its `related_anime`
in one response, so a BFS or sweep node costs exactly one request. This is what
keeps the crawl affordable at 1 req/s.

**The `/anime?q=` search endpoint is the exception.** `related_anime` is
detail-only — MAL drops it from list-endpoint nodes even when `fields` asks for
it. So `_SEARCH_FIELDS` requests only `id,title`, search is treated purely as
fuzzy title→mal_id discovery, and each *root* is re-fetched through its detail
call before the BFS runs. Skipping that re-fetch leaves every root's
`relation_cache` empty, so the BFS captures no edges and franchises fragment into
single-media rows with empty sidecars — which then surface as spurious
`title_studio` merge candidates.

## Rate limiting and retries

A class-level lock spaces request *starts* at `MAL_MIN_REQUEST_INTERVAL_S`
(default 1.0s). MAL's limit on the official API is undocumented; ~1 req/s is safe
for continuous flows, and tighter intervals (0.35s, 0.5s) draw 429s.

Retries are Tenacity `wait_exponential(multiplier=2, min=1, max=30)`, gated by
`_is_transient_mal_error` so only 5xx, 429, timeouts and network errors retry —
every other 4xx is deterministic and would burn 31s of backoff to fail identically. `reraise=True`
surfaces the underlying `httpx` error rather than tenacity's wrapper.

**429 is capped at 3 attempts** where 5xx/timeout get 5. Retrying a throttle
harder masks sustained over-rate; the correct response is to slow
`MAL_MIN_REQUEST_INTERVAL_S`.

A 404 on the **direct-id path** (a bare 5–6 digit query routed to `seed_mal_id`)
raises the permanent `MalIdNotFoundError`, so the job bell shows "No anime on
MyAnimeList has id N" with no retry button. A 200-OK-with-empty-data response
stays `TransientUpstreamError` and remains retryable.

## Value translation

`extract_information` is an anti-corruption layer at the ingestion chokepoint. MAL
v2 emits snake_case/lowercase `media_type`, `status`, `rating` and `source`; the
`_MEDIA_TYPE_MAP` / `_AIRING_STATUS_MAP` / `_AGE_RATING_MAP` / `_SOURCE_MAP`
tables convert them to the catalogue's stored title-cased strings.

That boundary is load-bearing for the DB enums, the `ix_media_airing_now` partial
index (which matches the literal `'Currently Airing'`), `age_rating_numeric`'s
prefix map, the classifier sentinels, and the filter facets — all of which compare
against the stored format.

- Only the six insertable `MediaType` values map. `music`/`cm`/`pv` pass through
  lowercased for the skip rule; `unknown` becomes None.
- Unknown `source` values pass through unchanged rather than being dropped.
- Relation labels normalize via `normalize_relation` (lowercase, spaces →
  underscores) plus a `spin_off` → `spin-off` alias, so a sweep re-fetch doesn't
  rewrite every spin-off edge.
- **Air dates carry no time.** MAL publishes `start_date` / `end_date` as bare
  `YYYY-MM-DD`, and `_mal_date_to_iso` stores that form unchanged. **Partial
  dates** (`YYYY`, `YYYY-MM`, common on older records) fill the missing
  month/day with `01`; that padding is not recoverable, so a stored
  `2011-01-01` may mean "sometime in 2011".
- `duration_seconds` comes from `average_episode_duration` (exact per-episode
  seconds). The legacy `duration` display string is always None; the frontend
  renders from `duration_seconds` via `formatDuration`.

`catalog_season_name` is the single owner of the MAL-lowercase → `SeasonType`
vocabulary boundary; `next_season(year, season)` rolls a season forward, which is
what the upcoming sweep targets.

## What gets skipped

- **Hentai** — `is_hentai(info)` is true on a "Hentai" genre *or* the Rx rating.
  Checked before the `media_type` gate so a null-`media_type` hentai is still
  blacklisted. The same predicate drives both the fresh-scrape skip and the
  sweep's removal path, so the two cannot diverge.
- **`media_type=None` with `airing_status="Not yet aired"`** — skipped silently,
  not blacklisted. Blacklisting these permanently blocks rediscovery once the show
  actually airs. Only a null `media_type` with some *other* status is a true
  anomaly worth recording in `media_unwanted`.
- **`title=None`** — skipped silently. MAL routinely leaves the romanization field
  null on freshly-announced donghua and PV stubs and fills it in within hours; a
  `<mal_id:NNNN>` placeholder would pollute `media_unwanted` and block rediscovery.

## BFS and TERMINAL nodes

`search_title` walks the relation graph from a seed. It accepts a
`ProgressReporter` so user-scrape jobs stream progress to the bell, and
`seed_mal_id` + `seed_payload` so the sweep probe can start from a known mal_id
rather than a fuzzy `q=` lookup — that lookup drags unrelated franchises into the
catalogue when used for a known id.

Nodes reached through **identity-breaking** edges (`side_story`, `spin-off`,
`parent_story`, `other`, `summary`, `full_story`) are **TERMINAL**: the BFS records
their outgoing edges but does not recurse from them. That keeps the graph bounded
while still letting split-detection see a sub-chain leaking out of one anime row.

Relation edges are persisted **unfiltered**, including targets outside the local
catalogue, so a bridge edge activates later if the other side is scraped or merged
in. See [relations](relations.md) for what happens to the graph after capture.

---

**Why it is this way**
- [MAL API v2 migration](../../compound-docs/2026-07-18-v0.14.14-mal-api-migration.md) — endpoint/field mapping, ACL rationale, and the empty-`relation_cache` regression
- [Scraper quirks and field notes](../../compound-docs/2026-05-11-jikan-scraper-quirks.md) — upstream data oddities
- [Content pipeline](../../compound-docs/2026-05-09-v0.14.0-content-pipeline.md) — the original design
