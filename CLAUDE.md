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
cp .env.example .env
docker compose up --build
```

## Architecture

### Backend (phsar/app/)

Layered architecture with strict dependency flow: **routers → services → DAOs → models**

- **routers/** — FastAPI endpoint definitions. Each router maps to an API prefix (`/admin`, `/auth`, `/search`, `/filters`, `/media`, `/save`, `/seed`, `/ratings`, `/users`, `/jobs`, `/library`, `/maintenance`). `/admin` handles registration token management (list, create, delete — admin-only), database backups (list, create, download, delete, restore, upload — admin-only; plus `/admin/backups/auto` for scheduled dumps, authenticated via a cron bearer token), and merge-candidate review (list pending, merge, dismiss — admin-only; powered by the duplicate detector). `/search` handles both `/search/media` (per-media) and `/search/anime` (aggregated by anime). `/media` handles both `/media/{uuid}` and `/media/anime/{uuid}`. `/users` handles settings CRUD, data export, and account deletion. `/jobs` handles user-triggered background work (`POST /jobs/scrape` enqueues a `user_scrape` job; `GET /jobs/mine` lists the current user's active + recently-finished jobs; `GET /jobs/{uuid}` single-job poll for owner or admin). `/library` exposes `GET /library/recent` for the `/library/add` page's recent-additions panel. `/maintenance` exposes a public `GET /maintenance/status` returning `{active, scheduled_at}` for the frontend's pre-warning banner; allowlisted in the maintenance HTTP middleware so it keeps returning truthful state mid-window.
- **services/** — Business logic as module-level async functions:
  - `jikan_scraper.py` — MAL API client with retry. Tenacity tuned to `wait_exponential(multiplier=2, min=1, max=30)` × 5 attempts for better tail behavior on transient MAL outages. BFS in `search_title` accepts an optional `ProgressReporter` so user-scrape jobs can stream progress to the bell.
  - `job_worker.py` — single asyncio FIFO worker draining the `jobs` table. Per-user cap (`JOBS_PER_USER_LIMIT=4`); claims jobs via `with_for_update(skip_locked=True)`; `wakeup` Event for sub-second pickup with a 60s wall-clock fallback. Dispatcher table maps `JobKind → handler` (registered from `main.py` lifespan). On failure, stamps `result_summary.retryable = not isinstance(failure, PermanentPhsarError)` so the bell knows whether to show a retry button. Sequential per-job sessions (claim-tx then work-tx in fresh sessions) avoid asyncpg pool deadlocks under nested-savepoint patterns. Sweep-kind jobs (`update_sweep`, `seasonal_sweep`) are bracketed in maintenance mode by the worker — `set_maintenance(True)` before dispatch, `set_maintenance(False)` + `set_scheduled_at(None)` in `finally` so a dispatcher crash can't leave the flag stuck behind a 503 until restart.
  - `scrape_dispatcher.py` — handler for `user_scrape` jobs. Wraps the existing `handle_search_mal_api_results` + `save_search_results` pipeline behind a `ProgressReporter` so the bell sees mid-flight progress without waiting for the whole job tx.
  - `progress_reporter.py` — short-lived autocommit-tx writer that pushes `(stage, items_done, items_total)` updates to a job row. 0.5s throttle (with `force=True` bypass for stage transitions) keeps tight BFS loops from opening hundreds of sessions per second.
  - `vector_embedding_service.py` — sentence-transformers embeddings.
  - `media_search_service.py` / `anime_search_service.py` — filtered DB search. Anime variant uses a two-phase query (GROUP BY + HAVING for filter/order, then detail fetch) with majority-genre logic.
  - `filter_service.py` — filter option values; view-type-aware for anime vs media ranges.
  - `auth_service.py` — registration, authentication, token issuance, account deletion.
  - `user_settings_service.py` — user settings CRUD + default creation.
  - `token_service.py` — compressed JWT for shareable filter URLs.
  - `admin_service.py` — registration token list + delete.
  - `merge_detection_service.py` — duplicate-anime detector. Three signals feed the `merge_candidates` table: `title_studio` (SequenceMatcher ratio OR containment ≥ 0.85, gated by studio overlap; containment additionally requires a word-boundary on both sides of the match in the longer string AND a size floor of `MIN_CONTAINMENT_MATCH_CHARS=4` chars OR a full match where the shorter title is itself ≥ `MIN_FULL_MATCH_CHARS=3`), `title_desc` (weaker title match + description-embedding cosine ≥ 0.85), `relation_link` (BFS surfaced a non-crossover related media that lives under a different anime). Detection runs at the end of `save_search_results` (new × existing); a startup `backfill_merge_candidates` covers existing × existing. `seen_pairs` pre-fetch short-circuits flagged or admin-resolved pairs before any similarity computation.
  - `merge_candidate_service.py` — admin operations on merge candidates: list pending (ranked per-pair by `(earliest aired_from ASC nulls last, rating_count DESC, anime_id ASC)` so the recommended-keep side is surfaced as A; uses `MergeCandidateDAO.get_rating_counts_for_anime` for the tiebreak), dismiss (status flip), and merge (re-parents B's media onto A, deletes B via cascade, refreshes A's anime embedding, runs `detect_merge_candidates` against the survivor so freshly-valid pairs from the merged media get flagged, recomputes spoiler cache for all users). The merge accepts an optional `keep_uuid` to swap which side survives — the DB invariant `anime_a_id < anime_b_id` is unchanged, A/B is a presentation label only. Fail-loud on shared `Media.mal_id` between A and B since that's a global-unique-violation that needs human review.
  - `rating_service.py` — rating CRUD + note search; triggers a spoiler-visibility recompute on every change.
  - `spoiler_service.py` — frontier algorithm + precomputed visibility cache in `user_visible_media`; recomputed per-anime on rating changes, per-user on registration, and per-user after new scrapes land via `save_service`.
  - `export_service.py` — flat media-level export merging catalog + ratings + watchlist; respects user's `name_language` for localized title columns.
  - `backup_service.py` — pg_dump/pg_restore orchestration: atomic `.partial` writes, sidecar `.meta.json`, content-hash dedupe, retention (14 daily + 8 Sunday; never evicts the most recent known-good dump), pre-restore auto-snapshot. `.current_db.json` pointer tracks which dump matches the live DB, set by restore, dedupe-confirm, or first unique dump on a fresh install. All write paths serialized via a module-level `asyncio.Lock` (single-worker assumption). Restore flips a maintenance flag so other requests 503 during the window. Subprocess password via `PGPASSWORD`, never on the CLI. Deeper design notes: [compound-docs/2026-04-19-v0.13.0-deployment.md](compound-docs/2026-04-19-v0.13.0-deployment.md).
- **daos/** — Data access layer. `BaseDAO` provides generic async CRUD; specialized DAOs (media, anime, genre, studio, user, user_settings, registration_token, rating, job, merge_candidate) add domain-specific queries with vector similarity, filtering, and aggregation. `AnimeDAO.search_anime_aggregated` uses two-phase query: SQL GROUP BY with HAVING for filtering/ordering, then detail fetch. `search_filters.py` provides shared filter/ordering helpers for media, anime pre-aggregation (WHERE), and anime post-aggregation (HAVING) filters. `JobDAO` provides claim-skip-locked dispatch + crash recovery: `reap_orphans` runs at startup and flips any `running` rows to `failed` so a mid-job process restart doesn't leave them stuck.
- **models/** — SQLAlchemy ORM models mapped to PostgreSQL tables. `media_search.py` stores pgvector embeddings for title and description; `anime_search.py` stores anime-level embeddings; `rating_search.py` stores note embeddings for rating note search. `user_settings.py` stores per-user preferences (one-to-one with Users) with enums for theme, name language, search view, rating step, and spoiler level. `user_visible_media.py` is a precomputed cache of which media are visible (not spoiler-protected) per user, updated on rating changes. `merge_candidate.py` stores admin-reviewable duplicate pairs with status enum (`pending`/`dismissed`/`merged`); FK cascades on both anime ids so merging A into B (or deleting either anime) cleans up dangling rows. Unique constraint + check on `(anime_a_id, anime_b_id)` with caller-enforced ascending order so `(A,B)` and `(B,A)` collapse. `job.py` stores the queue of background jobs with `JobKind` enum (`user_scrape`, `update_sweep`, `seasonal_sweep`), `JobStatus` enum (`queued`/`running`/`succeeded`/`failed`), JSONB payload, progress fields (`stage`, `items_done`, `items_total`), `not_before_at` for scheduled-delay jobs, and `result_summary` JSONB (carries `retryable: bool` for the bell); partial composite index on `(created_at) WHERE status='queued'` keeps the worker's FIFO claim cheap regardless of finished-row volume. `anime_freshness.py` / `media_freshness.py` are 1:1 sidecars (`unique=True` on the FK column) for the nightly update sweep — they hold `last_checked_at` (and `stable_check_count` on the anime side) outside the canonical catalog rows so sweep cadence can't leak into Pydantic schemas via `model_dump()`. Existing rows are backfilled to the parent's `created_at` so the sweep enters them at honest age, not "never checked."
- **schemas/** — Pydantic request/response DTOs.
- **core/** — Config (`config.py` loads from `.env`), database engine (`db.py`), auth dependencies (`dependencies.py` — JWT user dep + `require_roles()` factory + a generic `require_bearer_token(settings_attr, error_factory)` factory used by both `BACKUP_CRON_TOKEN` and `JOBS_CRON_TOKEN` cron-authed endpoints), JWT/password security (`security.py`), process-wide maintenance state (`maintenance.py`: `_active` flag flipped by destructive ops + `_scheduled_at` future-window pointer set by the schedule-sweep cron endpoint when it enqueues a delayed sweep; both are module globals, single-process assumption).
- **seeders/** — Run at app startup via lifespan; seed genres, admin user, and optional guest user (restricted_user role). `backfill_user_settings` ensures all users have a UserSettings row. `backfill_spoiler_visibility` computes visible media for users with no cache rows. `embedding_backfiller.py` detects and regenerates any missing anime, media, or rating embeddings (enables seamless embedding model swaps via Alembic migration + restart). `merge_detection_service.backfill_merge_candidates` does a one-shot existing × existing pair sweep so duplicates that pre-date the detector get flagged on first restart after upgrade. `save_service.save_search_results` also triggers a full-user spoiler-cache recompute after new animes land so `spoiler_level=hide` doesn't mask them until the next restart.
- **exceptions.py** — Custom exception hierarchy rooted at `PhsarBaseError` with `status_code` attribute. Single exception handler in `main.py` reads the status code from each exception class. `PermanentPhsarError` is a marker subclass for failures where retry won't help (`AnimeNotFoundError`, `MainMediaNotFoundError`, `MalIdAlreadyExistsError`); `JobWorker` reads the marker via `isinstance` and stamps `result_summary.retryable = False` on the failed job so the bell hides its retry button instead of letting users spam jobs that can't ever succeed.
- **main.py** — App factory + lifespan (seeders → embedding backfill → merge-candidate backfill → `JobDAO.reap_orphans` flips any `running` jobs to `failed` so a mid-job restart doesn't leave them stuck → `job_worker.register_dispatcher(JobKind.user_scrape, scrape_dispatcher)` then `job_worker.start()`; on shutdown, `job_worker.stop()`). Also exposes `GET /` and `GET /health` directly (health returns `{status, version, db}` and pings the DB with a short 2s `asyncio.wait_for` so transient DB unavailability produces a fast 503 instead of riding asyncpg's 60s connect timeout into a Coolify liveness flap). Registers a `maintenance_gate` HTTP middleware that short-circuits every request not in the allowlist (`/`, `/health`, `/maintenance/status`) to 503 `{maintenance: true}` while `core/maintenance.py`'s flag is set (flipped on by restore, or by the worker for the duration of an `update_sweep` / `seasonal_sweep` job).

### Frontend (phsar/frontend/)

SvelteKit with file-based routing, Svelte 5 runes, Tailwind CSS 4, shadcn-svelte component library.

- **routes/** — Pages: home (`/`), login (`/login`), register (`/register`), search (`/search`), media detail (`/media`), anime detail (`/anime`), settings (`/settings`), admin (`/admin`), add to library (`/library/add`). Plus a `GET /health` endpoint returning `{status, version}` for Coolify liveness — deliberately does not probe the backend (liveness should only check what restarting this container can fix). `/library/add` is a query-input + recent-additions panel; submitting POSTs to `/jobs/scrape` and the navbar bell takes over from there. Restricted users see the page but the form is disabled.
- **lib/components/** — App components (SearchBar, MediaInfo, NavBar, JobBell, TagSelect, DoubleRangeSlider, RatingCard, BulkRateDialog, DangerZone, BackupsCard, MergeCandidatesCard, MaintenanceBanner, RelatedMediaCarousel, SpoilerGuard, EChart, RatingsOverview with sub-components for Stats/Timeline/Notes/Attributes, AttributeRadar, AttributeBadges, AttributeDetailBars, VersionFooter, LoadingScreen (themed sakura-ring loader shown during initial boot + ~1.5s logout transition), etc.) using Svelte 5 `$props()`, `$state()`, `$derived()`, `$effect()`. `VersionFooter` renders at the bottom of every page and reads `PUBLIC_APP_VERSION` from `$env/dynamic/public`. `BackupsCard` is the admin-only dump list (create/upload/download/restore/delete with a "Current" badge on the row the DB was last restored from). `MergeCandidatesCard` is the admin-only review surface for pending merge candidates: side-by-side anime info (with rating count + earliest aired date as visible justification for the recommended A), similarity score, merge/dismiss with confirm-step, and a per-row "Swap A/B" button that flips the merge direction. Refreshes are silent — the keyed each-block diffs in place instead of collapsing to "Loading…", so the list never jumps; merges trigger an automatic refetch that surfaces both cascade-resolved pairs and freshly-detected ones from the survivor. `MaintenanceBanner` is a global yellow banner mounted above the navbar in `+layout.svelte` that polls `GET /maintenance/status` every 60s via raw `fetch` (deliberately bypassing `api.ts` so a 503 mid-window doesn't trigger the maintenance redirect and defeat the pre-warning point); renders a countdown when a sweep is scheduled within 30 min, an "in progress" message while one is running, otherwise nothing. `JobBell` polls `/jobs/mine`, caps the dropdown at 5 entries (older entries spill to `/library/add`), hides the retry button when `result_summary.retryable === false`, and disables it across all rows while a retry is in flight.
- **lib/components/ui/** — shadcn-svelte base components (button, card, input, badge, slider, dropdown-menu, popover, checkbox, label, select, separator, etc.).
- **lib/api.ts** — Centralized API client with `get`/`post`/`postForm`/`put`/`del`/`downloadBlob`/`postMultipart` methods, `ApiError` class, automatic auth header injection from the token store, and a maintenance-503 handler that clears the token and hard-navigates to `/login?maintenance=1` when the backend returns `{maintenance: true}`.
- **lib/types/api.ts** — TypeScript interfaces mirroring backend Pydantic schemas (`MediaConnected`, `FilterOptions`, `TokenResponse`, etc.).
- **lib/stores/** — Svelte stores for auth state (JWT token persisted to localStorage), user settings, spoiler visibility (precomputed visible media UUIDs from backend), bell session-scoped state, and cross-component bumps. `jobs.ts` exports two writable bumps + an `onBump(store, fn)` subscribe-and-skip-the-initial-fire helper: `jobsRefresh` (bumped by `/library/add` after a successful POST so the bell refetches in tens of ms instead of waiting for the 30s idle poll) and `librarySaved` (bumped by the bell when it observes a new `succeeded` user_scrape — UUID-tracked via `announcedSavedUuids` so it fires exactly once per job — so `/library/add` refreshes its recent-additions panel without a manual reload). `bell-session.ts` exports `BELL_LOGIN_KEY` / `BELL_SEEN_KEY` + a `clearBellSession()` helper; `auth.ts` calls it whenever the token transitions to null so a logout-and-back-in cycle in the same tab doesn't inherit the previous session's "seen" set or session-start timestamp (sessionStorage otherwise survives hard navs).
- **lib/utils/** — String formatting (`formatAiringStatus`, `formatRelationType`, `formatMediaType`, `formatSeasonRange`, `formatDuration`, `formatDecimalDigits`, `formatShortDate`, `formatShortDateTime`, `formatBytes`), season logic, search params (`fetchSearchResults`, `fetchAnimeSearchResults`), navigation (`navigateToSearch`, `buildDetailHref`), chart colors (`CHART_COLORS`, `scoreColor`, `getThemedChartColorPalette`, `RELATION_TYPE_ORDER`, `RELATION_TYPE_COLORS`, `RELATION_TYPE_LABELS`), spoiler frontier computation (`spoilerFrontier.ts` — client-side frontier for detail pages).
- **lib/themes.ts** — Centralized theme config (`THEMES` record mapping keys to CSS classes, character pics, labels; `ThemeKey` type; helpers: `isValidTheme`, `getThemeCssClass`, `getThemePic`, `getThemeFocal`, `getActiveTheme`).
- **lib/echarts.ts** — Lazy-loaded ECharts singleton (`getEcharts()`) using pre-built ESM bundle (SSR-safe, cached).
- **lib/config.ts** — Backend API base URL (consumed only by `api.ts`).
- **src/app.css** — Theme system: `@property` definitions for `--primary`/`--ring`, `@theme inline` with `var()` indirection, `.theme-red`/`.theme-blue`/`.theme-green` override classes, themeable gradient variables (body dark gradient `--gradient-*` + auth-page light gradient `--auth-gradient-*` used on login/register). Light elevated surfaces on dark gradient background. Dark mode locked to class-based only.
- **tests/** — Vitest + @testing-library/svelte component tests.

### Key Patterns

- **Dependency injection**: FastAPI `Depends()` for DB sessions, current user extraction, role-based access (`require_roles()` accepts `RoleType` enum).
- **Role-based access**: Three roles — `admin`, `user`, `restricted_user`.
- **Async throughout**: asyncpg driver, SQLAlchemy AsyncSession, async service/DAO methods. All ORM relationships use `lazy="raise"` to prevent implicit lazy loading — every relationship access must go through explicit `selectinload` in the DAO query.
- **Vector search**: `paraphrase-multilingual-MiniLM-L12-v2` model generates embeddings stored via pgvector; similarity search on title, description, and rating note vectors. `SearchType` enum (`title`, `description`, `rating_notes`) selects the target. Search filter schemas use inheritance: `MediaSearchFilters` (base) → `RatingSearchFilters` (adds rating-specific filters). Anime-level title search uses `AnimeSearch` embeddings directly; description search averages cosine distances across media. `ViewType` enum (`anime`, `media`) selects the search mode. `/filters/options?view_type=anime` returns anime-appropriate filter ranges (aggregated episodes/watch time, majority genres).
- **Domain exceptions**: All custom exceptions extend `PhsarBaseError` with a `status_code` class attribute. One handler in `main.py` serves all.
- **Theme system**: CSS custom properties with `@property` indirection — `@property --primary` / `--ring` hold the source values, `@theme inline` references them via `var()`, and `.theme-*` classes on `<html>` override them. This forces Tailwind to emit `var()` in utilities instead of inlining static values. Components use semantic tokens (`bg-primary`, `text-primary`, `ring-ring`). Centralized theme config in `lib/themes.ts` maps theme keys to CSS classes, character pics, and labels. FOUC prevention via inline localStorage script in `app.html`. Per-theme chart color palettes in `chartColors.ts` avoid hue clashes.
- **Spoiler protection**: Three levels (`off`/`blur`/`hide`) controlled by `SpoilerLevel` user setting. Uses a "frontier" algorithm: per anime, all media up to and including the next unwatched main-story entry are visible. Precomputed in `user_visible_media` table (updated per-anime on rating changes, per-user on registration, and per-user after new scrapes land via `save_service`). Backend `GET /ratings/spoiler-visibility` returns visible UUIDs; frontend stores as `Set` in `spoilerVisibility` store. `SpoilerGuard.svelte` wraps covers/descriptions with blur + click-to-reveal. Detail pages compute frontier locally for fresher data. `hide` mode in media search uses `WHERE media.id IN (...)` from the cache. Anime covers/descriptions are never spoiler-protected.
- **Background jobs**: A single asyncio FIFO worker (`job_worker.py`) drains the `jobs` table. Per-user cap (`JOBS_PER_USER_LIMIT=4`) prevents one user from monopolizing the queue; system jobs (sweeps, seasonal) submit with `requested_by_user_id=null` to skip the cap. Each handler accepts a `ProgressReporter` so `JobBell` sees mid-flight stage/items updates before the whole job tx commits (short-lived autocommit txes throttled to 0.5s). `PermanentPhsarError` marker class gates retry: deterministic failures (`AnimeNotFoundError`, `MainMediaNotFoundError`, `MalIdAlreadyExistsError`) stamp `result_summary.retryable = False` and the bell hides the retry button. Per-query dedupe lives at submission time: re-running the same normalized query within `JOBS_DEDUPE_HOURS` returns 409 (failed jobs don't count, so a transient MAL outage doesn't lock a user out). Crash recovery: `JobDAO.reap_orphans` runs on lifespan startup and marks any `running` rows as `failed` (mirrors `embedding_backfiller`'s idempotency pattern).
- **Maintenance mode**: Destructive operations flip `core/maintenance.py`'s in-memory `_active` flag — currently backup restore (synchronous, request-scoped) and nightly `update_sweep`/`seasonal_sweep` jobs (the worker brackets each sweep dispatch in a try/finally so a crash can't leave the flag stuck). An HTTP middleware in `main.py` returns 503 `{maintenance: true}` for every non-allowlisted request while `_active` is set; the allowlist is `/`, `/health`, `/maintenance/status`. The frontend's `api.ts` detects 503-with-maintenance, clears the auth token, and hard-navigates to `/login?maintenance=1`. Pre-warning protocol: the schedule-sweep cron endpoint (lands in 7b) sets `_scheduled_at` to a future timestamp when it enqueues a delayed sweep (e.g. 20 min ahead); `MaintenanceBanner` polls `GET /maintenance/status` every 60s and renders a yellow countdown when the schedule is within 30 min so users can save work before the window opens. Both `_active` and `_scheduled_at` are process-wide module globals — single-worker assumption, documented upgrade path is a file sentinel or DB row.
- **CORS**: Backend allows origins from `settings.CORS_ORIGINS` (defaults to `http://localhost:5173`) and exposes `Content-Disposition` so the frontend can read server-authored download filenames.

