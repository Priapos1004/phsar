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

**Every candidate below was implemented in v0.15.4** except the three §5 rejects.
The baseline figures are left exactly as measured — they are the point of the doc,
and the "landed" column is what a future release compares its own re-run against.
The decisions and gotchas from applying them live in the companion
[2026-08-06-v0.15.4-efficiency-improvements.md](2026-08-06-v0.15.4-efficiency-improvements.md).

## The short version

| | Candidate | Baseline → predicted | **Landed (v0.15.4)** |
|---|---|---|---|
| **B2** | Sweep-tier count card | 44,106 → 1,368 buffers, 40 → 4.7 ms | **629 buffers, 4.5 ms** — beat the prediction; all four atoms moved into the CTE, not just `min_stable` |
| **B7** | Anime genre filter, 3 genres | 77,762 buffers / 49.7 ms | **16,191 / 11.2 ms**, and wall-clock now **flat** in genre count (12.9 / 10.5 / 11.2 at 1/2/3) |
| **B13** | No HTTP compression anywhere | 7.2× / 6.6× | **exactly as predicted**; backup download opted out via `Content-Encoding: identity` |
| **B12** | Two list endpoints' fan-out | 104.6 → 18.0 ms, 7 → 1 round trip | **7 → 1**, fetch **21.7 ms** (a scoped pre-aggregation beat the first cut's 25.9) |
| **B1** | 384-float in the search `GROUP BY` | 54,778 → 15,185 buffers, 43.6 → 23.9 ms | **16,239 buffers, 22.7 ms**; GroupAggregate + sort → HashAggregate |
| **B11** | Autogenerate drops 2 live indexes | `alembic check` FAILS | **green**, and enforced in CI against a chain-replayed DB |
| **B3** | Three dead indexes | Plan byte-identical without them | **confirmed identical** (cost `912.03..918.71`, 621 buffers), dropped |
| **B8** | Embedding re-encodes every search | ~30 ms per search, no reuse | **0.10 ms on a hit** (310×); query and document caches split so a sweep can't evict queries |
| **B10** | 25 PK-duplicating indexes | 5.7 MB, 27 % of all index bytes | **5,744 kB reclaimed** exactly; 21,872,640 → 15,990,784 B |
| **B4** | Four discarded medians | 6.8 ms + 2,312 buffers + 4 round trips | **15 → 11 round trips**, 0 `percentile_cont`; payload identical |
| **F1** | `/auth/validate` per nav **and** per hover | Blocks every navigation | **zero requests** — local `exp` decode via `sessionRemainingMs` |
| **F2–F4** | Client refetches | 626 KiB twice; options per mount | **cached** (`filterOptions`, `ratingScores`); `/watchlist` drops its tags fetch |

> ⚠️ **Buffer figures: extract the TOP-LEVEL node, not the sum.** `EXPLAIN
> (ANALYZE, BUFFERS)` reports buffers **cumulatively up the plan tree**, so a
> parent re-counts its children and summing every `Buffers: shared hit=` line
> inflates the total several-fold. Both columns above use the top node. A harness
> that sums will look internally consistent and still be incomparable with this
> table — it happened during v0.15.4 and cost a re-measurement.

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

## 3. Why `/ratings` and `/watchlist` took 1–2 s (pre-v0.15.4)

Decomposed rather than reported as one number, because the split is what a
future re-run compares against.

### The two fetches, as measured

| Fetch | Rows | DB round trips | Server time | Response raw | gzipped |
|---|---|---|---|---|---|
| `GET /ratings/scores` | 456 | **7** | 136–311 ms | **625.7 KiB** | 86.7 KiB (7.2×) |
| `GET /watchlist/items` | 341 | **8** | 120–186 ms | **372.0 KiB** | 56.1 KiB (6.6×) |

**After v0.15.4** (same user, same technique). The raw bytes are unchanged by
design — the DTO contract didn't move — but they now go over the wire gzipped:

| Fetch | DB round trips | Fetch | + DTO build | On the wire |
|---|---|---|---|---|
| `GET /ratings/scores` | **1** | 21.7 ms | 18.4 ms | 86.6 KiB |
| `GET /watchlist/items` | **1** | 11.8 ms | 10.1 ms | 56.0 KiB |

Two things a future re-run should know. **The DTO build is now ~40 % of what's
left** (456 Pydantic constructions ≈ 18 ms), so it, not the query, is the next
target on this path. And the fan-out figure below inverted: what was ~90 % of the
cost is now one statement, which is why §3's stage ranking needs re-deriving
before it's trusted again.

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

1. **Transfer.** 625.7 KiB uncompressed on the ratings page alone, and at the time
   of measurement **no HTTP compression anywhere in the stack** — no
   `GZipMiddleware` on FastAPI, no compression dependency, no `precompress` on
   adapter-node. At 7.2× that was ~539 KiB of avoidable bytes on one request, and
   on a home connection to the VM the dominant term. *Closed by B13.*
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

