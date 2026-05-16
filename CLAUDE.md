# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Phsar is a full-stack anime search and rating web application. It combines a FastAPI backend with a SvelteKit frontend, using PostgreSQL with pgvector for semantic vector search over anime data sourced from the MyAnimeList (Jikan) API.

## Commands

All backend commands run from the `phsar/` subdirectory. The database Docker container must be running for tests and the app.

### Backend
```bash
cd phsar

# Run FastAPI (seeds genres + admin user on first start)
uvicorn app.main:app --reload

# Lint
ruff check .
ruff check . --fix    # auto-fix

# Tests (requires running PostgreSQL container; all DB changes are rolled back)
pytest
pytest tests/routers/test_auth.py           # single file
pytest tests/routers/test_auth.py::test_fn  # single test

# Database migrations
alembic revision --autogenerate -m "Describe change"
alembic upgrade head
```

### Frontend
```bash
cd phsar/frontend
bun install
bun run dev -- --open   # dev server at localhost:5173
bun run test            # vitest component tests
bun run check           # svelte-check type check
```

Backend and frontend must run simultaneously in separate terminals.

### Database (Docker)
```bash
# Start PostgreSQL with pgvector (use credentials matching your .env)
docker run --name anime-postgres \
  -e POSTGRES_USER=<DB_USER> -e POSTGRES_PASSWORD=<DB_PASSWORD> \
  -e POSTGRES_DB=<DB_NAME> -v pgdata:/var/lib/postgresql/data \
  -p 5432:5432 -d ankane/pgvector

# Reset database
rm phsar/alembic/versions/*.py
docker exec -it anime-postgres psql -U <DB_USER> -d <DB_NAME> \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

### Docker (production parity)
```bash
# Build + run db + backend + frontend containers end-to-end (NOT the dev flow).
cp phsar/.env.example .env
docker compose up --build
```

## Architecture

### Backend (phsar/app/)

Layered architecture with strict dependency flow: **routers → services → DAOs → models**

#### routers/

FastAPI endpoint definitions. Each router maps to an API prefix.

- **`/admin`** — admin-only operations
  - Registration token management (list, create, delete)
  - Database backups (list, download, delete, restore, upload)
    - `POST /admin/backups` and `POST /admin/backups/auto` (cron-token authed) both enqueue a `backup` job and return 202 with the job uuid so the request thread doesn't block on `pg_dump`
    - Manual backups attribute to the admin user (visible only in their bell); cron is a system job (`requested_by_user_id=null`), invisible to every bell — the dump list is the audit log
  - Merge-candidate review (list pending, merge, dismiss; powered by the duplicate detector)
    - `POST /admin/merge-candidates/backfill` re-runs existing × existing detection without a container restart — primarily for the post-restore workflow (restore is synchronous, so the lifespan-startup backfill never sees the restored catalog)
  - Three cron-token-authed sweep schedulers:
    - `POST /admin/jobs/schedule-sweep?delay_minutes=N` — enqueues an `update_sweep` job (nightly catalog refresh + relations probe)
    - `POST /admin/jobs/schedule-seasonal?delay_minutes=N` — enqueues a `seasonal_sweep` job (weekly `/seasons/now` scrape)
    - `POST /admin/jobs/schedule-nightly?delay_minutes=N` — combined daily entry: backup (immediate, no banner needed since pg_dump is MVCC-snapshot), update_sweep (delayed), and — when `datetime.now(timezone.utc).weekday() == 6` (Sunday UTC) — a seasonal_sweep with the same delay so the weekly pickup piggybacks on the daily maintenance window
  - All three sweep schedulers set `core/maintenance.set_scheduled_at(...)` so the banner countdown shows
  - All three are bound to `Query(20, ge=0, le=1440)` on `delay_minutes`
  - All three are allowlisted in the maintenance gate so a cron retry while a sweep is running can't 503 the cron itself
  - All four cron-authed endpoints (including `/backups/auto`) share `JOBS_CRON_TOKEN` — one bearer for the whole machine-only surface
- **`/search`** — `/search/media` (per-media) and `/search/anime` (aggregated by anime)
- **`/media`** — `/media/{uuid}` and `/media/anime/{uuid}`
- **`/users`** — settings CRUD, data export, and account deletion
- **`/jobs`** — user-triggered background work
  - `POST /jobs/scrape` enqueues a `user_scrape` job
  - `GET /jobs/mine` lists the current user's active + recently-finished jobs
  - `GET /jobs/{uuid}` single-job poll for owner or admin
- **`/library`** — `GET /library/recent` for the `/library/add` page's recent-additions panel
- **`/maintenance`** — public `GET /maintenance/status` returning `{active, scheduled_at}` for the frontend's pre-warning banner; allowlisted in the maintenance HTTP middleware so it keeps returning truthful state mid-window

#### services/

Business logic as module-level async functions.

- **`jikan_scraper.py`** — MAL API client with retry + client-side rate limiter
  - Retry: Tenacity `wait_exponential(multiplier=2, min=1, max=30)` × 5 attempts
    - `retry_if_exception(_is_transient_mal_error)` gates retries to 5xx + timeouts + network errors
    - 4xx is deterministic and burns 31s of backoff before failing the same way
    - `reraise=True` surfaces the underlying `HTTPStatusError`/`TimeoutException` instead of wrapping in tenacity's `RetryError`
  - Asymmetric 429 handling: retried but capped at 3 total attempts (2 retries — enough to bridge a misaligned per-minute window), while 5xx/timeout/network get the full 5
    - Why: retrying 429 harder masks sustained throttling instead of fixing it; the right response is to slow the source rate
    - Other 4xx (most importantly 404) is deterministic-non-retryable
  - Rate limiting: class-level `_rate_lock` + `_MIN_REQUEST_INTERVAL_S=1.0s` spaces request *starts* at 1 req/s
    - Jikan documents 3 req/s burst AND 60 req/min sustained — the per-minute ceiling binds for continuous-request flows like `/seasons/now` pagination and bulk-refresh sweeps
    - 0.35s and 0.5s both observed 429s in practice
    - Jikan's docs also note MAL upstream can rate-limit independently
  - BFS in `search_title`:
    - Accepts optional `ProgressReporter` so user-scrape jobs can stream progress to the bell
    - Takes `seed_mal_id` + `seed_payload` so the sweep probe can BFS from a known mal_id instead of the fuzzy `q=<title>` top-3 lookup (that lookup pulls unrelated franchises into the catalog if used for known-mal_id probes — see compound-doc)
    - When `seed_payload` carries a `/full` response with relations bundled, the BFS reuses them instead of paying a second `/anime/{id}/relations` hit
  - Skip rules:
    - Anime with `media_type=None` AND `airing_status="Not yet aired"` are skipped silently — they used to land in `media_unwanted` as `Unknown`, permanently blocking rediscovery once the show aired; now only true anomalies (null `media_type` with a non-Not-yet-aired status) get blacklisted
    - Anime with `title=None` are skipped silently — MAL routinely leaves the romanization field null on freshly-announced donghua/Chinese shows and PV stubs (fills in within hours); blacklisting with a `<mal_id:NNNN>` placeholder would pollute `media_unwanted` and block rediscovery

- **`job_worker.py`** — single asyncio FIFO worker draining the `jobs` table
  - Claims jobs via `with_for_update(skip_locked=True)`
  - `wakeup` Event for sub-second pickup with a 60s wall-clock fallback (shortens to 2s while `is_maintenance_active()` — restore lifts the gate without calling `notify()`, so the idle poll has to catch the transition itself)
  - Dispatcher table maps `JobKind → handler` (registered from `main.py` lifespan)
  - Failure handling:
    - Stamps `result_summary.retryable = not isinstance(failure, PermanentPhsarError)` so the bell knows whether to show a retry button
    - Stamps `result_summary.error_category` via `_classify_error`:
      - `upstream_outage` — httpx 5xx + TimeoutException + NetworkError + `TransientUpstreamError` (MAL returning 200 with empty data on a known mal_id)
      - `backup_disk_full` — `BackupDiskSpaceError`
      - `backup_corrupt` — `BackupIntegrityError` (pg_dump output that fails `pg_restore --list` integrity check)
    - The bell renders friendly text instead of raw error strings; uncategorized errors fall through to the raw `error_message`, which is already friendly for custom domain errors
  - Session management: sequential per-job sessions (claim-tx then work-tx in fresh sessions) avoid asyncpg pool deadlocks under nested-savepoint patterns
  - Maintenance bracketing:
    - Sweep-kind jobs (`update_sweep`, `seasonal_sweep`) are bracketed: `set_maintenance(True)` before dispatch, `set_maintenance(False)` + `set_scheduled_at(None)` in `finally` so a crash can't leave the flag stuck
    - `dispatch_one` short-circuits via `is_maintenance_active()` BEFORE claiming any row
      - Why: prevents a queued `backup` job from slipping in during a restore — restore takes its pre-snapshot, releases `_BACKUP_WRITE_LOCK`, then flips maintenance + disposes the pool + `pg_terminate_backend`s every other session; without the early-return, the worker could claim the backup between the pre-snapshot's lock release and `pg_restore` starting
      - The check is unconditional (all kinds) because any job during restore would have its session yanked by `pg_terminate_backend` anyway
      - Sweep-induced maintenance is a no-op for the check: the worker is already running the sweep inside `dispatch_one`, so `_run` doesn't re-enter while the flag is set

- **`scrape_dispatcher.py`** — handlers for `user_scrape` and `update_sweep` jobs (the catalog-mutation pair that share `_apply_media_diff` / `_weighted_score`)
  - `seasonal_sweep` handler lives in its own module `seasonal_sweep_dispatcher.py` because it shares no helpers — it's purely a discovery pass that hands off work to user_scrape
  - **`user_scrape`**: wraps `handle_search_mal_api_results` + `save_search_results` behind a `ProgressReporter`
    - System-enqueued children (from seasonal sweep) carry `seed_mal_id` in payload so each child's BFS skips the fuzzy top-3 lookup and seeds directly off the known mal_id
  - **`update_sweep`**: tier-selects due anime via `AnimeDAO.select_due_for_sweep`, then per anime:
    - **Step 1** — refreshes child media via `JikanScraper.refresh_anime` (`/anime/{id}/full`), diffs volatile fields (`score`, `scored_by`, `episodes`, `airing_status`, `aired_to`) via `_apply_media_diff`, updates `MediaFreshness`, and rewrites `MediaRelationEdges` from the bundled `relations` block (steady-state refresh so MAL additions and bridge-edge restoration for pre-v0.14.1 rows flow in nightly; not counted as `anime_changed` for stable-counter purposes — structural metadata, not volatile fields)
    - **Step 2** (only tier 3 + tier 4 — `not currently_airing AND stable_check_count >= 3`) — probes each Main media's relations via `JikanScraper.search_title(seed_mal_id=...)`, attaches discovered media via `save_service.attach_search_result_to_anime`, advances `AnimeFreshness`
    - Two commits per anime + per-anime try/except:
      - Step 1 always commits durably (crash mid-sweep preserves field-diff work; single bad MAL response fails only that anime)
      - Step 2 only commits on probe success — failure leaves `AnimeFreshness` untouched so the tier query re-selects
    - Per-Main-seed BFS (each main gets its own `visited_ids`) lets the probe reach disjoint sub-graphs — walking from BNHA's main alone wouldn't surface Vigilante S2 because Vigilante S1 is a side-story and BFS stops expanding side-stories once a main is found
  - Score stability tracking:
    - `_weighted_score(score, scored_by) = score * log10(scored_by + 1)` — same formula used for search ranking
    - Only counts as stability-resetting when `abs(new − old) >= _SCORE_STABILITY_THRESHOLD = 0.05`
      - Why: without this, a single new vote per night on a million-vote anime resets the counter forever
    - None↔value transitions bypass the threshold (first votes coming in is structural)
    - New values are written through regardless; the threshold gates only the stability *signal*
    - Score/scored_by writes gated on `payload["scored_by"]` being truthy — MAL returns scored_by as None or > 0 (never literally 0), and `extract_information` coerces None → 0 for the not-null column, so a 0 during refresh means the field was omitted; clobbering a populated count would be silent data loss
  - Stability counter: resets to 0 when any media is currently airing or any field changed (above threshold), else `min(prev + 1, 99)`
  - Coalesced `refresh_spoiler_cache_for_all_users` fires once at sweep end if any new media landed — the probe path uses `attach_search_result_to_anime` (never recomputes) instead of `save_search_results` (always does), so a 200-anime sweep with 50 new media triggers one cache recompute instead of 50
  - **`seasonal_sweep`**: paginates `JikanScraper.fetch_current_season` (`/seasons/now`)
    - Dedupes against `Anime.mal_id ∪ Media.mal_id ∪ MediaUnwanted.mal_id` (plus per-run dedupe so MAL's cross-page duplicates don't double-enqueue)
    - Bulk-inserts one system `user_scrape` child per new mal_id with `requested_by_user_id=null` (system jobs skip per-user cap)
    - Bulk-insert instead of per-row commit because the enqueue loop does no MAL I/O — crash-safety argument doesn't apply, shorter maintenance window matters more

- **`backup_dispatcher.py`** — handler for the `backup` JobKind
  - Wraps `backup_service.create_backup(source, label)`
  - Progress stages: `Dumping` → `Applying retention` → `Done`
  - Stamps `result_summary = {filename, size_bytes, integrity, source, deduped_against}` for the bell to render
  - Catches `DuplicateBackupError` → success outcome with `deduped_against` populated (softer "no new data" line)
  - `apply_retention()` runs after every job — manual and cron share the same 14-recent + 8-Sunday + 1-known-good pool
  - **No maintenance bracket**: `pg_dump` runs on an MVCC snapshot, user writes are safe
  - `BackupDiskSpaceError` / `BackupIntegrityError` surface via `_classify_error` as `backup_disk_full` / `backup_corrupt` with friendly bell copy; both stay `retryable=True`

- **`progress_reporter.py`** — short-lived autocommit-tx writer pushing `(stage, items_done, items_total)` updates to a job row
  - 0.5s throttle with `force=True` bypass for stage transitions — keeps tight BFS loops from opening hundreds of sessions per second

- **`search_service.py`** — orchestrates BFS output into save/attach/merge decisions
  - Takes graphs from `JikanScraper.search_title`, runs DB-side dedupe against catalog + `media_unwanted`
  - Per-graph decision: save as new anime, attach to existing anime, or surface as merge candidate
  - Packages as `SaveAction | AttachToExistingAction` for the caller
  - **`AttachToExistingAction`**: routes orphan side-story graphs (single cross-link to an existing Media, no main of their own) through `save_service.attach_search_result_to_anime` so a tier-1/2 parent's new side-story gets attached under the right anime instead of becoming a duplicate
  - **`_pick_root_for_promotion`**: seed-mode fallback when `get_first_main_relation` finds no main AND there's no single cross-link
    - Picks the most main-like graph entry by `(type_tier, aired_from)`: TV/Movie=0, ONA=1, OVA/TVSpecial=2, Special=3 (nulls last on aired_from)
    - Why: necessary for donghua sub-universes whose canonical main is an ONA, and for pilot-aired-before-the-real-show edge (tier > date)
  - Cross-link signals are filtered to subtract `media_unwanted` mal_ids before the attach-vs-promote decision so filtered Music/PV entries don't get treated as franchise-overlap evidence
  - `alternative_setting` is treated as a graph boundary (like `crossover`) but dropped entirely — MAL's explicit "different story, shared themes" label; conflating those into one Anime row triggered false-positive merge candidates on every sweep
  - All MAL relation strings normalized once on entry via `_normalize_relation(rel) = rel.lower().replace(" ", "_")`
    - Before v0.14.0 comparisons used the underscore form but lists held raw MAL strings (`"Parent story"`), so the `is_main_story` gate silently let every franchise movie classify as `main` instead of `side_story`
    - See [compound-docs/2026-05-11-jikan-scraper-quirks.md](compound-docs/2026-05-11-jikan-scraper-quirks.md)
    - Fix applies to new scrapes only; pre-fix catalog rows keep stale labels until re-scraped

- **`vector_embedding_service.py`** — sentence-transformers embeddings
- **`media_search_service.py`** / **`anime_search_service.py`** — filtered DB search
  - Anime variant uses a two-phase query (GROUP BY + HAVING for filter/order, then detail fetch) with majority-genre logic
  - **Anime-view filters mirror the card's derivation in `_compute_anime_aggregates`**, not per-media WHERE: `age_rating` filters against `MAX(age_rating_numeric)`, `airing_status` against the priority-collapsed value (Currently → Finished → Not yet aired). Otherwise an anime with one Finished side-story would surface under the "Finished" filter despite the card showing "Currently Airing"
- **`filter_service.py`** — filter option values; view-type-aware for anime vs media ranges
- **`auth_service.py`** — registration, authentication, token issuance, account deletion
- **`user_settings_service.py`** — user settings CRUD + default creation
- **`token_service.py`** — compressed JWT for shareable filter URLs
- **`admin_service.py`** — registration token list + delete

- **`merge_detection_service.py`** — duplicate-anime detector
  - Three signals feed `merge_candidates`:
    - `title_studio` — SequenceMatcher ratio OR containment ≥ 0.85, gated by studio overlap
      - Containment additionally requires word-boundary on both sides of the match in the longer string AND a size floor of `MIN_CONTAINMENT_MATCH_CHARS=4` chars OR a full match where the shorter title is itself ≥ `MIN_FULL_MATCH_CHARS=3`
    - `title_desc` — weaker title match + description-embedding cosine ≥ 0.85
    - `relation_link` — BFS surfaced a non-crossover related media under a different anime
  - Detection runs at the end of `save_search_results` (new × existing AND new × new — the latter catches single-scrape duplicates without waiting for a restart); startup `backfill_merge_candidates` covers existing × existing, and admin can re-trigger it any time via the manual `POST /admin/merge-candidates/backfill` endpoint
  - `seen_pairs` pre-fetch short-circuits flagged or admin-resolved pairs before any similarity computation

- **`merge_candidate_service.py`** — admin operations on merge candidates
  - List pending: ranked per-pair by `(earliest aired_from ASC nulls last, rating_count DESC, anime_id ASC)` so recommended-keep side surfaces as A
    - Uses `MergeCandidateDAO.get_rating_counts_for_anime` for tiebreak
  - Each list-pending item carries `pending_reclassifications: list[{media_uuid, title, old_relation_type, new_relation_type}]` — admin sees the per-media changes that would land before clicking merge (substance-gate demotions, alt-version labels, anchor flips)
  - Dismiss: status flip
  - Merge: re-parents B's media onto A, deletes B via cascade, calls `anime_relation_service.reclassify_anime` over the consolidated set (rewrites umbrella + regenerates embedding only when drift), runs `detect_merge_candidates` against survivor, recomputes spoiler cache
    - Accepts optional `keep_uuid` to swap which side survives — DB invariant `anime_a_id < anime_b_id` unchanged, A/B is presentation only
    - Fail-loud on shared `Media.mal_id` between A and B — global-unique-violation needs human review

- **`relation_classifier.py`** — pure-function two-pass classifier (DB-less)
  - `classify_anime_relations(nodes, edges) -> dict[mal_id, str]` — picks anchor by substance gate + tier + age, builds main chain via sequel/prequel closure, classifies alt-chain via `alternative_version` edges, defaults rest to `side_story`; demotes weak Mains via substance gate as final layer
  - Substance gate: TV/ONA needs `episodes>=8 AND duration_seconds>=900` (15min) — NULL episodes acceptable for currently-airing/long-running; Movie needs `duration_seconds>=1800` (30min); TVSpecial strict
  - Anchor tier: TV(1) > ONA(2) > Movie(3) > other(4); within tier oldest aired_from wins
  - `media_to_classifier_node` (ORM projection) + `build_classifier_nodes` (scraper-dict projection) co-located so future ClassifierNode field additions surface both
  - `_build_adjacency(edges, valid_ids)` filters dangling endpoints defensively — sidecars persist unfiltered edges so merge time can resolve previously-dangling bridges

- **`anime_relation_service.py`** — orchestrates `reclassify_anime(db, anime, *, dry_run=False)` over a loaded Anime
  - Detects drift on any of 7 umbrella fields (mal_id, title, name_eng, name_jap, other_names, description, cover_image); rewrites + regenerates embedding when drift present
  - `preview_reclassifications(anime_a, anime_b)` returns the per-media diff that would land if A absorbed B — read-only, powers the merge-candidate preview
  - Called from `relation_backfiller` (per catalog row) and `merge_candidate_service.merge` (survivor reclassification)

- **`rating_service.py`** — rating CRUD + note search; triggers spoiler-visibility recompute on every change
- **`spoiler_service.py`** — frontier algorithm + precomputed visibility cache in `user_visible_media`
  - Anchor types include `Main` AND `AlternativeVersion` — retellings extend the story so each alt-version gates the next (rating Eva TV reveals Rebuild Movie 1 but not Movies 2-4)
  - Recomputed per-anime on rating changes, per-user on registration, per-user after new scrapes via `save_service`

- **`export_service.py`** — flat media-level export merging catalog + ratings + watchlist; respects user's `name_language` for localized title columns

- **`backup_service.py`** — pg_dump/pg_restore orchestration
  - Atomic `.partial` writes, sidecar `.meta.json`, content-hash dedupe
  - Retention — two independent pools:
    - Manual + cron: 14 daily + 8 Sunday + most-recent-known-good
      - Pins the `is_current` dump regardless of age — prevents a stack of dedupe-hit re-confirms from pushing the pointed-at older dump out of the 14-recent window
    - Uploads: separate `_UPLOAD_RETENTION_COUNT=5` most-recent pool
      - Also pins `is_current` — ensures a restore-from-upload workflow can't evict the bytes the DB was just restored from
    - Pre-restore snapshots stay retention-exempt entirely — safety net for synchronous restore, admin cleans by hand
  - `.current_db.json` pointer tracks which dump matches the live DB:
    - Set by `restore_backup` (→ restored dump) and by every successful `create_backup` regardless of source — manual / cron / pre_restore, whether unique or dedupe hit
    - Uploads NEVER move the pointer (`save_uploaded_backup` only stamps `is_current` when the new filename equals the unchanged pointer) — uploaded bytes are external, can't verify they match live
    - Deleting the pointed dump clears the pointer
  - All write paths serialized via module-level `asyncio.Lock` (single-worker assumption)
  - Restore flips maintenance flag → other requests 503; backup creation does NOT (MVCC-snapshot read-only)
  - Subprocess password via `PGPASSWORD`, never on the CLI
  - Deeper design notes: [compound-docs/2026-04-19-v0.13.0-deployment.md](compound-docs/2026-04-19-v0.13.0-deployment.md)

#### daos/

Data access layer.

- **`BaseDAO`** — generic async CRUD
- **Specialized DAOs** (media, anime, genre, studio, user, user_settings, registration_token, rating, job, merge_candidate) — domain-specific queries with vector similarity, filtering, aggregation
- **`AnimeDAO`**:
  - `search_anime_aggregated` — two-phase query: SQL GROUP BY with HAVING for filtering/ordering, then detail fetch
  - `select_due_for_sweep` — four-tier sweep selection (airing now / still stabilizing / weekly recent main / 180-day long tail), backed by three indexes:
    - `ix_anime_freshness_last_checked_at` (the ORDER BY)
    - `ix_media_airing_now` — partial index on `media(anime_id) WHERE airing_status = 'Currently Airing'`
    - `ix_media_main_aired_from` — composite `(anime_id, relation_type, aired_from)` for the recent-main EXISTS
- **`search_filters.py`** — shared filter/ordering helpers for media, anime pre-aggregation (WHERE), and anime post-aggregation (HAVING)
  - **Title-search ranking**: `apply_vector_ordering` subtracts a two-tier bonus from `cosine_distance` so titles that literally match the query rank ahead of merely thematically-similar shows. Substring (`ilike`) bonus is flat; pg_trgm `similarity()` bonus is scaled linearly above a threshold so typos still surface the intended show. Description and rating-notes search skip both bonuses (semantic queries, not literal). pg_trgm extension enabled via migration `4b8f1e3c7d0a`
- **`JobDAO`**:
  - Claim-skip-locked dispatch + crash recovery
  - `reap_orphans` — runs at startup, flips any `running` rows to `failed` so a mid-job restart doesn't leave them stuck
  - `find_recent_scrape_for_query` (submission-time dedup) — backed by `ix_jobs_scrape_query`, an expression index on `lower(trim(payload->>'query')), created_at DESC` filtered to `kind='user_scrape'`, so dedup stays O(log n) as seasonal sweep enqueues hundreds of system jobs per week

#### models/

SQLAlchemy ORM models mapped to PostgreSQL tables.

- **`media_search.py`** — pgvector embeddings for title and description
- **`media_relation_edges.py`** — 1:1 sidecar to `media` holding the raw MAL relation list (`[[target_mal_id, normalized_rel], ...]` JSONB). Off the canonical row so `selectinload(Anime.media)` on detail/search hot paths doesn't drag the JSONB through every load. Read at merge / preview / backfill time via explicit `selectinload(Media.relation_edges)`. Edges persisted unfiltered (including targets outside the local catalog) so bridge edges activate when split franchises later get merged
- **`anime_search.py`** — anime-level embeddings
- **`rating_search.py`** — note embeddings for rating note search
- **`user_settings.py`** — per-user preferences (1:1 with Users) with enums for theme, name language, search view, rating step, spoiler level
- **`user_visible_media.py`** — precomputed spoiler-visibility cache per user, updated on rating changes
- **`merge_candidate.py`** — admin-reviewable duplicate pairs
  - Status enum: `pending`/`dismissed`/`merged`
  - FK cascades on both anime ids — merging or deleting either anime cleans up dangling rows
  - Unique constraint + check on `(anime_a_id, anime_b_id)` with caller-enforced ascending order so `(A,B)` and `(B,A)` collapse
- **`job.py`** — background job queue
  - `JobKind` enum: `user_scrape`, `update_sweep`, `seasonal_sweep`, `backup`
  - `JobStatus` enum: `queued`/`running`/`succeeded`/`failed`
  - JSONB `payload`, progress fields (`stage`, `items_done`, `items_total`), `not_before_at` for scheduled-delay jobs
  - `result_summary` JSONB carries `retryable: bool` for the bell
  - Partial composite index on `(created_at) WHERE status='queued'` keeps the worker's FIFO claim cheap regardless of finished-row volume
- **`anime_freshness.py`** / **`media_freshness.py`** — 1:1 sidecars (`unique=True` on FK) for the nightly update sweep
  - Hold `last_checked_at` (and `stable_check_count` on anime side) outside canonical rows so sweep cadence can't leak into Pydantic schemas via `model_dump()`
  - Existing rows backfilled to parent's `created_at` so sweep enters them at honest age, not "never checked"

#### Other backend modules

- **schemas/** — Pydantic request/response DTOs
- **core/** — cross-cutting infrastructure:
  - `config.py` — loads settings from `.env`
  - `db.py` — database engine
  - `dependencies.py` — JWT user dep + `require_roles()` factory + generic `require_bearer_token(settings_attr, error_factory)` factory bound once to `JOBS_CRON_TOKEN` for every cron-authed endpoint
  - `security.py` — JWT/password security
  - `maintenance.py` — process-wide maintenance state: `_active` flag (flipped by destructive ops) + `_scheduled_at` future-window pointer (set by schedule-sweep cron endpoint); both are module globals, single-process assumption
  - `maintenance_middleware.py` — see Maintenance Mode under Key Patterns
- **seeders/** — run at app startup via lifespan
  - Seed genres, admin user, and optional guest user (`restricted_user` role)
  - `backfill_user_settings` — ensures all users have a UserSettings row
  - `backfill_spoiler_visibility` — computes visible media for users with **zero** cache rows (new deployments, pre-feature users); does **not** mop up partial-cache drift on existing users
  - `anime_title_backfiller.backfill_anime_title_suffixes` — strips season suffixes ("Season I", "第2期", "Part 2", " II"…) from `Anime.title`/`name_eng`/`name_jap` on rows scraped before the normalisation landed; regenerates the anime embedding for changed rows. Idempotent; subsequent restarts touch zero rows. `anime_service.create_anime_from_media` applies the same strip on new scrapes so the umbrella row reads like the franchise name, not the per-season identity
  - `embedding_backfiller.py` — detects and regenerates missing anime/media/rating embeddings (enables seamless embedding model swaps via Alembic migration + restart)
  - `relation_backfiller.backfill_relations` — gated by `RELATION_BACKFILL_ON_STARTUP`. Re-runs the two-pass classifier over every Anime via `anime_relation_service.reclassify_anime`. Per-anime commit: lazily-fetched MAL relations (~1 req/s) checkpoint incrementally so a crash mid-run doesn't lose hours of pagination. `dry_run=True` powers the audit checkpoint (see `phsar/scripts/audit_relation_backfill.py`); supports `anime_ids` filter for the admin re-classify endpoint and tests
  - `merge_detection_service.backfill_merge_candidates` — one-shot existing × existing pair sweep so duplicates pre-dating the detector get flagged on first restart after upgrade
  - `save_service.save_search_results` triggers a full-user spoiler-cache recompute after new animes land — load-bearing for existing `spoiler_level=hide` users whose populated cache stays stale (startup backfill skips them since they have rows)
  - The sweep dispatcher's relations probe goes through `save_service.attach_search_result_to_anime` instead, which intentionally does *not* recompute per-batch; the dispatcher fires one coalesced `refresh_spoiler_cache_for_all_users` at sweep end
- **exceptions.py** — custom exception hierarchy rooted at `PhsarBaseError` with `status_code` attribute
  - Single exception handler in `main.py` reads the status code from each class
  - `PermanentPhsarError` — marker subclass for non-retryable failures:
    - `AnimeNotFoundError`, `MainMediaNotFoundError`, `MalIdAlreadyExistsError`, `AnimeFilteredOutError`
    - `JobWorker` reads via `isinstance` and stamps `result_summary.retryable = False`
  - `TransientUpstreamError` — outside the permanent branch; raised when MAL returns 200 OK with empty data on a valid mal_id
    - Bell keeps retry button; `_classify_error` tags as `upstream_outage` for friendly copy
  - `AnimeFilteredOutError` (sibling to `AnimeNotFoundError` under permanent) — surfaces when seeded BFS returns nothing AND seed mal_id is in `media_unwanted`; admin sees `"'X' was filtered out as Music"` instead of misleading "not found"
- **main.py** — app factory + lifespan
  - Startup sequence: seeders → embedding backfill → merge-candidate backfill → `JobDAO.reap_orphans` → `job_worker.register_dispatcher` (for each of `user_scrape`, `update_sweep`, `seasonal_sweep`, `backup`) → `job_worker.start()`
  - Shutdown: `job_worker.stop()`
  - Direct endpoints: `GET /` and `GET /health`
    - Health returns `{status, version, db}` and pings DB with 2s `asyncio.wait_for` so transient unavailability produces a fast 503 instead of riding asyncpg's 60s connect timeout into a Coolify liveness flap
  - Registers `MaintenanceGateMiddleware` — see Maintenance Mode under Key Patterns

### Frontend (phsar/frontend/)

SvelteKit with file-based routing, Svelte 5 runes, Tailwind CSS 4, shadcn-svelte component library.

#### routes/

- Pages: home (`/`), login (`/login`), register (`/register`), search (`/search`), media detail (`/media`), anime detail (`/anime`), settings (`/settings`), admin (`/admin`), add to library (`/library/add`)
- `GET /health` endpoint returning `{status, version}` for Coolify liveness — deliberately does not probe backend (liveness should only check what restarting this container can fix)
- `/library/add` — query-input + recent-additions panel; submitting POSTs to `/jobs/scrape` and the navbar bell takes over from there; restricted users see the page but the form is disabled

#### lib/components/

App components using Svelte 5 `$props()`, `$state()`, `$derived()`, `$effect()`.

- **SearchBar, MediaInfo, NavBar, TagSelect, DoubleRangeSlider, RatingCard, BulkRateDialog, DangerZone, RelatedMediaCarousel, SpoilerGuard, EChart** — core UI components
- **RatingsOverview** — with sub-components: Stats, Timeline, Notes, Attributes
- **AttributeRadar, AttributeBadges, AttributeDetailBars** — attribute visualization
- **VersionFooter** — renders at the bottom of every page, reads `PUBLIC_APP_VERSION` from `$env/dynamic/public`
- **LoadingScreen** — themed sakura-ring loader shown during initial boot + ~1.5s logout transition
- **Notice** — shared yellow info card (rounded `bg-yellow-50` surface + `AlertTriangle` icon — solid surface so it reads on the dark body gradient)
- **BackupsCard** — admin-only dump list
  - Create/upload/download/restore/delete with a "Current" badge on the row the DB was last restored from
- **MergeCandidatesCard** — admin-only review surface for pending merge candidates
  - Side-by-side anime info (with rating count + earliest aired date as visible justification for recommended A)
  - Similarity score, merge/dismiss with confirm-step, per-row "Swap A/B" button
  - Silent refreshes — keyed each-block diffs in place instead of collapsing to "Loading…"
  - Merges trigger automatic refetch surfacing cascade-resolved pairs and freshly-detected ones
- **MaintenanceBanner** — wraps a `Notice`, lives in a sticky container in `+layout.svelte` alongside the navbar
  - Polls `GET /maintenance/status` every 30s via raw `fetch` (bypasses `api.ts` so a 503 mid-window can't trigger maintenance redirect and defeat the pre-warning point — 30s instead of 60s because seasonal sweep's maintenance window can be only seconds long)
  - Subscribes to `token` store + `maintenanceRefresh` bump signal so relogin or any 503-with-maintenance response refreshes in milliseconds
  - Countdown wording: `"Scheduled maintenance starts in ~N minute(s) — pause your current episode."` within 30 min; `"Maintenance in progress. Some pages may be unavailable."` when active; otherwise hidden
- **JobBell** — polls `/jobs/mine`
  - Caps dropdown at 5 entries (older spill to `/library/add`)
  - Hides retry button when `result_summary.retryable === false`
  - Disables retry across all rows while one is in flight

#### lib/components/ui/

shadcn-svelte base components (button, card, input, badge, slider, dropdown-menu, popover, checkbox, label, select, separator, etc.).

#### lib/

- **api.ts** — centralized API client
  - Methods: `get`/`post`/`postForm`/`put`/`del`/`downloadBlob`/`postMultipart`
  - `ApiError` class, automatic auth header injection from token store
  - Maintenance-503 handler: clears token, calls `bumpMaintenanceRefresh()` (covers user-on-/login where `token.set(null)` is a no-op), hard-navigates to `/login`
- **types/api.ts** — TypeScript interfaces mirroring backend Pydantic schemas (`MediaConnected`, `FilterOptions`, `TokenResponse`, etc.)
- **stores/** — Svelte stores for auth, settings, spoiler visibility, bell session, cross-component bumps
  - `jobs.ts`:
    - Three writable bumps via `createBumpStore()` factory + `onBump(store, fn)` helper:
      - `jobsRefresh` — bumped by `/library/add` or BackupsCard after successful POST so bell refetches in ms instead of waiting for 30s idle poll
      - `librarySaved` — bumped by bell when it observes a new `succeeded` `user_scrape` so `/library/add` refreshes recent-additions
      - `backupSaved` — bumped by bell on new `succeeded` `backup` so BackupsCard auto-refreshes
    - Same `announcedSavedUuids` Set covers both kinds — UUIDs are globally unique
    - `optimisticJobs` (writable list) + `addOptimisticJob(job)` / `reconcileOptimisticJobs(fetched)`:
      - Bell merges optimistic ∪ fetched (deduped by UUID) inside `$derived`
      - Callers seed a `queued` row synchronously off returned `job_uuid`; next fetch reconciles (UUID match → optimistic pruned)
    - Store-update helpers short-circuit no-ops (svelte writables notify on every `set()` even with same-reference returns)
  - `maintenance.ts` — `maintenanceRefresh` writable + `bumpMaintenanceRefresh()`; `api.ts` bumps on every 503-with-maintenance, `MaintenanceBanner` subscribes via `onBump`
  - `bell-session.ts` — `BELL_LOGIN_KEY` / `BELL_SEEN_KEY` + `clearBellSession()` helper; `auth.ts` calls it when token transitions to null so logout-and-back-in doesn't inherit previous session state (sessionStorage survives hard navs)
- **utils/** — helpers:
  - String formatting: `formatAiringStatus`, `formatRelationType`, `formatMediaType`, `formatSeasonRange`, `formatDuration`, `formatDecimalDigits`, `formatShortDate`, `formatShortDateTime`, `formatBytes`
  - Season logic, search params (`fetchSearchResults`, `fetchAnimeSearchResults`), navigation (`navigateToSearch`, `buildDetailHref`)
  - Chart colors: `CHART_COLORS`, `scoreColor`, `getThemedChartColorPalette`, `RELATION_TYPE_ORDER`, `RELATION_TYPE_COLORS`, `RELATION_TYPE_LABELS`
  - `spoilerFrontier.ts` — client-side frontier for detail pages
- **themes.ts** — centralized theme config: `THEMES` record mapping keys to CSS classes, character pics, labels; `ThemeKey` type; helpers: `isValidTheme`, `getThemeCssClass`, `getThemePic`, `getThemeFocal`, `getActiveTheme`
- **echarts.ts** — lazy-loaded ECharts singleton (`getEcharts()`) using pre-built ESM bundle (SSR-safe, cached)
- **config.ts** — backend API base URL (consumed only by `api.ts`)

#### src/app.css

Theme system: `@property` definitions for `--primary`/`--ring`, `@theme inline` with `var()` indirection, `.theme-red`/`.theme-blue`/`.theme-green` override classes, themeable gradient variables (body dark gradient `--gradient-*` + auth-page light gradient `--auth-gradient-*`). Light elevated surfaces on dark gradient background. Dark mode locked to class-based only.

#### tests/

Vitest + @testing-library/svelte component tests.

### Key Patterns

- **Dependency injection**: FastAPI `Depends()` for DB sessions, current user extraction, role-based access (`require_roles()` accepts `RoleType` enum)
- **Role-based access**: three roles — `admin`, `user`, `restricted_user`
- **Async throughout**: asyncpg driver, SQLAlchemy AsyncSession, async service/DAO methods
  - All ORM relationships use `lazy="raise"` to prevent implicit lazy loading — every relationship access must go through explicit `selectinload` in the DAO query
- **Vector search**: `paraphrase-multilingual-MiniLM-L12-v2` model, pgvector storage
  - `SearchType` enum (`title`, `description`, `rating_notes`) selects the target
  - `ViewType` enum (`anime`, `media`) selects the search mode
  - Filter schemas use inheritance: `MediaSearchFilters` (base) → `RatingSearchFilters` (adds rating-specific filters)
  - Anime-level title search uses `AnimeSearch` embeddings directly; description search averages cosine distances across media
  - `/filters/options?view_type=anime` returns anime-appropriate filter ranges (aggregated episodes/watch time, majority genres)
- **Domain exceptions**: all custom exceptions extend `PhsarBaseError` with `status_code`. One handler in `main.py`. See exceptions.py above for hierarchy
- **Theme system**: CSS custom properties with `@property` indirection
  - `@property --primary` / `--ring` hold source values, `@theme inline` references via `var()`, `.theme-*` classes override
  - Why: forces Tailwind to emit `var()` in utilities instead of inlining static values
  - Components use semantic tokens (`bg-primary`, `text-primary`, `ring-ring`)
  - Centralized config in `lib/themes.ts`; FOUC prevention via inline localStorage script in `app.html`
  - Per-theme chart color palettes in `chartColors.ts` avoid hue clashes
- **Two-pass relation classifier**: scrape-time + merge-time + backfill-time classification of media within an anime (see [compound-docs/2026-05-11-jikan-scraper-quirks.md](compound-docs/2026-05-11-jikan-scraper-quirks.md))
  - Pass 1 (`jikan_scraper.search_title`) captures relation **edges** during BFS — no classification baked in. Sidecars persist edges unfiltered, including dangling targets
  - Pass 2 (`relation_classifier.classify_anime_relations`) picks a canonical anchor by substance gate + tier (TV > ONA > Movie) + oldest aired_from, builds main chain via sequel/prequel closure, classifies alt-chain via `alternative_version` edges, defaults rest to `side_story`; demotes weak Mains via substance gate
  - `RelationType.AlternativeVersion` enum value distinguishes retellings (Evangelion TV ↔ Rebuild Movies, Hokuto no Ken alts) from genuine side stories. Spoiler frontier treats alt-version as an anchor
  - Same classifier runs at three sites: scrape (per BFS-result), merge survivor (consolidated A∪B), backfiller (per catalog row)
  - Bridge edges across previously-different-anime boundaries: persisted unfiltered in sidecars; classifier's `_build_adjacency` filters dangling endpoints at adjacency-build time. Merge consolidation surfaces bridges that were dangling at scrape time (Dr. Stone split-merge case)
  - Backfiller (`relation_backfiller`) lazy-fetches `/anime/{id}/relations` for media with empty sidecars; per-anime commit checkpoints incrementally so a 14-min cold start can't lose progress
  - `anime_relation_service.reclassify_anime` is the orchestration helper; rewrites all 7 umbrella fields (mal_id, title, name_eng, name_jap, other_names, description, cover_image) on any drift, regenerates embedding only on title-affecting drift
- **Spoiler protection**: three levels (`off`/`blur`/`hide`) via `SpoilerLevel` user setting
  - Frontier algorithm: per anime, all media up to and including the next unwatched **anchor** (`main` or `alternative_version`) entry are visible — retellings extend the story so each alt-version gates the next
  - Precomputed in `user_visible_media` table (updated per-anime on rating changes, per-user on registration, per-user after scrapes via `save_service`)
  - Backend `GET /ratings/spoiler-visibility` returns visible UUIDs; frontend stores as `Set` in `spoilerVisibility` store
  - `SpoilerGuard.svelte` wraps covers/descriptions with blur + click-to-reveal
  - Detail pages compute frontier locally for fresher data
  - `hide` mode in media search uses `WHERE media.id IN (...)` from the cache
  - Anime covers/descriptions are never spoiler-protected
- **Background jobs**: single asyncio FIFO worker (`job_worker.py`) drains the `jobs` table
  - JobKinds: `user_scrape`, `update_sweep` + `seasonal_sweep` (bracket maintenance), `backup` (does NOT bracket)
  - Per-user cap: `JOBS_PER_USER_LIMIT=4` enforced at submission time (bounds queue depth, not concurrency — worker stays sequential because MAL's rate limit means parallel jobs just fragment bandwidth)
  - System jobs submit with `requested_by_user_id=null` to skip cap
  - `ProgressReporter`: handlers stream `(stage, items_done, items_total)` to the bell before the job tx commits (autocommit txes, 0.5s throttle)
  - `PermanentPhsarError` gates retry: deterministic failures stamp `retryable = False`, bell hides retry button
  - `TransientUpstreamError` stays outside marker → retryable bell entry
  - Per-query dedupe at submission: same normalized query within `JOBS_DEDUPE_HOURS` returns 409 (failed jobs don't count, so transient outage doesn't lock users out)
  - Crash recovery: `JobDAO.reap_orphans` runs at lifespan startup, marks `running` → `failed`
  - Bell cadence: 2s active poll while anything is queued/running, 30s idle
  - Optimistic-stub pattern: pages that enqueue push a `queued` stub keyed on `job_uuid` into `optimisticJobs` store; bell merges optimistic ∪ fetched (UUID-deduped); `reconcileOptimisticJobs(fresh)` prunes landed entries
- **Maintenance mode**: destructive ops flip `core/maintenance.py`'s `_active` flag
  - Triggers: backup restore (synchronous, request-scoped), `update_sweep`/`seasonal_sweep` (worker brackets in try/finally)
  - `MaintenanceGateMiddleware` (pure ASGI class in `core/maintenance_middleware.py`) returns 503 `{maintenance: true}` for non-allowlisted requests
    - Allowlist: `/`, `/health`, `/maintenance/status`, `/admin/jobs/schedule-sweep`, `/admin/jobs/schedule-seasonal`, `/admin/jobs/schedule-nightly`
  - **Critical middleware ordering invariant**: `app.add_middleware()` *prepends* (`insert(0, ...)`), so LAST registered = OUTERMOST
    - Register `MaintenanceGateMiddleware` FIRST, then `CORSMiddleware` — CORS wraps maintenance, 503 gets `Access-Control-Allow-Origin`
    - Wrong order → 503 has no CORS headers → browser blocks → `fetch()` throws TypeError → generic error instead of maintenance banner
  - Why pure ASGI (not `@app.middleware("http")`/BaseHTTPMiddleware): BaseHTTPMiddleware short-circuits don't compose cleanly with CORSMiddleware's send wrapper
  - Frontend: `api.ts` detects 503-with-maintenance, clears token, bumps `maintenanceRefresh`, hard-navigates to `/login`
  - Pre-warning: schedule-sweep cron endpoint sets `_scheduled_at` to future timestamp; `MaintenanceBanner` polls and renders countdown when within 30 min
  - Both `_active` and `_scheduled_at` are process-wide module globals — single-worker assumption, documented upgrade path is file sentinel or DB row
- **CORS**: backend allows origins from `settings.CORS_ORIGINS` (defaults to `http://localhost:5173`); exposes `Content-Disposition` so frontend can read server-authored download filenames