## Working With Me

- Always ask before making changes to the repo such as creating issues, milestones, releases, commits, or pushing code.
- When planning work, discuss the plan with me before executing — don't assume priorities or release groupings.

## Configuration

The backend requires a `phsar/.env` file with: `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`, `SEARCH_SECRET_KEY`.

Optional: `DEBUG` (enables SQL echo), `CORS_ORIGINS` (JSON list of allowed origins), `GUEST_USERNAME` + `GUEST_PASSWORD` (seeds a read-only guest account with `restricted_user` role), `APP_VERSION` (deployed version tag surfaced on `/health`; injected via the backend Dockerfile build arg), `BACKUP_DIR` (where dumps are written; defaults to `./backups` so native `uvicorn` dev works without root, and the Dockerfile sets it to `/backups` so the container writes to the bind-mounted volume), `BACKUP_CRON_TOKEN` (shared bearer secret for `POST /admin/backups/auto`; empty = scheduled backups disabled and the endpoint fails closed), `BACKUP_RESTORE_TIMEOUT_SECONDS` (default 600 — raise if the DB grows large enough that pg_restore legitimately takes >10 min; a mid-restore kill leaves the DB half-dropped), `JOBS_CRON_TOKEN` (shared bearer secret for the scheduled-sweep cron endpoints; empty = sweep endpoints disabled and fail closed), `JOBS_PER_USER_LIMIT` (default 4 — max queued+running user_scrape jobs per non-system user; the 5th submission returns 409), `JOBS_DEDUPE_HOURS` (default 72 — re-running the same scrape query within this window returns 409 unless the prior job failed), `JOBS_SWEEP_MAX_PER_RUN` (default 200 — bounds nightly `update_sweep` batch size).