**Landed:** 16,239 buffers / 22.7 ms, HashAggregate. Re-verified at 0 mismatched
positions across all 50 rows on three query shapes — a literal substring match, a
typo'd query (pg_trgm bonus), and a purely thematic one where ordering rests
entirely on the aggregated distance. One constraint the prediction didn't name:
the aggregate must also **ignore group size**, since the query groups over the
joined media rows — `min`/`avg` qualify, `sum` would rank a 6-media franchise six
times worse for being a franchise.

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

**Landed better than predicted: 629 buffers / 4.5 ms, and SubPlan mentions 18 → 0.**
The prediction assumed only the correlated `MIN` moved; in fact `_sweep_atoms` has
exactly one consumer, so the two `EXISTS` and the correlated `MAX` roll up from the
same `GROUP BY media.anime_id` and went into the CTE too — one pass replacing four
correlated constructs. All 7 buckets identical at **both** grains, both still
summing to the catalogue totals.

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

### B7 — the anime-view genre filter was superlinear in genres selected ✅ (worst query measured)

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

### B8 — `generate_embedding` re-encoded identical queries ✅

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

**Landed:** distinct 31.5 ms median, repeat **0.10 ms** — a 310× hit. One thing the
prediction missed: a single shared LRU is the wrong shape, because document text
(titles, descriptions, notes) has a structurally 0 % hit rate and a sweep inserts
thousands of such keys, so it evicted every query — leaving the cache coldest right
after the nightly window. Split into a memoized `generate_query_embedding` and an
uncached `generate_embedding`, both over one shared case-fold.

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

**Landed:** green, with the check in CI. Two things the plan didn't anticipate.
The step needs its **own** database: run against the test DB and it compares
`create_all`'s metadata to a schema built from that same metadata, passing however
far the migrations have drifted — so it creates a throwaway `migrationcheck` and
`alembic upgrade head`s into it, which is also the only place CI now replays the
chain from empty. And `ix_jobs_scrape_query` had to be declared with raw SQL in
Postgres's own normalized spelling (`TRIM(BOTH FROM …)`, explicit `::text`),
because autogenerate diffs index expressions as reflected strings and the
`func.*` form can never match. That leaves the expression written twice, in two
languages, so `JobDAO.scrape_query_expr()` names it once and a test asks Postgres
(EXPLAIN, seqscan off) whether the index is still usable.

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

**Landed** in migration `80bdabf2d417`; the plan re-checked after the drop is
byte-identical (same cost `912.03..918.71`, same 621 buffers, same Seq Scan +
quicksort, same 261 rows due).

Incidental finding from the same plan: **only 261 media are currently due**,
well under `JOBS_SWEEP_MAX_PER_RUN = 500`. v0.15.3 recorded prod as
over-subscribed at ~652/night; the 180-day archival tier that shipped in that
release is what closed the gap. The cap is no longer binding.

### B4 — `/filters/options?view_type=media` computed four medians and discarded them ✅

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
`get_min_max` that doesn't call `get_field_stats` is the whole fix.

**Landed:** media 15 → **11** round trips, 4 → 0 `percentile_cont`, payload
identical across all 17 keys at both view types. `get_field_stats` was deleted
outright — no other caller, no test, and its two validation raises (the only thing
between a field-name string and a `func.min` over it) were uncovered as a result.
A further **11 → 8** is available from a `MediaDAO.filter_bounds()` selecting all
four min/max pairs in one statement; deferred. Note the
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

**Landed:** exactly 5,744 kB reclaimed (total index bytes 21,872,640 →
15,990,784). The fix is at the base class plus the one table that doesn't inherit
it (`user_visible_media`), not 25 per-table edits.

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

**Landed:** 7 → 1 round trip, fetch **21.7 ms**, DTOs identical field-for-field
(456 × 36 and 341 × 25). Three things the prototype didn't cover:

- **`LEFT JOIN LATERAL` is not the fix** — Postgres plans it as the same ~900
  subplans, identical buffers, no win. Grouping over the whole catalogue is
  *worse* (17.2 ms). The win is aggregating **scoped to the requesting user's
  media**: 9.3 → 5.0 ms for the array half, and flat in page size.
- The rewrite surfaced a **latent ordering bug**: both queries ordered by
  `modified_at` alone, which ties heavily (456 ratings over 369 distinct values;
  341 watchlist entries over 156, biggest group 12) because a bulk write stamps
  one timestamp across an anime. Two *paginated* queries elsewhere had the same
  shape, where a tie can show a row on page 1 and again on page 2.
  `base_dao.recency_order` now appends a PK tiebreak everywhere.