## Working With Me

- Always ask before making changes to the repo such as creating issues, milestones, releases, commits, or pushing code.
- When planning work, discuss the plan with me before executing — don't assume priorities or release groupings.

## Configuration

### Backend (required)

`phsar/.env` file with: `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`, `SEARCH_SECRET_KEY`.

### Backend (optional)

- `DEBUG` — enables SQL echo
- `CORS_ORIGINS` — JSON list of allowed origins
- `GUEST_USERNAME` + `GUEST_PASSWORD` — seeds a read-only guest account with `restricted_user` role
- `APP_VERSION` — deployed version tag surfaced on `/health`; injected via backend Dockerfile build arg
- `BACKUP_DIR` — where dumps are written; defaults to `./backups` (native dev), Dockerfile sets to `/backups` (bind-mounted volume)
- `BACKUP_RESTORE_TIMEOUT_SECONDS` — default 600; raise if DB grows large enough that pg_restore legitimately takes >10 min (a mid-restore kill leaves the DB half-dropped)
- `JOBS_CRON_TOKEN` — shared bearer secret for every cron-authed endpoint (`/admin/backups/auto`, the three sweep schedulers); empty disables all four, they fail closed
- `JOBS_PER_USER_LIMIT` — default 4; max queued+running user_scrape jobs per non-system user; 5th submission returns 409
- `JOBS_DEDUPE_HOURS` — default 72; same scrape query within this window returns 409 unless prior job failed
- `JOBS_SWEEP_MAX_PER_RUN` — default 200; bounds nightly `update_sweep` batch size
- `RELATION_BACKFILL_ON_STARTUP` — default `True`; runs `relation_backfiller` at lifespan startup. First cold start fetches missing `MediaRelationEdges` sidecars from MAL at 1 req/s (~14min for an 800-media catalog); subsequent restarts skip already-populated rows and finish in seconds. Disable for tight maintenance windows on fresh deployments

