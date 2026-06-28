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

Dev DB helper scripts (audit, inspect, find, delete) live under `phsar/scripts/` — see [phsar/scripts/CLAUDE.md](phsar/scripts/CLAUDE.md) for the full list. Read-only by default; mutating scripts require `--apply`.

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
  - `GET /admin/stats/overview` — aggregate stats for the admin Overview tab (catalog totals, 7d job health by kind with retryable-failed subset, 7d activity counters, plus `sweep_tiers` + `media_sweep_tiers` cycle-membership breakdowns powering the SweepTiersCard anime/media toggle). Aggregate only — no per-user breakdowns; the Jobs Log surfaces those where they're needed for debugging
  - `GET /admin/jobs` — paginated all-jobs listing for the Jobs Log tab. Filters by status/kind/user_id/created_after/created_before; returns `AdminJobResponse` rows with `requested_by_username` flattened from the eager-loaded relationship and `parent_job_uuid` for clustered children. Backed by `ix_jobs_created_at_desc` (newest-first scan + matching COUNT). Default hides children (filters `parent_job_id IS NULL`); `?parent_uuid=<UUID>` expands a single seasonal_sweep's flock via the partial `ix_jobs_parent_job_id` index. `limit` capped at 500 so a sweep with hundreds of children can be expanded without paging
  - `GET /admin/jobs/{uuid}` — admin-only single-job detail fetch backing the `/admin/jobs/[uuid]` page. Returns the same `AdminJobResponse` shape the list emits (eager-loads `requested_by` + `parent` via the shared `_ADMIN_LOAD_OPTIONS` tuple in `JobDAO` so the list + detail paths can't drift)
  - `GET /admin/curation/pending-counts` — `{merge: int, split: int}` for the navbar bell's pinned admin reminder. Bell polls this on every tick when admin is logged in; cheap COUNTs on the status-filtered candidate tables. Sequential awaits per the AsyncSession-no-gather rule
  - Registration token management (list, create, delete)
  - Database backups (list, download, delete, rename, restore, upload)
    - `POST /admin/backups` and `POST /admin/backups/auto` (cron-token authed) both enqueue a `backup` job and return 202 with the job uuid so the request thread doesn't block on `pg_dump`
    - `PATCH /admin/backups/{filename}` sets/clears a dump's display `name`; a non-empty name pins it against auto-retention (admin actively chose to keep it), blank clears the pin
    - Manual backups attribute to the admin user (visible only in their bell); cron is a system job (`requested_by_user_id=null`), invisible to every bell — the dump list is the audit log
  - Merge-candidate review (list pending, merge, dismiss; powered by the duplicate detector)
    - `POST /admin/merge-candidates/backfill` re-runs existing × existing detection without a container restart — primarily for the post-restore workflow (restore is synchronous, so the lifespan-startup backfill never sees the restored catalog)
    - `GET /admin/merge-candidates/dismissed` + `POST /admin/merge-candidates/{uuid}/delete` (username-gated like restore) back the "Dismissed decisions" history: deleting a dismissed row drops the pair from `get_existing_pairs`' skip-set, so re-detection (sweep or Re-detect) resurfaces it as pending — the escape hatch for a wrong dismissal. Only `dismissed` rows are deletable (merged rows are already cascade-gone with anime B)
  - Split-candidate review (list pending, split, dismiss; powered by `find_disjoint_franchises` finding disjoint substance-passing chains under one anime row — the BNHA↔Vigilante, Toaru Index↔Railgun shapes)
    - `POST /admin/split-candidates/backfill` re-runs detection across the catalog on demand; idempotent via cluster-signature supersede in the DAO
    - Execute creates one new Anime row per detected cluster, re-parents the cluster's media (UUIDs stable so existing ratings stay attached), reclassifies both sides, and re-runs merge detection on the new rows
    - `GET /admin/split-candidates/dismissed` + `POST /admin/split-candidates/{uuid}/delete` mirror the merge pair: deleting a dismissed row clears its cluster-signature from the sticky-dismissal history so re-detection resurfaces it
  - Story-completion curation (v0.14.10) — a **manual** flag (no detector): admin marks an anime as story-complete (narrative concluded), distinct from MAL's broadcast `airing_status`. Backed by the `anime_completion` 1:1 sidecar (row-presence = finished)
    - `GET /admin/finished-anime` lists marked anime (cover + who/when audit) for the Completion tab; `POST`/`DELETE /admin/finished-anime/{anime_uuid}` mark/unmark (mark is idempotent). The tab's anime search reuses the public `/search/anime` — no admin-specific search query
    - Surfaced read-side as `AnimeDetail.is_finished` + `AnimeSearchResult.is_finished` (both via `selectinload(Anime.completion)`); the frontend renders a "Story Complete" badge on the anime page + anime search cards
  - Three cron-token-authed sweep schedulers:
    - `POST /admin/jobs/schedule-sweep?delay_minutes=N` — enqueues an `update_sweep` job (nightly catalog refresh + relations probe)
    - `POST /admin/jobs/schedule-seasonal?delay_minutes=N` — enqueues a `seasonal_sweep` job (weekly `/seasons/now` scrape)
    - `POST /admin/jobs/schedule-nightly?delay_minutes=N` — combined daily entry: backup (immediate, no banner needed since pg_dump is MVCC-snapshot), update_sweep (delayed), and — when `datetime.now(timezone.utc).weekday() == 6` (Sunday UTC) — a seasonal_sweep with the same delay so the weekly pickup piggybacks on the daily maintenance window
  - All three sweep schedulers set `core/maintenance.set_scheduled_at(...)` so the banner countdown shows
  - All three are bound to `Query(20, ge=0, le=1440)` on `delay_minutes`
  - All three are allowlisted in the maintenance gate so a cron retry while a sweep is running can't 503 the cron itself
  - All four cron-authed endpoints (including `/backups/auto`) share `JOBS_CRON_TOKEN` — one bearer for the whole machine-only surface
- **`/auth`** — `POST /auth/login` + `POST /auth/register` issue a JWT (`sub`, `role`, `exp`); `GET /auth/validate` checks one. `POST /auth/refresh` re-issues a fresh full-lifetime token to any **still-valid** token (an expired token 401s, same as `/validate`) — the sliding-session re-issue the frontend calls on activity (see Sliding session under Key Patterns). Bare `get_current_user` (not role-gated) so restricted/guest users keep their sessions alive too; role is re-read from the DB user
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

Business logic as module-level async functions. **Per-service design rationale lives in [phsar/app/services/CLAUDE.md](phsar/app/services/CLAUDE.md)** (loaded automatically when working in the backend tree).

Modules:
- `jikan_scraper.py` — MAL API client with retry, 1 req/s rate limiter, BFS in `search_title` (supports `seed_mal_id` for sweep probes)
- `job_worker.py` — single asyncio FIFO worker; `with_for_update(skip_locked=True)`; maintenance-aware
- `scrape_dispatcher.py` — handlers for `user_scrape` + `update_sweep`. v0.14.8 made `update_sweep` **media-level**: it selects the due *media* via `AnimeDAO.select_due_media_for_sweep`, groups them by parent anime, and refreshes only those media (`_refresh_one_anime(media_to_refresh)`) — `MediaFreshness` is the per-media refresh clock, `AnimeFreshness` the per-anime probe clock (probe gated by a 7-day floor). Writes a v5 `result_summary` (media-grained counters `media_refreshed`/`anime_touched`/`media_skipped_fresh`, the `anime_with_*` pair dropped; per-media field diffs + per-anime umbrella diffs + aggregated `unknown_genre_tags` + per-anime `step1_failures` + symmetric `probe_failures[]`). v0.14.5 relaxed the drift apply policy so genre + studio additions AND removals apply, with unknown genre tags surfaced for seeder review; v0.14.7 added `step1_failed`/`step1_failures[]`
- `seasonal_sweep_dispatcher.py` — `seasonal_sweep` handler (separate; pure discovery pass)
- `backup_dispatcher.py` — `backup` JobKind handler (no maintenance bracket — pg_dump is MVCC-snapshot)
- `progress_reporter.py` — throttled autocommit-tx progress writer
- `search_service.py` — BFS output → save/attach/merge decisions
- `vector_embedding_service.py` — sentence-transformers embeddings
- `media_search_service.py` / `anime_search_service.py` — filtered DB search (anime variant: two-phase GROUP BY + HAVING)
- `filter_service.py` — filter option values; view-type-aware. Also `fetch_genres` — all genres + descriptions for the frontend genre-badge tooltips (`GET /filters/genres`)
- `auth_service.py`, `user_settings_service.py`, `token_service.py`, `admin_service.py`
- `merge_detection_service.py` — duplicate detector (title_studio / title_desc / relation_link signals). `relation_link` reads from `media_relation_edges` sidecars (single source of truth — see services CLAUDE.md for rationale); three call sites (save, sweep, backfill) converge through `find_cross_anime_relation_pairs` so the signal fires identically regardless of how anime rows entered the catalog
- `merge_candidate_service.py` — admin merge operations
- `split_candidate_service.py` — admin split operations (list, dismiss, execute_split)
- `relation_classifier.py` — pure-function two-pass classifier (DB-less) + third-pass `find_disjoint_franchises` for split detection
- `anime_relation_service.py` — `reclassify_anime` orchestration; umbrella drift detection
- `anime_summary.py` — shared `summarize_anime(anime, rating_count)` helper for the merge + split admin cards
- `completion_service.py` — admin story-complete mark/unmark + the marked list (with cover + marked-by audit) for the Completion tab
- `rating_service.py` — rating CRUD + note search; logs watch events (first completion + rewatches) and derives `watched_count`. `get_rating_score_items` backs `GET /ratings/scores` — one wide projection consumed by both the RatingCard consistency helper (v0.14.11) and the `/ratings` page list + statistics (v0.14.12); the field list + wide-DTO trade-off live in the services CLAUDE.md + the `RatingScoreItem` docstring
- `spoiler_service.py` — frontier algorithm + `user_visible_media` cache
- `export_service.py` — flat media-level export
- `backup_service.py` — pg_dump/pg_restore orchestration; retention pools; `.current_db.json` pointer

#### daos/

Data access layer.

- **`BaseDAO`** — generic async CRUD
- **Specialized DAOs** (media, anime, anime_completion, genre, studio, user, user_settings, registration_token, rating, watch_event, job, merge_candidate, split_candidate) — domain-specific queries with vector similarity, filtering, aggregation
- **`AnimeDAO`**:
  - `search_anime_aggregated` — two-phase query: SQL GROUP BY with HAVING for filtering/ordering, then detail fetch
  - `select_due_media_for_sweep` — **media-level** four-tier sweep selection (v0.14.8): each atom is a direct predicate on the media row + its `MediaFreshness` sidecar (airing now / still stabilizing `stable_check_count < SWEEP_STABILIZE_THRESHOLD` / weekly recent main / `SWEEP_LONG_TAIL_DAYS` long tail), so a still-airing umbrella's stable members are no longer dragged through a refresh every night. Returns `Media` rows with the parent `Anime` + its full media set eager-loaded (the dispatcher groups by `anime.id`). `LIMIT` bounds MAL calls = media (the real 1 req/s cost unit). Replaced the anime-grained `select_due_for_sweep`. Backed by:
    - `ix_media_freshness_last_checked_at` (the ORDER BY + the `due_weekly`/`due_long_tail` staleness predicates)
    - `ix_media_airing_now` — partial index on `media(anime_id) WHERE airing_status = 'Currently Airing'`
    - `ix_media_main_aired_from` — composite `(anime_id, relation_type, aired_from)`
  - `score_top_percent(anime_id)` (v0.14.11) — rank of this anime among all scored anime by its confidence-weighted MAL score (`weighted_score_expr` = `score * log10(scored_by + 1)`, the shared search-ranking weight) as a rank-based "top N%" (worst = 100); `None` when unscored. `MediaDAO.score_top_percent(media_id)` is the per-media analogue. Both surface as `score_top_percent` on the detail responses (anime ranks among anime, media among media) → the frontend "Top N%" chip. Query-shape rationale (window vs `count FILTER`, why no metric index, SQL/Python parity via the drift test) lives in `compound-docs/2026-06-22-v0.14.11-further-qol.md`
  - `count_by_sweep_tier_priority` / `count_media_by_sweep_tier_priority` — anime- and media-grained membership-bucket counts for the admin Overview SweepTiersCard toggle; both use the shared atoms (`_sweep_atoms` / `_media_sweep_atoms`) and the shared `_tier_bucket` CASE. `SWEEP_STABILIZE_THRESHOLD` (3) and `SWEEP_LONG_TAIL_DAYS` (90) are single constants shared by media + anime so the two grains can't drift. The stabilizing total is further split into `stabilizing_by_check` (counts per `stable_check_count` 0…threshold-1) so the card can show the stabilization pipeline — media grain by the media's own count, anime grain by its least-settled member (a correlated `MIN` over the anime's media); dynamic in the threshold
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
- **`ratings.py`** — `watch_status` enum (`completed`/`on_hold`/`dropped`, replaced the legacy `dropped` boolean in v0.14.10) + 11 optional attribute enums; one row per (user, media)
- **`watch_event.py`** — append-only watch/rewatch log keyed to (user_id, media_id), NOT to a rating row (so history survives a rating delete + re-add). `watched_count` is derived `COUNT(events)`, never stored. Both FKs `ON DELETE CASCADE`; no ORM back-relationships (read only via grouped count queries in `WatchEventDAO`). `watched_at` (distinct from `created_at`) is the watch moment, for future time-series analysis
- **`user_settings.py`** — per-user preferences (1:1 with Users) with enums for theme, name language, search view, rating step, spoiler level
- **`user_visible_media.py`** — precomputed spoiler-visibility cache per user, updated on rating changes
- **`merge_candidate.py`** — admin-reviewable duplicate pairs
  - Status enum: `pending`/`dismissed`/`merged`
  - FK cascades on both anime ids — merging or deleting either anime cleans up dangling rows
  - Unique constraint + check on `(anime_a_id, anime_b_id)` with caller-enforced ascending order so `(A,B)` and `(B,A)` collapse
- **`split_candidate.py`** — admin-reviewable disjoint-franchise rows
  - Status enum: `pending`/`dismissed`/`split`
  - Asymmetric to `merge_candidate`: 1 source anime + JSONB `clusters` payload (one entry per disjoint chain detected). No anime_b_id — splits are single-source-multi-target
  - FK cascade on `anime_id` — deleting or merging the source anime cleans up the row
  - One-pending-per-anime convention enforced by DAO: `upsert_pending` supersedes the existing pending row when the cluster signature changes (cheaper than partial-unique-constraint migration on enum-status predicates)
- **`job.py`** — background job queue
  - `JobKind` enum: `user_scrape`, `update_sweep`, `seasonal_sweep`, `backup`, `restore`
  - `JobStatus` enum: `queued`/`running`/`succeeded`/`failed`
  - JSONB `payload`, progress fields (`stage`, `items_done`, `items_total`), `not_before_at` for scheduled-delay jobs
  - `result_summary` JSONB carries `retryable: bool` for the bell
  - `version: int NOT NULL DEFAULT 1` — per-kind schema version for `result_summary`. Runtime source of truth is the `JOB_KIND_VERSIONS` registry in `app/core/job_versions.py`; every Job-construction site goes through the `make_job(kind, **kw)` helper which stamps the current registry value. Frontend dispatches on `(kind, version)` so historical rows render with the correct schema. Bump the integer per kind when its result_summary shape changes (current: `update_sweep` at v6 after v0.14.9 added `probe_attached_anime[]` + `counters.probe_attached_media_count`; all others at v1)
  - Partial composite index on `(created_at) WHERE status='queued'` keeps the worker's FIFO claim cheap regardless of finished-row volume
- **`anime_completion.py`** — 1:1 sidecar (`unique=True` on FK) for the admin story-complete flag (v0.14.10). **Row-presence = finished** (no boolean): marking inserts, unmarking deletes. `marked_by_user_id` (FK `SET NULL`) + `created_at` are the who/when audit. Sidecar so the admin flag can't leak into the anime Pydantic schemas; surfaced explicitly as `is_finished` on detail + search results
- **`anime_freshness.py`** / **`media_freshness.py`** — 1:1 sidecars (`unique=True` on FK) for the nightly update sweep
  - Both hold `last_checked_at` + `stable_check_count` outside canonical rows so sweep cadence can't leak into Pydantic schemas via `model_dump()`. v0.14.8 added `stable_check_count` to `media_freshness` (server_default 0): `MediaFreshness` is the per-media **refresh** clock that drives `select_due_media_for_sweep`; `AnimeFreshness` is the per-anime **probe** clock
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
  - `embedding_backfiller.py` — `backfill_embeddings` detects and regenerates **missing** anime/media/rating embeddings (enables seamless embedding model swaps via Alembic migration + restart). `reembed_all_embeddings` regenerates **every** embedding in place (delete+insert per row, batched commits) — the one-time re-normalization path after a `generate_embedding` change (e.g. the query/document case-fold); gated by `EMBEDDING_REEMBED_ON_STARTUP`, fired post-yield so a ~5-9 min catalog re-encode can't block /health
  - `relation_backfiller.backfill_relations` — gated by `RELATION_BACKFILL_ON_STARTUP`. Re-runs the two-pass classifier over every Anime via `anime_relation_service.reclassify_anime` AND `detect_split_candidates_for_anime` inside the same per-anime SAVEPOINT. Lazy-fetches MAL relations (~1 req/s) checkpoint incrementally so a crash mid-run doesn't lose hours of pagination. `dry_run=True` powers the audit checkpoint (see `phsar/scripts/audit_relation_backfill.py`); supports `anime_ids` filter for the admin re-classify endpoint and tests
  - `merge_detection_service.backfill_merge_candidates` — one-shot existing × existing pair sweep so duplicates pre-dating the detector get flagged on first restart after upgrade
  - `split_candidate_backfiller.backfill_split_candidates` — one-shot disjoint-franchise detection across the catalog; runs after `backfill_merge_candidates` so resolved pairs don't surface duplicate split candidates. Pure structural (no MAL calls); idempotent on repeat restarts
  - `save_service.save_search_results` triggers a spoiler-cache recompute **scoped to the newly-created anime** (`refresh_spoiler_cache_for_anime_ids`) after new animes land — load-bearing for existing `spoiler_level=hide` users whose populated cache stays stale (startup backfill skips them since they have rows)
  - The sweep dispatcher's relations probe goes through `save_service.attach_search_result_to_anime` instead, which intentionally does *not* recompute per-batch; the dispatcher fires one coalesced scoped `refresh_spoiler_cache_for_anime_ids` over the probe-attached anime at sweep end
- **exceptions.py** — custom exception hierarchy rooted at `PhsarBaseError` with `status_code` attribute
  - Single exception handler in `main.py` reads the status code from each class
  - `PermanentPhsarError` — marker subclass for non-retryable failures:
    - `AnimeNotFoundError`, `MainMediaNotFoundError`, `MalIdAlreadyExistsError`, `AnimeFilteredOutError`
    - `JobWorker` reads via `isinstance` and stamps `result_summary.retryable = False`
  - `TransientUpstreamError` — outside the permanent branch; raised when MAL returns 200 OK with empty data on a valid mal_id
    - Bell keeps retry button; `classify_error` tags as `upstream_outage` for friendly copy
  - `AnimeFilteredOutError` (sibling to `AnimeNotFoundError` under permanent) — surfaces when seeded BFS returns nothing AND seed mal_id is in `media_unwanted`; admin sees `"'X' was filtered out as Music"` instead of misleading "not found"
- **main.py** — app factory + lifespan
  - Startup sequence: seeders → embedding backfill → `JobDAO.reap_orphans` → `job_worker.register_dispatcher` (for each of `user_scrape`, `update_sweep`, `seasonal_sweep`, `backup`) → `job_worker.start()` → yield → post-yield backfills (optional one-shot full re-embed when `EMBEDDING_REEMBED_ON_STARTUP` → relation-backfiller → merge-candidate backfill → split-candidate backfill). Post-yield backfills run in `asyncio.create_task` so /health responds during the ~14-min relation cold start; split detection runs LAST so it sees relation-backfiller's TERMINAL sidecars and merge-backfiller's collapsed pairs
  - Shutdown: `job_worker.stop()`
  - Direct endpoints: `GET /` and `GET /health`
    - Health returns `{status, version, db}` and pings DB with 2s `asyncio.wait_for` so transient unavailability produces a fast 503 instead of riding asyncpg's 60s connect timeout into a Coolify liveness flap
  - Registers `MaintenanceGateMiddleware` — see Maintenance Mode under Key Patterns

### Frontend (phsar/frontend/)

SvelteKit with file-based routing, Svelte 5 runes, Tailwind CSS 4, shadcn-svelte component library. **Component / store / theme details live in [phsar/frontend/CLAUDE.md](phsar/frontend/CLAUDE.md)** (loaded automatically when working in the frontend tree).

Quick map:
- `routes/` — pages + `GET /health` for Coolify liveness. The `/ratings` page (v0.14.12 — anime-level list + ECharts statistics, both client-side off the one `GET /ratings/scores` fetch) consolidated the old `/statistics` nav placeholder, which is gone
- `lib/api.ts` — centralized API client with maintenance-503 handler
- `lib/stores/` — auth, settings, spoiler visibility, bell session, cross-component bumps (`jobs.ts`, `maintenance.ts`, `bell-session.ts`), global toast (`toast.ts`)
- `lib/utils/` — formatters, search params, chart colors, client-side spoiler frontier
- `lib/themes.ts` + `src/app.css` — centralized theme system (CSS custom props + `.theme-*` overrides)
- `lib/components/` — MaintenanceBanner, JobBell, BackupsCard, MergeCandidatesCard, SplitCandidatesCard, RatingsOverview, Toast/ToastHost (global toast host in the layout), attribute viz, etc.
- `lib/components/ui/` — shadcn-svelte base components
- `tests/` — Vitest + @testing-library/svelte

### Key Patterns

- **Dependency injection**: FastAPI `Depends()` for DB sessions, current user extraction, role-based access (`require_roles()` accepts `RoleType` enum)
- **Role-based access**: three roles — `admin`, `user`, `restricted_user`
- **Sliding session / idle timeout**: the JWT `exp` is a short idle clock (`ACCESS_TOKEN_EXPIRE_MINUTES=10`), not a hard ceiling
  - Backend is stateless: no refresh-token table, no absolute session cap. `POST /auth/refresh` simply re-issues a fresh token to any still-valid one (see the `/auth` router)
  - The frontend owns the policy (`lib/components/SessionTimeoutBanner.svelte` + pure `lib/utils/sessionTimeout.ts`): a 1s tick reads `exp`, silently refreshes on recent activity, shows a countdown warning banner over the last 3 min when idle, and triggers logout at expiry. An **active** user is never logged out; an idle one is warned then signed out — see the frontend CLAUDE.md for the full component/constant rationale
  - Security note: shortening the token only tightens the *passive-leak* window; the token lives in `localStorage`, so XSS (which can also call `/auth/refresh`) is the real exposure. HttpOnly-cookie auth is the bigger lever and is out of scope
- **Async throughout**: asyncpg driver, SQLAlchemy AsyncSession, async service/DAO methods
  - All ORM relationships use `lazy="raise"` to prevent implicit lazy loading — every relationship access must go through explicit `selectinload` in the DAO query
  - **🎯 Never `asyncio.gather` coroutines that share one `AsyncSession`** — SQLAlchemy's AsyncSession can't multiplex concurrent operations on a single session, and `gather` corrupts the in-flight query state. Pure-CPU coroutines (e.g. `to_thread.run_sync` over an embedding encode) that don't touch the session are fine to gather; anything that touches the session must run sequentially. See the inline comment at `seasonal_sweep_dispatcher.py:48-51` for the canonical "don't" example and `compound-docs/2026-05-09-v0.14.0-content-pipeline.md` (LANDMINE entry) for the failure mode.
- **Vector search**: `paraphrase-multilingual-MiniLM-L12-v2` model, pgvector storage
  - **Case-folded**: `generate_embedding` lowercases before encoding. The model is *cased*, so without this the same query in different capitalisation produced a materially different vector — enough to reorder title results and bury the intended show (capitalising a query dropped it off the page). Folding in the one chokepoint every embedding passes through keeps the query and the stored documents in one case space. Existing catalog vectors are re-normalized by `reembed_all_embeddings` (see seeders)
  - `SearchType` enum (`title`, `description`, `rating_notes`) selects the target
  - `ViewType` enum (`anime`, `media`) selects the search mode
  - Filter schemas use inheritance: `MediaSearchFilters` (base) → `RatingSearchFilters` (adds rating-specific filters)
  - Anime-level title search uses `AnimeSearch` embeddings directly; description search averages cosine distances across media
  - `/filters/options?view_type=anime` returns anime-appropriate filter ranges (aggregated episodes/watch time, majority genres)
  - `/filters/genres` returns every genre's `{name, description}` — the frontend caches it once and looks up descriptions for the genre-badge tooltips on the anime/media pages
- **Domain exceptions**: all custom exceptions extend `PhsarBaseError` with `status_code`. One handler in `main.py`. See exceptions.py above for hierarchy
- **Theme system**: CSS custom properties with `@property` indirection
  - `@property --primary` / `--ring` hold source values, `@theme inline` references via `var()`, `.theme-*` classes override
  - Why: forces Tailwind to emit `var()` in utilities instead of inlining static values
  - Components use semantic tokens (`bg-primary`, `text-primary`, `ring-ring`)
  - Centralized config in `lib/themes.ts`; FOUC prevention via inline localStorage script in `app.html`
  - Per-theme chart color palettes in `chartColors.ts` avoid hue clashes
- **Two-pass relation classifier + third-pass split detection**: scrape-time + merge-time + backfill-time. See [compound-docs/2026-05-11-jikan-scraper-quirks.md](compound-docs/2026-05-11-jikan-scraper-quirks.md) for v0.14.1 classifier rationale and [compound-docs/2026-05-18-v0.14.2-split-candidates.md](compound-docs/2026-05-18-v0.14.2-split-candidates.md) for the third pass
  - Pass 1 (`jikan_scraper.search_title`) captures relation **edges** during BFS — no classification baked in. TERMINAL nodes (arrived via identity-breaking edges) now fetch `/relations` so their outgoing edges land in the sidecar (the v0.14.2 split-candidates change), but the BFS still does NOT recurse from them — the graph stays bounded. Sidecars persist edges unfiltered, including dangling targets
  - Pass 2 (`relation_classifier.classify_anime_relations`) picks a canonical anchor by substance gate + tier (TV > ONA > Movie) + oldest aired_from, builds main chain via sequel/prequel closure, classifies alt-chain via `alternative_version` edges, defaults rest to `side_story`; demotes weak Mains via substance gate and recaps (`full_story`) to `summary`. **Not-yet-aired entries** get a provisional substance pass (so an announced sequel stays Main) but are **anchor-ineligible** (a franchise can't anchor on something unaired) — see services CLAUDE.md. The `AIRING_STATUS_*` sentinels live in `relation_classifier` (re-imported by `jikan_scraper`)
  - Pass 3 (`relation_classifier.find_disjoint_franchises`) takes the classified graph and flags substance-passing media outside the anchor's main+alt chain that form their own connected sub-chain — the Overlord+Eminence, BNHA+Vigilante, Toaru Index+Railgun shapes. Conan-exception: movie-only clusters bridged via `parent_story` or `summary` are legitimate side-story chains and stay quiet. Surfaces as a `split_candidate` for admin review; never auto-splits
  - `RelationType.AlternativeVersion` enum value distinguishes retellings (Evangelion TV ↔ Rebuild Movies, Hokuto no Ken alts) from genuine side stories. Spoiler frontier treats alt-version as an anchor
  - Same three passes run at three sites: scrape (per BFS-result), merge survivor (consolidated A∪B), backfiller (per catalog row)
  - Bridge edges across previously-different-anime boundaries: persisted unfiltered in sidecars; classifier's `_build_adjacency` filters dangling endpoints at adjacency-build time. Merge consolidation surfaces bridges that were dangling at scrape time (Dr. Stone split-merge case)
  - Backfiller (`relation_backfiller`) lazy-fetches `/anime/{id}/relations` for media with empty sidecars; per-anime commit checkpoints incrementally so a 14-min cold start can't lose progress
  - `anime_relation_service.reclassify_anime` is the orchestration helper; rewrites all 7 umbrella fields (mal_id, title, name_eng, name_jap, other_names, description, cover_image) on any drift, regenerates embedding only on title-affecting drift
- **Spoiler protection**: three levels (`off`/`blur`/`hide`) via `SpoilerLevel` user setting
  - Frontier algorithm: per anime, all media up to and including the next unwatched **anchor** (`main` or `alternative_version`) entry are visible — retellings extend the story so each alt-version gates the next
  - Precomputed in `user_visible_media`; updated per-anime on rating changes, per-user on registration, and **scoped to the changed anime** after catalog mutations (save / sweep / merge / split) via `refresh_spoiler_cache_for_anime_ids`. `backfill_spoiler_visibility` (startup) is the only whole-catalog path
  - **Restricted (guest) users are pinned to `spoiler_level=off` and excluded from the cache** (they can't rate). See services CLAUDE.md for the enforcement points; the settings UI renders their rating-related controls disabled rather than hidden
  - Backend `GET /ratings/spoiler-visibility` returns visible UUIDs; frontend stores as `Set` in `spoilerVisibility` store
  - `SpoilerGuard.svelte` wraps covers/descriptions with blur + click-to-reveal
  - Detail pages compute frontier locally for fresher data
  - `hide` mode in media search uses `WHERE media.id IN (...)` from the cache
  - Anime covers/descriptions are never spoiler-protected
- **Background jobs**: single asyncio FIFO worker (`job_worker.py`) drains the `jobs` table
  - JobKinds: `user_scrape`, `update_sweep` + `seasonal_sweep` (bracket maintenance), `backup` (does NOT bracket)
  - **Per-kind result_summary versioning**: `JOB_KIND_VERSIONS` registry in `app/core/job_versions.py` + `make_job()` helper at every Job-construction site. Frontend reads `job.version` to dispatch the parser. Bump the integer per kind when the shape changes — see `models/job.py` for the column rationale
  - **Hardened failure path** (v0.14.5): three guards keep `dispatch_one` from stranding a job in `running` after a downstream crash — (1) `str(job.uuid)` pre-captured immediately after claim so the failure logger never reads ORM attrs on a poisoned session, (2) the `work_session.rollback()` is wrapped in try/except so a PendingRollback cleanup failure doesn't escape, (3) an outer catch-all around the work-session block routes unexpected plumbing bugs through `mark_failed` instead of letting them propagate to the `_run` loop. The fail-session write is also wrapped — worst case it logs the failure and leaves the row for `reap_orphans` on next startup
  - Per-user concurrent cap: `JOBS_PER_USER_LIMIT=4` enforced at submission time (bounds queue depth, not concurrency — worker stays sequential because MAL's rate limit means parallel jobs just fragment bandwidth)
  - Per-user daily cap: `JOBS_DAILY_LIMIT=50` rolling 24h on top of the concurrent cap. **Admins are exempt** (trusted operators — catalog seeding/fixing; the concurrent cap + dedup still bound them). Counts every status (succeeded/failed too) so a fast-failing client can't cycle through the limit; 51st submission returns 429 marked `PermanentPhsarError` so the bell hides retry. Backed by partial composite `ix_jobs_user_scrape_recent (requested_by_user_id, created_at DESC) WHERE kind='user_scrape'` so per-POST cost stays O(in-window-rows)
  - System jobs submit with `requested_by_user_id=null` to skip cap
  - `ProgressReporter`: handlers stream `(stage, items_done, items_total)` to the bell before the job tx commits (autocommit txes, 0.5s throttle)
  - `PermanentPhsarError` gates retry: deterministic failures stamp `retryable = False`, bell hides retry button
  - `TransientUpstreamError` stays outside marker → retryable bell entry
  - Per-query dedupe at submission: same normalized query within `JOBS_DEDUPE_HOURS` returns 409 (failed jobs don't count, so transient outage doesn't lock users out)
  - Crash recovery: `JobDAO.reap_orphans` runs at lifespan startup, marks `running` → `failed`
  - Bell cadence: 2s active poll while anything is queued/running, 30s idle
  - Optimistic-stub pattern: pages that enqueue push a `queued` stub keyed on `job_uuid` into `optimisticJobs` store; bell merges optimistic ∪ fetched (UUID-deduped); `reconcileOptimisticJobs(fresh)` prunes landed entries
  - Bell completion toasts (v0.14.13): on an active→finished transition the bell fires a green/red global toast (`pushToast`) for `user_scrape` + `backup`; opening the bell now also acknowledges still-running jobs so the badge is dismissible mid-fetch, and succeeded scrape/backup rows are clickable (→ `/library/add` / `/admin?tab=backups`). Frontend-only — see `frontend/CLAUDE.md`
  - Parent-child clustering: `seasonal_sweep_dispatcher` stamps `parent_job_id=parent.id` on every enqueued `user_scrape` child (self-referential FK with `ON DELETE SET NULL` so deleting the parent doesn't cascade-delete audit history). Backs the admin Jobs Log expander — default list hides children (`parent_job_id IS NULL`), `?parent_uuid=<UUID>` returns the flock under that sweep. Historical pre-FK rows can be retro-clustered via `scripts/backfill_seasonal_sweep_parents.py` (safe because the dispatcher is the only production source of NULL-user user_scrapes)
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
- `ACCESS_TOKEN_EXPIRE_MINUTES` — default 10; JWT lifetime = the sliding-session idle clock (frontend refreshes on activity, warns over the last 3 min, logs out at expiry — see Sliding session under Key Patterns)
- `CORS_ORIGINS` — JSON list of allowed origins
- `GUEST_USERNAME` + `GUEST_PASSWORD` — seeds a read-only guest account with `restricted_user` role
- `APP_VERSION` — deployed version tag surfaced on `/health`; injected via backend Dockerfile build arg
- `BACKUP_DIR` — where dumps are written; defaults to `./backups` (native dev), Dockerfile sets to `/backups` (bind-mounted volume)
- `BACKUP_RESTORE_TIMEOUT_SECONDS` — default 600; raise if DB grows large enough that pg_restore legitimately takes >10 min (a mid-restore kill leaves the DB half-dropped)
- `JOBS_CRON_TOKEN` — shared bearer secret for every cron-authed endpoint (`/admin/backups/auto`, the three sweep schedulers); empty disables all four, they fail closed
- `JOBS_PER_USER_LIMIT` — default 4; max queued+running user_scrape jobs per non-system user; 5th submission returns 409
- `JOBS_DAILY_LIMIT` — default 50; max user_scrape submissions per non-system, non-admin user in any trailing 24h window (counts all statuses); 51st returns 429. Admins are exempt
- `JOBS_DEDUPE_HOURS` — default 24; same scrape query within this window returns 409 unless prior job failed
- `JOBS_SWEEP_MAX_PER_RUN` — default 500; bounds the nightly `update_sweep` batch (a **media** count since v0.14.8, was anime). Only binds during the post-migration herd + stabilizing bursts; steady-state sweeps finish in seconds
- `RELATION_BACKFILL_ON_STARTUP` — default `True`; runs `relation_backfiller` at lifespan startup. First cold start fetches missing `MediaRelationEdges` sidecars from MAL at 1 req/s (~14min for an 800-media catalog); subsequent restarts skip already-populated rows and finish in seconds. Disable for tight maintenance windows on fresh deployments
- `EMBEDDING_REEMBED_ON_STARTUP` — default `False`; when `True`, regenerates **every** search embedding in place at startup (`reembed_all_embeddings`) so the catalog picks up a `generate_embedding` change (the query/document case-fold). Runs post-yield in the background (can't block /health). A ~5-9 min catalog re-encode on the 2-vCPU VM, wasteful on every restart — flip ON for a single deploy, watch for the `Re-embed complete` log line, then flip OFF

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
  - Bell tracks progress (`Dumping` → `Verifying backups` → `Applying retention` → `Done`); on success BackupsCard auto-refreshes. The verify stage re-runs `pg_restore --list` across all dumps (cheap, TOC-only) so on-disk corruption stops listing as `ok` before retention picks its known-good pin
  - "Create backup" button debounces for 5s to absorb double-clicks
  - Download/delete/rename/restore/upload from the same UI; restore stays synchronous (meant to be blocking)
  - Rename (pencil): names a dump and **pins** it against auto-retention; an inline "Remove name" button (or saving a blank name) unpins. Named rows show a "Pinned" badge
- Scheduled backups: driven by `/admin/jobs/schedule-nightly` (see Scheduled Jobs below)
  - Standalone `POST /admin/backups/auto` stays available for backup-only ad-hoc cron
  - Retention runs after **every** backup job — three pools (archival manual+cron: 14-recent + latest-per-Sunday×8 + most-recent-known-good; pre-restore relevance buffer; uploads 5-recent). Named/pinned dumps are kept on top of each pool's rolling window (they don't consume slots), so manual-only installs don't accumulate indefinitely while admin-chosen keeps survive
- Off-host safety net: `scripts/pull-backups.sh user@vm` rsyncs `/opt/phsar/backups/` to local machine; run every ~2 months and before any restore
- Restore workflow: UI prompts for admin's username as confirmation string; automatic pre-restore snapshot first, then `pg_restore --clean --if-exists --no-owner --no-privileges`. The restored dump's row shows "Previous state saved as …" linking to its pre-restore snapshot (the pre-restore tied to the current state is retention-pinned)

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