- Equivalence had to be judged **modulo those ties** — comparing raw row order
  reports a false failure. Compare the sequence of tie groups instead.

### B13 — no HTTP compression existed anywhere ✅

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

**Landed** with ratios reproduced to the tenth of a KiB. `compresslevel=6` rather
than starlette's default 9 (measured 41.7× vs 42.7× for 2.8× the CPU — it
compresses synchronously on the event loop, ~1.4 ms for a 510 KiB body here). The
backup download needed an explicit opt-out: starlette decides on size and
content-type alone, so a multi-GB `pg_dump -Fc` archive — already zlib-compressed
— would be streamed through gzip for ~0 % gain and lose its `Content-Length`.
`Content-Encoding: identity` on that one response is the opt-out.

### F1 — `/auth/validate` ran on every navigation *and* every link hover ✅ (source-verified)

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

**Landed:** the guard decodes the token's own `exp`, synchronously — zero requests.
`GET /auth/validate` now has no frontend caller. The reusable primitive turned out
to be the remaining-ms **number**, not an is-live boolean: extracting the boolean
first left `evaluateSession` still computing `exp * 1000 - now` itself, which
forced a cast. Worth generalising — *a cast beside a freshly extracted guard
usually means the extraction stopped one level too high.*

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

**Landed** as `filterOptions.ts` (keyed by `view_type`, self-clearing on the
`librarySaved` bump) and `ratingScores.ts`. Two corrections to the analysis above:

- **Coalescing alone would not have fixed F3.** Those visits are sequential, not
  concurrent, so it had to be a real cache — which trades away the one safety a
  per-mount fetch has for free. Buying it back is five explicit
  `invalidateRatingScores()` calls at the rating-write sites, deliberately not
  centralized in `api.ts` (that layer is kept dumb; it has no global 401 handler
  for the same reason).
- **F4's fetch was not redundant.** `Tag.entry_count` / `anime_count` are
  server-side counts that genuinely go stale as entries change. Deleting the call
  would have shipped stale badge counts. Their only consumer is
  `WatchlistTagsTab`, which mounts on demand — so the call moved *there*, and
  `/watchlist` drops the request while the counts stay correct.

A shared cache factory across all three was considered and rejected: the common
body is ~8 lines, a generic keyed cache is ~14 on its own, and `genres.ts` can't
join it (writable store, `Promise<void>`, swallows failures by design).

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

Everything else originally on the candidate list is now measured above. **Both of
these remain open after v0.15.4** — neither was implemented and neither reason has
changed.

### Levers found while implementing, deliberately not pulled

Recorded here so the next pass starts from them rather than re-deriving:

- **`/ratings/scores` DTO construction is now the bigger half.** With the fetch at
  21.7 ms and 456 Pydantic builds at 18.4 ms, the query is no longer the target on
  this path.
- **`/filters/options` 11 → 8 round trips** via a `MediaDAO.filter_bounds()` that
  selects all four min/max pairs in one statement (see B4).
- **The anime genre filter's nested loop** — the planner underestimates
  `genre.name IN (...)` selectivity ~7× and probes `media` by PK for ~10.4k of its
  buffers; `enable_nestloop=off` cuts it to ~2,020. Two rewrites failed to move the
  plan; the lever is getting `anime_id` onto the genre rows (see B7).
- **CI builds its test schema from `create_all`, not the migration chain**, which
  is why `alembic check` needs a second database. Building `testdb` with
  `alembic upgrade head` would delete that plus the `create_all` block and the
  `alembic stamp head` hack, and run the whole suite against a migration-built
  schema — at the cost of a broken migration failing everything.
- **The backup tests dominate local `pytest`** now that the dev DB is a 66 MB
  restored dump: ~36 of them shell out real `pg_dump`/`pg_restore` against it, so
  the suite takes ~16 min locally (CI is unaffected — its DB is empty). Scoping
  them to a small dedicated database would fix it.

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

Four more, learned while applying these:

7. **Take buffers from the TOP-LEVEL plan node.** EXPLAIN reports them
   cumulatively up the tree, so summing every `Buffers:` line inflates the figure
   several-fold — internally consistent, and incomparable with this table.
8. **A cheaper plan is not the same claim as an identical result**, and for an
   ordered query the equivalence check must be judged modulo whatever the ORDER BY
   actually guarantees. Two of these rewrites returned identical rows in a
   *different* order because the sort key ties; comparing raw order reports a
   false failure, and comparing nothing at all hides a real one.
9. **Verify a guard test by breaking the thing it guards.** Two invariants here
   got tests; both were watched going red against an injected fault. A test for a
   subtle invariant is worth nothing until you've seen it fail.
10. **A test that reads the catalogue only passes where the catalogue exists.**
    Asserting `min`/`max` were non-null over `media` passed against this restored
    dump and failed in CI, whose DB is empty. Seed sentinel values instead.