### Frontend (runtime)

Read from `$env/dynamic/public` — set as container ENV in production, no image rebuild required:

- `PUBLIC_API_BASE_URL` — backend URL; defaults to `http://localhost:8000` for local dev
- `PUBLIC_APP_VERSION` — shown in the footer

## Deployment

Self-hosted on a Coolify-managed VM. Images are built in GitHub Actions and pulled by Coolify — the VM is too small (2 vCPU / 4 GB) to survive a SvelteKit build.

### Services

- **`phsar/Dockerfile`** — multi-stage backend
  - CPU-only torch from pytorch CPU index; sentence-transformers model baked into `/opt/st-cache`
  - Runs as non-root `phsar` user (UID 1000)
  - `/backups` created at build time, chowned to `phsar:phsar` so bind-mounted host dir matches
  - Entrypoint (`phsar/docker/entrypoint.sh`) applies Alembic migrations before exec'ing uvicorn
- **`phsar/frontend/Dockerfile`** — bun build → `node:22-slim` runtime via SvelteKit `adapter-node`; reuses built-in `node` user
- **`docker-compose.yml`** (repo root) — all three containers; only for local parity smoke-testing, not day-to-day dev

### Deployment flow

Tag any commit with `v*` (stable `v0.13.0` or preview `v0.13.0-rc1`) and push. `build-images.yml` builds both images in parallel and pushes to `ghcr.io/priapos1004/phsar-{backend,frontend}:<tag>`. In Coolify, point each service at the new image tag and redeploy.

