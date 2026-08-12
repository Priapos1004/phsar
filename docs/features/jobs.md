# Background jobs

Everything slow runs as a job: catalogue scrapes, the nightly sweeps, backups.
Current behaviour; decisions are in the linked compound-docs.

**Code**: `services/job_worker.py` (the worker) → `services/scrape_dispatcher.py`,
`services/seasonal_sweep_dispatcher.py`, `services/backup_dispatcher.py` (handlers)
→ `services/progress_reporter.py` (progress) → `models/job.py`, `daos/job_dao.py`.

## The worker

One asyncio FIFO worker drains the `jobs` table. It claims rows with
`with_for_update(skip_locked=True)`, and a `wakeup` event gives sub-second pickup
with a 60s wall-clock fallback — shortened to 2s during maintenance, because a
restore lifts the gate without calling `notify()`, so the idle poll has to catch
that transition itself.

Handlers are registered `JobKind → handler` from the `main.py` lifespan. Each job
runs in its own sequential sessions (claim-tx, then work-tx in a fresh session):
two sequential sessions rather than nested ones, because concurrent sessions on a
small asyncpg pool deadlock. Savepoints nested *inside* the sweep are the
deliberate working pattern, not the hazard.

Concurrency is deliberately one. Parallel jobs would only fragment the 1 req/s
MAL budget, so the per-user cap (`JOBS_PER_USER_LIMIT`) bounds *queue depth*, not
parallelism.

**Crash recovery**: `JobDAO.reap_orphans` runs at startup and flips any `running`
row to `failed`, so a mid-job restart can't strand a row forever.

## Job kinds

| Kind | Does | Brackets maintenance |
|---|---|---|
| `user_scrape` | One BFS scrape from a query or a seeded mal_id | no |
| `update_sweep` | Nightly per-media refresh + relations probe | yes |
| `seasonal_sweep` | Scrapes the current season | yes |
| `upcoming_sweep` | Scrapes the next season | yes |
| `backup` | `pg_dump` + verify + retention | no |
| `restore` | Restores a dump | yes (request-scoped) |

`restore` has no dispatcher and is never queued or drained: its row is written
afterwards with its final status already set, as an audit record. Every other kind
is a real worker kind.

`backup` doesn't bracket because `pg_dump` runs on an MVCC snapshot — concurrent
user writes are safe.

## Failure handling

Two stamps on `result_summary` drive the UI:

- `retryable = not isinstance(failure, PermanentPhsarError)` — the bell shows a
  retry button only when retrying could plausibly work.
- `error_category` via `classify_error` — `upstream_outage` (httpx 5xx and 429,
  timeouts, network errors, `TransientUpstreamError`), `backup_disk_full`,
  `backup_corrupt`. 429 belongs here specifically so sustained throttling trips
  the circuit breaker rather than grinding through the batch.
  The bell renders friendly copy per category; anything uncategorized falls
  through to `error_message`, which is already friendly for domain errors.

Three guards keep a job from being stranded in `running` when something fails
*after* the dispatcher returned: the job uuid is captured as a string right after
claim (so the failure logger never touches ORM attributes on a poisoned session),
the rollback is itself wrapped, and an outer catch-all routes plumbing failures
through `mark_failed`.

## result_summary versioning

`result_summary` shapes change over time and the frontend must render historical
rows. `JOB_KIND_VERSIONS` in `core/job_versions.py` is the runtime source of
truth; every Job-construction site goes through `make_job(kind, **kw)`, which
stamps `job.version` from it. The frontend dispatches on `(kind, version)`.

Bump a kind's integer when its shape changes. Purely **additive keys with a safe
default do not bump** — the frontend simply omits them on older rows.

The two admin endpoints serve **different amounts** of the same summary:
`GET /admin/jobs/{uuid}` returns it whole, and the Jobs Log list strips the keys
only the detail page renders, because they dominate an `update_sweep` row on an
endpoint that is polled. `LIST_OMITTED_SUMMARY_KEYS` in `core/job_versions.py`
decides which.

## The update sweep

Selection is **per media**, not per anime: `AnimeDAO.select_due_media_for_sweep`
picks due media, the dispatcher groups them by parent anime and refreshes only
those, so settled older members of a still-airing franchise are not refreshed
nightly.

Two clocks: `MediaFreshness` (`last_checked_at` + `stable_check_count`) is the
per-media *refresh* clock; `AnimeFreshness` is the per-anime *probe* clock.

### What counts as due

Four independent predicates in `AnimeDAO.select_due_media_for_sweep`, each a direct
test on the media row plus its freshness sidecar:

| Tier | Selects |
|---|---|
| airing now | `airing_status = 'Currently Airing'` |
| stabilizing | `stable_check_count < SWEEP_STABILIZE_THRESHOLD` (3) |
| recent main | a main entry with a recent premiere, weekly |
| long tail | everything else, on a per-row window |

