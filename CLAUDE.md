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

- **routers/** — FastAPI endpoint definitions. Each router maps to an API prefix (`/admin`, `/auth`, `/search`, `/filters`, `/media`, `/save`, `/seed`, `/ratings`, `/users`). `/admin` handles registration token management (list, create, delete — admin-only) and database backups (list, create, download, delete, restore, upload — admin-only; plus `/admin/backups/auto` for scheduled dumps, authenticated via a cron bearer token). `/search` handles both `/search/media` (per-media) and `/search/anime` (aggregated by anime). `/media` handles both `/media/{uuid}` and `/media/anime/{uuid}`. `/users` handles settings CRUD, data export, and account deletion.
- **services/** — Business logic as module-level async functions. Key services: `jikan_scraper.py` (MAL API client with retry), `vector_embedding_service.py` (sentence-transformers embeddings), `media_search_service.py` (filtered DB search), `anime_search_service.py` (anime aggregated search + detail with majority genre logic), `rating_service.py` (rating CRUD + search, triggers spoiler visibility recompute on changes), `token_service.py` (compressed JWT for shareable filter URLs), `auth_service.py` (registration, authentication, token issuance, account deletion), `filter_service.py` (filter option values, view-type-aware for anime vs media ranges), `user_settings_service.py` (user settings CRUD + default creation), `spoiler_service.py` (spoiler frontier algorithm + precomputed visibility cache in `user_visible_media` table; recomputed per-anime on rating changes, per-user on registration), `export_service.py` (flat media-level data export merging catalog info, ratings, and watchlist per media; respects user's name_language setting for localized title columns), `admin_service.py` (registration token list + delete), `backup_service.py` (pg_dump/pg_restore wrappers via `asyncio.create_subprocess_exec`; atomic `.partial` writes, sidecar `.meta.json` per dump, integrity check via `pg_restore --list`, retention of 14 daily + 8 Sunday dumps, disk-space guard, pre-restore auto-snapshot; password passed to subprocess via `PGPASSWORD`, never on the CLI).
- **daos/** — Data access layer. `BaseDAO` provides generic async CRUD; specialized DAOs (media, anime, genre, studio, user, user_settings, registration_token, rating) add domain-specific queries with vector similarity, filtering, and aggregation. `AnimeDAO.search_anime_aggregated` uses two-phase query: SQL GROUP BY with HAVING for filtering/ordering, then detail fetch. `search_filters.py` provides shared filter/ordering helpers for media, anime pre-aggregation (WHERE), and anime post-aggregation (HAVING) filters.
- **models/** — SQLAlchemy ORM models mapped to PostgreSQL tables. `media_search.py` stores pgvector embeddings for title and description; `anime_search.py` stores anime-level embeddings; `rating_search.py` stores note embeddings for rating note search. `user_settings.py` stores per-user preferences (one-to-one with Users) with enums for theme, name language, search view, rating step, and spoiler level. `user_visible_media.py` is a precomputed cache of which media are visible (not spoiler-protected) per user, updated on rating changes.
- **schemas/** — Pydantic request/response DTOs.
- **core/** — Config (`config.py` loads from `.env`), database engine (`db.py`), auth dependencies (`dependencies.py`), JWT/password security (`security.py`).
- **seeders/** — Run at app startup via lifespan; seed genres, admin user, and optional guest user (restricted_user role). `backfill_user_settings` ensures all users have a UserSettings row. `backfill_spoiler_visibility` computes visible media for users with no cache rows. `embedding_backfiller.py` detects and regenerates any missing anime, media, or rating embeddings (enables seamless embedding model swaps via Alembic migration + restart).
- **exceptions.py** — Custom exception hierarchy rooted at `PhsarBaseError` with `status_code` attribute. Single exception handler in `main.py` reads the status code from each exception class.
- **main.py** — App factory + lifespan; also exposes `GET /` and `GET /health` directly (health returns `{status, version, db}` and pings the DB via the shared session dependency).

### Frontend (phsar/frontend/)

SvelteKit with file-based routing, Svelte 5 runes, Tailwind CSS 4, shadcn-svelte component library.

- **routes/** — Pages: home (`/`), login (`/login`), register (`/register`), search (`/search`), media detail (`/media`), anime detail (`/anime`), settings (`/settings`), admin (`/admin`).
- **lib/components/** — App components (SearchBar, MediaInfo, NavBar, TagSelect, DoubleRangeSlider, RatingCard, BulkRateDialog, DangerZone, RelatedMediaCarousel, SpoilerGuard, EChart, RatingsOverview with sub-components for Stats/Timeline/Notes/Attributes, AttributeRadar, AttributeBadges, AttributeDetailBars, VersionFooter, etc.) using Svelte 5 `$props()`, `$state()`, `$derived()`, `$effect()`. `VersionFooter` renders at the bottom of every page and reads `PUBLIC_APP_VERSION` from `$env/dynamic/public`.
- **lib/components/ui/** — shadcn-svelte base components (button, card, input, badge, slider, dropdown-menu, popover, checkbox, label, select, separator, etc.).
- **lib/api.ts** — Centralized API client with `get`/`post`/`postForm`/`put`/`del` methods, `ApiError` class, and automatic auth header injection from the token store.
- **lib/types/api.ts** — TypeScript interfaces mirroring backend Pydantic schemas (`MediaConnected`, `FilterOptions`, `TokenResponse`, etc.).
- **lib/stores/** — Svelte stores for auth state (JWT token persisted to localStorage), user settings, and spoiler visibility (precomputed visible media UUIDs from backend).
- **lib/utils/** — String formatting (`formatAiringStatus`, `formatRelationType`, `formatMediaType`, `formatSeasonRange`, `formatDuration`, `formatDecimalDigits`), season logic, search params (`fetchSearchResults`, `fetchAnimeSearchResults`), navigation (`navigateToSearch`, `buildDetailHref`), chart colors (`CHART_COLORS`, `scoreColor`, `getThemedChartColorPalette`, `RELATION_TYPE_ORDER`, `RELATION_TYPE_COLORS`, `RELATION_TYPE_LABELS`), spoiler frontier computation (`spoilerFrontier.ts` — client-side frontier for detail pages).
- **lib/themes.ts** — Centralized theme config (`THEMES` record mapping keys to CSS classes, character pics, labels; `ThemeKey` type; helpers: `isValidTheme`, `getThemeCssClass`, `getThemePic`, `getThemeFocal`, `getActiveTheme`).
- **lib/echarts.ts** — Lazy-loaded ECharts singleton (`getEcharts()`) using pre-built ESM bundle (SSR-safe, cached).
- **lib/config.ts** — Backend API base URL (consumed only by `api.ts`).
- **src/app.css** — Theme system: `@property` definitions for `--primary`/`--ring`, `@theme inline` with `var()` indirection, `.theme-red`/`.theme-blue`/`.theme-green` override classes, themeable gradient variables. Light elevated surfaces on dark gradient background. Dark mode locked to class-based only.
- **tests/** — Vitest + @testing-library/svelte component tests.

### Key Patterns

- **Dependency injection**: FastAPI `Depends()` for DB sessions, current user extraction, role-based access (`require_roles()` accepts `RoleType` enum).
- **Role-based access**: Three roles — `admin`, `user`, `restricted_user`.
- **Async throughout**: asyncpg driver, SQLAlchemy AsyncSession, async service/DAO methods. All ORM relationships use `lazy="raise"` to prevent implicit lazy loading — every relationship access must go through explicit `selectinload` in the DAO query.
- **Vector search**: `paraphrase-multilingual-MiniLM-L12-v2` model generates embeddings stored via pgvector; similarity search on title, description, and rating note vectors. `SearchType` enum (`title`, `description`, `rating_notes`) selects the target. Search filter schemas use inheritance: `MediaSearchFilters` (base) → `RatingSearchFilters` (adds rating-specific filters). Anime-level title search uses `AnimeSearch` embeddings directly; description search averages cosine distances across media. `ViewType` enum (`anime`, `media`) selects the search mode. `/filters/options?view_type=anime` returns anime-appropriate filter ranges (aggregated episodes/watch time, majority genres).
- **Domain exceptions**: All custom exceptions extend `PhsarBaseError` with a `status_code` class attribute. One handler in `main.py` serves all.
- **Theme system**: CSS custom properties with `@property` indirection — `@property --primary` / `--ring` hold the source values, `@theme inline` references them via `var()`, and `.theme-*` classes on `<html>` override them. This forces Tailwind to emit `var()` in utilities instead of inlining static values. Components use semantic tokens (`bg-primary`, `text-primary`, `ring-ring`). Centralized theme config in `lib/themes.ts` maps theme keys to CSS classes, character pics, and labels. FOUC prevention via inline localStorage script in `app.html`. Per-theme chart color palettes in `chartColors.ts` avoid hue clashes.
- **Spoiler protection**: Three levels (`off`/`blur`/`hide`) controlled by `SpoilerLevel` user setting. Uses a "frontier" algorithm: per anime, all media up to and including the next unwatched main-story entry are visible. Precomputed in `user_visible_media` table (updated per-anime on rating changes, per-user on registration). Backend `GET /ratings/spoiler-visibility` returns visible UUIDs; frontend stores as `Set` in `spoilerVisibility` store. `SpoilerGuard.svelte` wraps covers/descriptions with blur + click-to-reveal. Detail pages compute frontier locally for fresher data. `hide` mode in media search uses `WHERE media.id IN (...)` from the cache. Anime covers/descriptions are never spoiler-protected.
- **CORS**: Backend allows origins from `settings.CORS_ORIGINS` (defaults to `http://localhost:5173`).

## Working With Me

- Always ask before making changes to the repo such as creating issues, milestones, releases, commits, or pushing code.
- When planning work, discuss the plan with me before executing — don't assume priorities or release groupings.

## Configuration

The backend requires a `phsar/.env` file with: `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`, `SEARCH_SECRET_KEY`.

Optional: `DEBUG` (enables SQL echo), `CORS_ORIGINS` (JSON list of allowed origins), `GUEST_USERNAME` + `GUEST_PASSWORD` (seeds a read-only guest account with `restricted_user` role), `APP_VERSION` (deployed version tag surfaced on `/health`; injected via the backend Dockerfile build arg), `BACKUP_DIR` (where dumps are written; defaults to `./backups` so native `uvicorn` dev works without root, and the Dockerfile sets it to `/backups` so the container writes to the bind-mounted volume), `BACKUP_CRON_TOKEN` (shared bearer secret for `POST /admin/backups/auto`; empty = scheduled backups disabled and the endpoint fails closed).

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
- Scheduled backups: set `BACKUP_CRON_TOKEN` in Coolify backend env, then add a Coolify scheduled task that `curl -X POST -H "Authorization: Bearer $BACKUP_CRON_TOKEN" https://<backend-domain>/admin/backups/auto`. The endpoint creates a dump tagged `cron` and applies retention (14 daily + 8 Sunday; never evicts the most recent known-good dump).
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