### Backups

- Coolify mounts `/opt/phsar/backups` on the VM to `/backups` in the backend container
  - Host directory must be owned by UID 1000 (`chown 1000:1000 /opt/phsar/backups`)
- Manual backups: admin panel → Backups card → "Create backup"
  - Both manual and cron POSTs are async — endpoint enqueues a `backup` job (202 with `job_uuid`), worker runs `pg_dump` in background
  - Bell tracks progress (`Dumping` → `Applying retention` → `Done`); on success BackupsCard auto-refreshes
  - "Create backup" button debounces for 5s to absorb double-clicks
  - Download/delete/upload/restore from the same UI; restore stays synchronous (meant to be blocking)
- Scheduled backups: driven by `/admin/jobs/schedule-nightly` (see Scheduled Jobs below)
  - Standalone `POST /admin/backups/auto` stays available for backup-only ad-hoc cron
  - Retention runs after **every** backup job (manual and cron share the pool), so manual-only installs don't accumulate indefinitely
- Off-host safety net: `scripts/pull-backups.sh user@vm` rsyncs `/opt/phsar/backups/` to local machine; run every ~2 months and before any restore
- Restore workflow: UI prompts for admin's username as confirmation string; automatic pre-restore snapshot first, then `pg_restore --clean --if-exists --no-owner --no-privileges`