Frontend (runtime, read from `$env/dynamic/public`): `PUBLIC_API_BASE_URL` (backend URL; defaults to `http://localhost:8000` for local dev) and `PUBLIC_APP_VERSION` (shown in the footer). Both are set as container ENV in production — changing them does not require an image rebuild.

## Deployment

Self-hosted on a Coolify-managed VM. Images are built in GitHub Actions and pulled by Coolify — the VM is too small (2 vCPU / 4 GB) to survive a SvelteKit build.

Three services:

- `phsar/Dockerfile` — multi-stage backend. CPU-only torch from the pytorch CPU index; sentence-transformers model baked into `/opt/st-cache`. Runs as non-root `phsar` user (UID 1000). `/backups` is created at build time and chowned to `phsar:phsar` so a bind-mounted host dir matches. Entrypoint (`phsar/docker/entrypoint.sh`) applies Alembic migrations before exec'ing uvicorn.
- `phsar/frontend/Dockerfile` — bun build → `node:22-slim` runtime via SvelteKit `adapter-node`. Reuses the built-in `node` user.
- `docker-compose.yml` (repo root) — runs all three containers together; only for local parity smoke-testing, not day-to-day dev.

Deployment flow: tag any commit with `v*` (stable `v0.13.0` or preview `v0.13.0-rc1`) and push. The `build-images.yml` workflow builds both images in parallel and pushes to `ghcr.io/priapos1004/phsar-{backend,frontend}:<tag>`. In Coolify, point each service at the new image tag and redeploy.