The long tail uses a **per-row window rather than a fifth tier**: one `CASE`
compares `last_checked` against `SWEEP_ARCHIVAL_DAYS` (180) for media premiered over
`SWEEP_ARCHIVAL_AGE_YEARS` (10) ago and `SWEEP_LONG_TAIL_DAYS` (90) otherwise. A
separate fifth branch would need tier 4 narrowed by `not_(archival)` to avoid
shadowing it, and that coupling is easy to forget. The single predicate also makes
NULL correct for free — an undated media fails the `WHEN` and lands on 90 days.

`LIMIT` bounds MAL calls, since media are the real 1 req/s cost unit. The long tail
is the terminal bucket — everything drains into it and nothing leaves — so it is the
only tier whose nightly cost grows without bound.

**Step 1** refreshes each due media in one MAL call, diffs volatile fields,
advances that media's freshness counter, and rewrites its relation edges.
Reclassification and airing detection still run over the anime's **full** media
set, so umbrella drift sees the whole franchise even when only some members were
refreshed.

**Step 2** probes relations for anime that are settled (not airing, stable count
past `SWEEP_STABILIZE_THRESHOLD`, last probe ≥ 7 days ago) and attaches whatever
is discovered. The 7-day floor keeps probing roughly weekly even though
media-level selection can re-touch an anime on consecutive nights.

Each anime commits twice, inside its own try/except: step 1 always commits (so a
crash mid-sweep keeps the diff work, and one bad MAL response fails only that
anime), step 2 only on probe success (so a failure leaves the probe clock
untouched and the anime re-selects).

**Stability counter**: resets when the media is airing or a volatile field moved
by at least `_SCORE_STABILITY_THRESHOLD` (0.05 on the weighted score
`score * log10(scored_by + 1)`), else climbs. The threshold matters because
without it a single new vote per night on a million-vote anime resets the counter
forever. None↔value transitions bypass it — first votes arriving is structural.

**Circuit breaker**: per-anime isolation is right for one bad row and catastrophic
when MAL is entirely down, since every anime then pays the full retry budget while
maintenance is held. The dispatcher counts *consecutive* step-1 failures
categorized `upstream_outage`, resets on any success, and aborts at
`JOBS_SWEEP_ABORT_AFTER_CONSECUTIVE_FAILURES` (default 10) by raising
`TransientUpstreamError`. The abort carries the partial summary gathered so far,
so the failed job's detail page still shows real counters instead of only a
banner. A non-upstream failure neither trips nor resets it. Pinned end to end
(dispatcher raise → partial-summary carry → worker flag-clear → seeded
`result_summary`) in `test_update_sweep.py` and `test_job_worker.py`.

### Genre and studio drift

Both apply additions *and* removals, but they are not symmetric:

- **Unknown genre tags are never auto-created.** The seed table is the deliberate
  source of truth for the user-facing taxonomy. They surface in the sweep-level
  `unknown_genre_tags` aggregate, which tints the Jobs Log row amber for review.
- **Unknown studios auto-create a row.** Studios are a discovered taxonomy, not a
  curated one.

Drift must actually be written, with the audit log as the rollback path. Reporting
drift without applying it re-reports the same drift every sweep.

## Season sweeps

`seasonal_sweep` and `upcoming_sweep` share one dispatcher; `job.kind` picks the
season. MAL v2 has no `/seasons/now`, so the current season is computed from the
clock, and the upcoming sweep targets `next_season` of it.

The pass is pure discovery: paginate the season, dedupe against
`Anime.mal_id ∪ Media.mal_id ∪ MediaUnwanted.mal_id` (plus per-run dedupe, since
MAL repeats titles across pages), then bulk-insert one system `user_scrape` child
per new mal_id with `parent_job_id` set. Children carry the seed mal_id in their
payload under `mal_id`, so each child's BFS skips the fuzzy lookup.

Bulk insert rather than per-row commit: the enqueue loop does no MAL I/O, so the
crash-safety argument doesn't apply and a shorter maintenance window wins.

## Progress

`ProgressReporter` writes `(stage, items_done, items_total)` in short autocommit
transactions, throttled to 0.5s with a `force=True` bypass for stage changes —
otherwise a tight BFS loop opens hundreds of sessions a second.

Sweep progress is **media-grained** (`items_total = len(due_media)`), because
media are the real MAL-call unit. The end gap is exactly the media of
step-1-failed anime.

---

**Why it is this way**
- [Sweep observability](../../compound-docs/2026-06-15-v0.14.5-sweep-observability.md) — the audit-diff summary
- [Media-level sweep](../../compound-docs/2026-06-17-v0.14.8-media-level-sweep.md) — anime → media selection
- [Reliability fixes](../../compound-docs/2026-07-17-v0.14.13-bug-fixes.md) — the circuit breaker and maintenance bracketing
- [Content pipeline](../../compound-docs/2026-05-09-v0.14.0-content-pipeline.md) — the original worker design