### Scheduled jobs

Every cron-authed endpoint shares `JOBS_CRON_TOKEN` (in Coolify backend env — empty disables all, fail closed).

- Sweep schedulers (`schedule-sweep`, `schedule-seasonal`, `schedule-nightly`) are allowlisted through maintenance gate so a cron retry mid-sweep authenticates instead of 503'ing
- `/admin/backups/auto` is *not* allowlisted — backups don't bracket maintenance, a sweep-window 503 is a benign no-op (worker short-circuits on maintenance flag anyway)
- `delay_minutes` bound to `Query(20, ge=0, le=1440)` on every sweep endpoint

**Recommended Coolify setup — one daily task (~02:30 UTC):**

```
curl -fsS -X POST -H "Authorization: Bearer $JOBS_CRON_TOKEN" \
  "http://localhost:8000/admin/jobs/schedule-nightly?delay_minutes=20"
```

`schedule-nightly` enqueues:
1. `backup` job (no delay — pg_dump is MVCC-snapshot, no banner needed)
2. `update_sweep` job with `not_before_at = now + delay_minutes`
3. `seasonal_sweep` job (same delay) — **only on Sundays** (`weekday() == 6`) so weekly pickup piggybacks on daily maintenance window

The two sweep jobs share `not_before_at` — worker drains backup first, then picks whichever sweep is next by FIFO. Ordering between sweeps is undefined but immaterial: both run inside the maintenance window with a sub-second flag bounce.