### Backups

- Coolify mounts `/opt/phsar/backups` on the VM to `/backups` in the backend container. The host directory must be owned by UID 1000 (`chown 1000:1000 /opt/phsar/backups`) so the `phsar` user can write dumps.
- Manual backups: admin panel → Backups card → "Create backup". Download/delete/upload/restore from the same UI.
- Scheduled backups: set `BACKUP_CRON_TOKEN` in Coolify backend env, then add a Coolify scheduled task that `curl -fsS -X POST -H "Authorization: Bearer $BACKUP_CRON_TOKEN" http://localhost:8000/admin/backups/auto` (task runs inside the backend container, which ships with curl, so loopback avoids TLS/DNS). The endpoint creates a dump tagged `cron` and applies retention (14 daily + 8 Sunday; never evicts the most recent known-good dump).
- Off-host safety net: `scripts/pull-backups.sh user@vm` rsyncs `/opt/phsar/backups/` to the local machine. Run every ~2 months and before any restore.
- Restore workflow: UI prompts for the admin's username as the confirmation string; an automatic pre-restore snapshot is taken first, then `pg_restore --clean --if-exists --no-owner --no-privileges` runs against the target DB.

## CI

GitHub Actions:
- **Backend Lint** (`backend-lint.yml`): `ruff check .` in `phsar/` — runs on every push/PR.
- **Backend Tests** (`backend-test.yml`): `pytest` against a pgvector service container — runs on every push/PR.
- **Frontend Check** (`frontend-check.yml`): `bun run check` + `bun run test` — runs on every push/PR.
- **Build & Push Images** (`build-images.yml`): builds backend + frontend images and pushes to ghcr.io — runs on tag push (`v*`) or manual dispatch.

## Linting Config (pyproject.toml)

Ruff excludes `alembic/versions` and `__init__.py` files. Import sorting is enabled (`extend-select = ["I"]`).

## Test Config

### Backend (pytest.ini)
- `asyncio_mode = auto` — no need for `@pytest.mark.asyncio` decorators.
- Tests use the real database (not mocks); all changes are rolled back after each test.

### Frontend (vite.config.ts)
- Vitest with jsdom environment and `@testing-library/svelte`.
- `resolve.conditions: ['browser']` for Svelte 5 compatibility.
- Tests mock SvelteKit modules (`$app/navigation`, `$app/environment`, `$app/state`) in `src/tests/setup.ts`.

## License

PolyForm Noncommercial 1.0.0 — free for personal, educational, and non-commercial use.
