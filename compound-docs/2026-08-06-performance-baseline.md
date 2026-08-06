---
date: 2026-08-06
version: v0.15.4
branch: v0.15.4-efficiency-improvements
topic: Performance baseline at prod catalogue scale — page waterfall, query costs, index audit
status: reference
---

# Performance baseline — prod catalogue, August 2026

A **reference** doc, not a change record: the numbers a future release re-runs to
tell progress from noise. Every figure here was taken against a production dump
restored into the dev container (see `phsar/scripts/CLAUDE.md`), which is the
whole reason it exists — the previous baselines in `2026-06-*` and `2026-07-*`
were measured on a 279-anime dev catalogue and several of them turned out to
understate prod by a wide margin.

**Nothing in this doc has been applied.** The candidates are measured so the
implement/skip decision is made on numbers.

## The short version

| | Candidate | Measured effect | Shape of the fix |
|---|---|---|---|
| **B2** | Sweep-tier count card | 44,106 → **1,368 buffers**, 40 → 4.7 ms | Pre-aggregated CTE; the media grain already uses it |
| **B7** | Anime genre filter, 3 genres | **77,762 buffers / 49.7 ms** vs 66 unfiltered | One majority-subquery per genre → one pass |
| **B13** | No HTTP compression anywhere | **7.2× / 6.6×** — 539 KiB on one request | Two lines in `main.py` |
| **B12** | Two list endpoints' fan-out | 104.6 → **18.0 ms**, 7 → 1 round trip | Flat projection, as `get_watchlisted_media_tags` does |
| **B1** | 384-float in the search `GROUP BY` | 54,778 → **15,185 buffers**, 43.6 → 23.9 ms | Group on the PK, aggregate the distance |
| **B11** | Autogenerate drops 2 live indexes | `alembic check` FAILS today | `__table_args__` + a CI step |
| **B3** | Three dead indexes | Plan **byte-identical** without them | One migration (shares B11's) |
| **B8** | Embedding re-encodes every search | **~30 ms** per search, no reuse | LRU on the folded query string |
| **B10** | 25 PK-duplicating indexes | **5.7 MB, 27 % of all index bytes** | Drop `index=True` on `BaseModel.id` |
| **B4** | Four discarded medians | 6.8 ms + 2,312 buffers + 4 round trips | `get_min_max` stops calling `get_field_stats` |
| **F1** | `/auth/validate` per nav **and** per hover | Blocks every navigation | Local `exp` decode |
| **F2–F4** | Client refetches | 626 KiB downloaded twice; options refetched per mount | Copy the `genres.ts` cache pattern |

Deliberately **not** worth doing: `score_top_percent` (B5), the spoiler
`IN`-list (B6), debouncing the filter writes — see §5.

---

## 1. Environment

Reproducing a number means reproducing the machine, so:

| | |
|---|---|
| **Host** | Apple M1, 8 cores (4 performance + 4 efficiency), 16 GB RAM, macOS 26.5.2 (25F84), arm64 |
| **Postgres** | `pgvector/pgvector:pg17` → PostgreSQL **17.10** (Debian), in Docker |
| **Container limits** | **none** — `NanoCpus=0`, `Memory=0`, so it may use the whole host |
| **PG settings** | `shared_buffers` 128 MB · `work_mem` 4 MB · `effective_cache_size` 4 GB · `random_page_cost` 4 · `max_parallel_workers_per_gather` 2 |
| **Extensions** | `vector` 0.8.5, `pg_trgm` 1.6 |
| **Python** | 3.12, asyncpg + SQLAlchemy AsyncSession |
| **Production, for contrast** | Coolify VM at **2 vCPU / 4 GB** |

> 🎯 **Buffer counts are the portable metric; wall-clock is not.** An 8-core M1
> with an unconstrained container and a fully-warm cache flatters every timing
> relative to the 2-vCPU VM. Buffers (and round-trip counts, and payload bytes)
> transfer; milliseconds only compare against other milliseconds *from this
> table*. All timings are warm, best-of-3 unless a range is given.

## 2. Catalogue scale

Restored from `phsar-20260806-113416-manual.dump`, `VACUUM ANALYZE`d, Alembic at
`d9e4a1c7b3f2`.

| Table | Rows | | Table | Rows |
|---|---|---|---|---|
| anime | 1,124 | | ratings | 800 |
| media | 4,495 | | watchlist | 341 |
| anime_search | 1,124 | | watch_events | 797 |
| media_search | 4,495 | | user_visible_media | 4,739 |
| jobs | 1,299 | | users | 4 |

Database **66 MB**, of which **21 MB is indexes**.

Heaviest user (`Priapos`, the one every per-user number below uses): **456
ratings**, **341 watchlist entries**, 1,773 visible media. No user is on
`spoiler_level = hide`.

Prior baselines were taken at 279 anime (v0.15.3) and ~800–1,400 media
(v0.14.5 – v0.14.11). This is **~4× the v0.15.3 anime grain**.

## 3. Why `/ratings` and `/watchlist` take 1–2 s

Decomposed rather than reported as one number, because the split is what a
future re-run compares against.

### The two fetches, as shipped

| Fetch | Rows | DB round trips | Server time | Response raw | gzipped |
|---|---|---|---|---|---|
| `GET /ratings/scores` | 456 | **7** | 136–311 ms | **625.7 KiB** | 86.7 KiB (7.2×) |
| `GET /watchlist/items` | 341 | **8** | 120–186 ms | **372.0 KiB** | 56.1 KiB (6.6×) |

The `/watchlist` **Statistics** subtab fires *both* (it lazily fetches
`/ratings/scores` on first open), so that view moves **~1.0 MB** of JSON today.

### Where the server time goes

For `/ratings/scores`, isolating the driving query from the eager-load fan-out:

| | Round trips | Time |
|---|---|---|
| Driving query alone (`SELECT ratings WHERE user_id`) | 1 | **10.4 ms** |
| \+ the three `selectinload` chains (media → anime / genres / studios) | 7 | **104.6 ms** (best) |
| \+ DTO construction (`_rating_to_score_item` × 456) | 7 | 136–311 ms |

**~90 % of the fetch cost is the fan-out and ORM hydration, not reading the
data.** The rows themselves are 10 ms.

### The four stages, ranked

1. **Transfer.** 625.7 KiB uncompressed on the ratings page alone, and **there
   is no HTTP compression anywhere in the stack** — no `GZipMiddleware` on
   FastAPI, no compression dependency, no `precompress` on adapter-node. At 7.2×
   this is ~539 KiB of avoidable bytes on one request. On a home connection to
   the VM this is the dominant term.
2. **Server time**, 120–310 ms per fetch, ~90 % of it fan-out + hydration.
3. **A blocking `/auth/validate` in front of everything** — see F1.
4. **Client parse + stats compute + the lazy ECharts chunk** (~330 KB gz,
   v0.15.2) on the two stats tabs. Not separately instrumented here.

## 4. Measured candidates

Each verified to return **identical results**, not merely a cheaper plan.

### B1 — drop the 384-dim vector from the anime-search `GROUP BY` ✅

`search_anime_aggregated` Phase A groups by `(anime.id, anime_search.title_embedding)`,
so a 384-float value sits in the hash/sort key of every input row. Grouping by
`anime.id` and ordering on `MIN(cosine_distance(...))` is equivalent —
`AnimeSearch` is 1:1 with `Anime`.

| | Buffers | Exec time | Aggregate |
|---|---|---|---|
| As shipped | **54,778** | 40.7 / 45.1 / 45.1 ms | GroupAggregate + full sort |
| Rewrite | **15,185** | 23.6 / 24.0 / 24.0 ms | HashAggregate |

**3.6× fewer buffers, ~1.8× faster.** Verified: **0 mismatched positions across
all 50 returned rows** (`FULL OUTER JOIN` on row number). Query used was a real
title search (`"hero academia"`) with a real embedding.

Note `min(vector)` does not exist in pgvector — the aggregate must wrap the
**distance**, not the embedding. The literal bonuses stay un-aggregated, being
functionally dependent on the grouped PK.

### B2 — sweep-tier count card: pre-aggregated CTE ✅ (largest verified improvement)

*Largest verified* rather than largest problem: B7 below is the more expensive
query, but a replacement for it was never prototyped, so only its cost is known,
not its saving.

`AnimeDAO.count_by_sweep_tier_priority`'s correlated `MIN(stable_check_count)`
*is* the compared expression in `_tier_bucket`, which emits one `WHEN` per
stabilize level — so the compiled SQL contains the scalar subquery three times
and Postgres plans three SubPlans with no cross-node caching.

| | Buffers | Exec time |
|---|---|---|
| Anime grain, as shipped | **44,106** | 38.5 / 46.9 / 39.9 ms |
| Anime grain, pre-aggregated CTE | **1,368** | 4.5 / 4.7 / 5.2 ms |
| Media grain (already the good shape, reference) | 621 | ~4 ms |

**32× fewer buffers, ~8.5× faster.** Counts identical in all 7 buckets
(airing_now 169 · weekly_cycle 477 · long_cycle 238 · archival_cycle 209 ·
stabilizing_0/1/2 = 14/9/8).

> **v0.15.3 measured 6,592 buffers on the dev catalogue and projected 13,247 for
> the settled state. The real figure is 44,106.** The correlated subquery is
> evaluated per anime row and each evaluation scans that anime's media, so it
> grows faster than the catalogue does — the clearest argument in this doc for
> why the dev DB had to be replaced.

Two things the rewrite must keep right:
- **Do not `coalesce` the pre-aggregated `min_stable`.** The shipped scalar
  subquery yields NULL for a media-less anime, which falls through to
  `long_cycle`; coalescing to 0 buckets it as `stabilizing_0`.
- `admin_stats_service`'s own docstring says "revisit if any single query
  crosses ~10 ms". At ~40 ms this crosses it 4×, on a card that loads with every
  admin Overview — a tab that already issues 17 round trips.

### B7 — the anime-view genre filter is superlinear in genres selected ✅ (worst query measured)

`apply_anime_having_filters` emits **one correlated majority-subquery per
selected genre** — each a 2-join `COUNT` over `media × media_genre × genre`,
re-evaluated per group, compared against `media_count`.

| Genres selected | Buffers | Best time |
|---|---|---|
| 0 (unfiltered browse) | **66** | 0.09 ms |
| 1 | 10,645 | 4.6 ms |
| 2 | 59,241 | 23.4 ms |
| 3 | **77,762** | **49.7 ms** |

**This is the most expensive query in this document** — more than B1 (54,778)
or B2 (44,106) — and it fires on an ordinary user action, ticking genre chips
on the search page. The growth is worse than linear: each added genre both adds
a SubPlan and widens the set each existing SubPlan is evaluated over.

Unmeasured but implied: the media-view genre filter uses a single
`GROUP BY … HAVING count(distinct genre)` subquery instead (`search_filters.py:159-170`)
and does not have this shape. The anime side is the outlier, not the norm.

### B8 — `generate_embedding` re-encodes identical queries ✅

Sentence-transformers `encode()` runs on the request path for every text search.

| | min | median | max |
|---|---|---|---|
| 10 distinct queries | 29.9 ms | **31.1 ms** | 164.7 ms |
| the same query ×10 | 28.9 ms | **30.2 ms** | 31.8 ms |

Repeat calls cost the same as fresh ones, confirming there is no memoization
today. **~30 ms per search**, which is larger than the entire 20 ms that B1's
rewrite saves. An LRU keyed on the case-folded query string is a handful of
lines and is safe by construction: `generate_embedding` is deterministic and
the model version is fixed at deploy. (The max column is M1 efficiency-core
scheduling noise, not a real tail — the median is the number to use.)

### B11 — `alembic revision --autogenerate` would drop two live indexes ✅

Filed originally as "model/migration drift". It is worse than drift, and
`alembic check` (which exists in this Alembic version, and takes seconds)
reports it outright:

```
FAILED: New upgrade operations detected:
  remove_index  ix_anime_freshness_last_checked_at
  remove_index  ix_media_freshness_last_checked_at
  remove_index  ix_media_airing_now            ← load-bearing
  remove_index  ix_media_main_aired_from       ← load-bearing
  remove_index / add_index  ix_jobs_scrape_query   (churn, see below)
```

`ix_media_airing_now` and `ix_media_main_aired_from` are the two indexes root
`CLAUDE.md` documents as backing `select_due_media_for_sweep` — they exist only
in migrations, never in `__table_args__`, so **the next autogenerated migration
silently drops them** unless someone reads the diff carefully. The two freshness
entries happen to coincide with what B3 wants dropped anyway; that is luck, not
design.

`ix_jobs_scrape_query` is a third case: it exists in both, but the model
declares it via `func.lower(...)` where the migration used a textual index
element, so autogenerate proposes a drop-and-recreate on **every** run.

Two consequences worth separating: the models need `__table_args__` for the four
missing indexes (same migration as B3, which removes two of them), and
**`alembic check` is a one-line CI step** — it answers the v0.15.3 follow-up
("CI never replays the chain") far more cheaply than swapping `create_all` for
`alembic upgrade head`.

### B3 — three dead indexes ✅ (the prod-snapshot plan check is now done)

The v0.15.3 follow-up was explicitly *"gated on confirming the plan against a
prod snapshot"*. Confirmed: `EXPLAIN (ANALYZE, BUFFERS)` of
`select_due_media_for_sweep` is **byte-identical with both freshness indexes
dropped** (inside a rolled-back transaction) — same cost `912.03..918.71`, same
627 buffers, same Seq Scan on media + quicksort.

| Index | Size | Status |
|---|---|---|
| `ix_media_freshness_last_checked_at` | 88 kB | never chosen; 0 lifetime scans in prod |
| `ix_anime_freshness_last_checked_at` | 56 kB | same |
| `ix_watch_events_watched_at` | 40 kB | no reader exists (v0.14.10 note) |

Size is not the point: `last_checked_at` is the only indexed **mutable** column
on either sidecar, so indexing it makes every sweep write a non-HOT update
(`n_tup_hot_upd = 0` across ~5.1k lifetime updates, measured on prod).
**Unblocked — one migration drops all three.**

Incidental finding from the same plan: **only 261 media are currently due**,
well under `JOBS_SWEEP_MAX_PER_RUN = 500`. v0.15.3 recorded prod as
over-subscribed at ~652/night; the 180-day archival tier that shipped in that
release is what closed the gap. The cap is no longer binding.

### B4 — `/filters/options?view_type=media` computes four medians and discards them ✅

`get_min_max` delegates to `get_field_stats`, which runs **two** queries per
field and keeps two of five results — the `percentile_cont(0.5) WITHIN GROUP`
median is thrown away one line later.

| Field | min/max query | discarded median |
|---|---|---|
| scored_by | 1.40 ms | 1.76 ms |
| episodes | 1.56 ms | 1.50 ms |
| duration_seconds | 1.53 ms | 1.80 ms |
| total_watch_time (CASE expr, unindexable) | 1.46 ms | 1.70 ms |

**~6.8 ms + ~2,312 buffers + 4 round trips wasted per request.** Measured
end-to-end, the endpoint costs:

| | Backend round trips | Time | Payload |
|---|---|---|---|
| `view_type=anime` | 8 | 66.2 ms | 11.8 KiB (4.4 KiB gz) |
| `view_type=media` | **15** | 45.6 ms | 11.8 KiB (4.4 KiB gz) |

So the four discarded sorts are **4 of the media path's 15 round trips**, and a
`get_min_max` that doesn't call `get_field_stats` is the whole fix. Note the
media path has nearly twice the round trips but *less* wall-clock than the anime
path — the anime path's two full `GROUP BY media.anime_id` passes
(`_get_anime_majority_genres`, `_get_anime_aggregated_ranges`) dominate there.
The payload is tiny either way, so this is a round-trip problem, not a
bytes problem — B13 does nothing for it, but F2 (caching it client-side) would.

### B10 — 25 PK-duplicating indexes ✅

`BaseModel` declares `id = Column(Integer, primary_key=True, index=True)`, so
every table carries a second btree identical to the primary key's own unique
index.

**25 indexes, 5,744 kB — 27 % of all index bytes in the database.** Pure write
amplification: every INSERT maintains both.

### B12 — flat projection instead of the selectinload fan-out ✅

`/ratings/scores` and `/watchlist/items` build wide DTOs of **scalars** but pay
6–7 `selectinload` round trips plus full ORM hydration of
Ratings/Watchlist + Media + Anime + Genre + Studio.
`WatchlistDAO.get_watchlisted_media_tags` already demonstrates the alternative:
one flat `select(...)` of columns, zero hydration.

Prototyped for `/ratings/scores` (scalars + `array_agg` for genres/studios):

| | Round trips | Best time |
|---|---|---|
| As shipped | 7 | **104.6 ms** |
| Flat projection | **1** | **18.0 ms** |

**5.8× faster, 87 ms saved per request**, before the DTO build. Caveat: this
measured the *fetch*; proving the full `RatingScoreItem` can be assembled from
it (and keeping `_to_item`'s `lazy="raise"` guard meaningful) is implementation
work, not measurement.

### B13 — no HTTP compression exists ✅

Verified absent everywhere: no `GZipMiddleware` in `main.py`, no compression
dependency in `requirements.txt`, no `precompress` in the adapter-node config.

| Endpoint | Raw | gzip -6 | Ratio |
|---|---|---|---|
| `/ratings/scores` | 625.7 KiB | 86.7 KiB | **7.2×** |
| `/watchlist/items` | 372.0 KiB | 56.1 KiB | **6.6×** |
| both (watchlist Statistics tab) | 997.7 KiB | 142.8 KiB | 7.0× |

Two lines in `main.py`, registered **between** `MaintenanceGateMiddleware` and
`CORSMiddleware` so the documented CORS-outermost invariant survives. Highest
ratio-to-effort item in this doc.

### F1 — `/auth/validate` on every navigation *and* every link hover ✅ (source-verified)

Not timed; established from the code, which is sufficient because it is a
question of *how many requests*, not how fast one is:

- `routes/+layout.ts:19` `await`s `api.get('/auth/validate')` inside the root
  `LayoutLoad`, so it **blocks** every navigation.
- The load touches `url.pathname`. In `@sveltejs/kit` **2.55.0**,
  `make_trackable` (`src/utils/url.js`) lists `pathname` in
  `tracked_url_properties`, and each such getter calls the whole-URL
  `callback()` — so the root layout load is invalidated by **any** URL change,
  including query-param-only ones like `?tab=ratings` → `?tab=stats`.
- `app.html:14` sets `data-sveltekit-preload-data="hover"`, and preloading runs
  the universal `load` — so **hovering** any internal link fires one too.

### F2–F4 — client refetches ✅ (counted from the call sites, costed from §4)

These are request *counts*, so the code is the evidence; the per-request cost
comes from the endpoint measurements above.

| | What repeats | Cost of one | Why |
|---|---|---|---|
| **F2** | `GET /filters/options` on every `SearchBar` mount and every anime↔media toggle | 8–15 backend round trips, 46–66 ms | `SearchBar.svelte:198` has the only call site, but the component mounts on **both** `/` (`+page.svelte:26`) and `/search` (`search/+page.svelte:171`), so every home↔search hop refetches. No store, no cache — for data that changes only when the catalogue does |
| **F3** | `GET /ratings/scores` from **three** independent consumers | 7 round trips, **625.7 KiB**, 136–311 ms | `routes/ratings/+page.svelte:39`, `routes/watchlist/+page.svelte:75`, `lib/components/RatingNeighbors.svelte:61`. No shared store exists (`lib/stores/ratingsFilter.ts` is UI state, not data), so `/ratings` → `/watchlist?tab=stats` downloads the same 626 KiB twice |
| **F4** | `refreshTags()` on every `/watchlist` mount | one small query | `routes/+layout.svelte:95` already fetches it at login into a cached store; `routes/watchlist/+page.svelte:45` calls it again unconditionally on each mount |

`lib/stores/genres.ts` is the pattern all three should copy — a module-level
promise that both coalesces concurrent callers and caches for the session, and
clears itself on failure so a later mount retries.

## 5. Measured and NOT worth acting on

Recording these so they aren't re-investigated:

- **B5 — `score_top_percent`.** Anime (`rank()` window over all scored anime)
  **572 buffers**; media (`count(*) FILTER`) **573 buffers**. Both are one seq
  scan of `media` per detail-page load, low single-digit ms. The v0.14.11 note
  ("sub-ms at ~1.4k media; precompute at 10k+") still holds at 4,495 media.
  **Leave it alone.**
- **B6 — the spoiler `IN (…)` list.** Real, but not currently reachable: no user
  is on `spoiler_level = hide`. The largest cache is 1,773 media, so a user who
  flipped to `hide` would inline 1,773 bind parameters — comfortably under
  asyncpg's 32,767 ceiling. Worth fixing as a shape, not as a live cost.
- **Debouncing the new sessionStorage filter writes.** All 19 write sites across
  the three stores are discrete user actions (pills, chips, `Select`, sort
  headers); no text input is bound to any of them, so there is no keystroke
  path. Debouncing would add a lost-write window at navigation for no gain.

## 6. Not measured

Named so the coverage claim is honest. Two items, both for the same reason —
they need a harness this doc doesn't have, not more time:

- **B9 — connection pool.** `create_async_engine(DATABASE_URL, echo=…)` sets no
  pool parameters at all: no `pool_size`, no `max_overflow`, no
  `pool_pre_ping`. Pool behaviour only manifests under concurrency, so measuring
  it needs a load harness; against a 4-user dev DB with no traffic there is
  nothing to see. `pool_pre_ping` in particular is a stale-connection
  *reliability* fix for the VM, not a latency knob — it should be argued, not
  benchmarked.
- **The client half of §3's stage 4** — JSON parse, `ratingStats` /
  `watchlistStats` compute, and the lazy ECharts chunk (~330 KB gz). Needs a
  real browser session against a logged-in account; the restored users carry
  production password hashes, so this would mean writing a known password into
  real user rows. Left for a deliberate in-browser pass instead.

Everything else originally on the candidate list is now measured above.

## 7. Reproducing this

1. Rebuild the dev DB per `phsar/scripts/CLAUDE.md` (**postgresql@17 on PATH**,
   `VACUUM ANALYZE`, merge `_jobs_dump_staging`).
2. SQL: compile the production statement via SQLAlchemy with
   `compile_kwargs={"literal_binds": True}` rather than hand-writing it — that
   is what keeps a measurement honest about the query the app actually sends —
   then `EXPLAIN (ANALYZE, BUFFERS)` it, best-of-3.
   - Two literal-binds artifacts to expect: `ESCAPE '\\'` needs unescaping for
     psql, and a 384-dim vector inlines to an ~8 kB statement.
3. Equivalence: `FULL OUTER JOIN` the two result sets and assert zero
   mismatches — for ordered queries, join on `row_number()`, not on the key.
4. Endpoints: call the service function in-process with a
   `before_cursor_execute` listener to count round trips, and `json.dumps` +
   `gzip.compress` the DTO list for payload bytes. This avoids needing a token
   for a restored user, and separates query time from serialization.
5. Index-drop checks: `BEGIN; DROP INDEX …; EXPLAIN …; ROLLBACK;` — the plan is
   the evidence. Index *usage* counters can't come from a restore
   (`pg_stat_user_indexes` resets); those must come from live prod.
6. Model/migration agreement: `alembic check` from `phsar/`. Seconds, no file
   written, and it names each drifting index.

Two habits worth keeping from this round. **Measure the shape, not one point** —
B7 only looked serious once it was run at 0/1/2/3 genres, and a single
three-genre number would have read as "50 ms, fine". And **prefer the median
over best-of-N for CPU work**: B8's first pass produced a 337 ms reading that
was pure efficiency-core scheduling noise and would have made a ~30 ms cost look
like a crisis.