**Individual endpoints — kept for ad-hoc triggers:**

- `POST /admin/backups/auto` — backup only
- `POST /admin/jobs/schedule-sweep?delay_minutes=N` — `update_sweep` only
- `POST /admin/jobs/schedule-seasonal?delay_minutes=N` — `seasonal_sweep` only

## CI

- **Backend Lint** (`backend-lint.yml`): `ruff check .` in `phsar/` — every push/PR
- **Backend Tests** (`backend-test.yml`): `pytest` against pgvector service container — every push/PR
- **Frontend Check** (`frontend-check.yml`): `bun run check` + `bun run test` — every push/PR
- **Build & Push Images** (`build-images.yml`): builds + pushes to ghcr.io — tag push (`v*`) or manual dispatch

## Linting Config (pyproject.toml)

Ruff excludes `alembic/versions` and `__init__.py` files. Import sorting is enabled (`extend-select = ["I"]`).

## Test Config

### Backend (pytest.ini)
- `asyncio_mode = auto` — no need for `@pytest.mark.asyncio` decorators
- Tests use the real database (not mocks); all changes are rolled back after each test

### Frontend (vite.config.ts)
- Vitest with jsdom environment and `@testing-library/svelte`
- `resolve.conditions: ['browser']` for Svelte 5 compatibility
- Tests mock SvelteKit modules (`$app/navigation`, `$app/environment`, `$app/state`) in `src/tests/setup.ts`

## License

PolyForm Noncommercial 1.0.0 — free for personal, educational, and non-commercial use.
