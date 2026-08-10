# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Phsar is a full-stack anime search and rating web application. It combines a FastAPI backend with a SvelteKit frontend, using PostgreSQL with pgvector for semantic vector search over anime data sourced from the official MyAnimeList API (v2).

## Where to find things

This file is the map: what exists, where it lives, how to run it. Depth lives in
four other places, each with one job.

**`.claude/rules/`** — invariants. Loaded automatically, only when relevant.

| Rule | Loads when |
|---|---|
| `workflow.md` — approval, commit blocks, `/ship`, authoring style | always |
| `docs.md` — where a fact belongs, how to write it | editing any `.md` |
| `backend.md` — layering, async session, exceptions | `phsar/{app,tests,scripts}/**/*.py` |
| `database.md` — models, sidecars, indexes, migrations | models / DAOs / alembic |
| `frontend.md` — runes, tokens, shared components, copy | `phsar/frontend/src/**` |
| `authoring-rules.md` — how to write a rule | editing `.claude/rules/**` |

**`docs/features/`** — how a subsystem works **today**, across the modules it spans.
These do **not** load automatically: **read the relevant one while planning** work
that touches its area, before settling on an approach.

| Doc | Covers |
|---|---|
| [scraping](docs/features/scraping.md) | MAL API v2 client, BFS, rate limiting, value translation, skip rules |
| [relations](docs/features/relations.md) | Two-pass classifier, substance gate, split detection, merge signals |
| [jobs](docs/features/jobs.md) | Worker, job kinds, due-tiers, `result_summary` versioning, the sweeps |
| [search](docs/features/search.md) | Embeddings, ranking, anime-view filters, main-story scoring |
| [backups](docs/features/backups.md) | Dump/restore, retention pools, the restorability verdict |
| [spoilers](docs/features/spoilers.md) | Frontier algorithm, visibility cache |

**`compound-docs/`** — why something changed. Dated and frozen; feature docs say how
it works now.

**Nested `CLAUDE.md`** — what is local to one subtree, loaded when working there:
[services](phsar/app/services/CLAUDE.md), [frontend](phsar/frontend/CLAUDE.md),
[scripts](phsar/scripts/CLAUDE.md). [USER_FLOWS.md](phsar/frontend/USER_FLOWS.md)
specifies user-facing behaviour.

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
  -p 5432:5432 -d pgvector/pgvector:pg17

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

### Backend (`phsar/app/`)

Layered, with dependency flowing one way: **routers → services → DAOs → models**.
The layering rules and their exceptions are in
[.claude/rules/backend.md](.claude/rules/backend.md).

**`routers/`** — grouped by API prefix (`/admin` spans five modules, mounted from
`admin.py`). The live contract is FastAPI's own
`/docs`; the frontend's consumer view is [USER_FLOWS.md](phsar/frontend/USER_FLOWS.md) §13.

| Prefix | Purpose |
|---|---|
| `/auth` | login, register, validate, refresh (sliding session) |
| `/search` | `/media` per-entry, `/anime` aggregated, `/ratings` note search, `/mal` |
| `/media` | media + anime detail |
| `/ratings` | rating CRUD, rewatch, scores projection, spoiler visibility |
| `/watchlist` | entries + lists (a "list" is a tag) |
| `/users` | settings, export, account deletion |
| `/jobs` | user-triggered scrapes, own-job polling |
| `/library`, `/filters` | recent additions; filter options + genres + the search-token pair |
| `/save`, `/seed` | internal save + seed entry points (not frontend-consumed) |
| `/maintenance` | public status for the pre-warning banner |
| `/admin*` | stats, jobs log, backups, registration tokens, merge/split/completion curation, cron schedulers |

**`services/`** — business logic as module-level async functions; long-lived
stateful components are classes. Per-service notes in
[services/CLAUDE.md](phsar/app/services/CLAUDE.md); subsystem behaviour in `docs/features/`.

**`daos/`** — all SQL. `BaseDAO` gives generic async CRUD; specialized DAOs own the
vector, aggregation and filtering queries. `search_filters.py` holds the shared
filter/order helpers and `media_projections.py` the shared wide-projection columns.
Query invariants are in [.claude/rules/database.md](.claude/rules/database.md).

**`models/`** — SQLAlchemy ORM. Alongside the canonical tables sit three deliberate
shapes, all covered by `rules/database.md`: **1:1 sidecars** for operational state
(`anime_freshness`, `media_freshness`, `media_relation_edges`, `anime_completion`),
**search tables** holding pgvector embeddings (`anime_search`, `media_search`,
`rating_search`), and **caches** (`user_visible_media`).

**`core/`** — cross-cutting infrastructure: `config.py` (env), `db.py` (engine),
`dependencies.py` (JWT user dep + `require_roles()` + the cron-bearer factory),
`security.py`, `job_versions.py` (the `result_summary` version registry),
`logging_config.py`, `maintenance.py` + `maintenance_middleware.py`.

**`exceptions.py`** — every error extends `PhsarBaseError` with a `status_code`, read
by the single handler in `main.py`. `PermanentPhsarError` marks a failure
non-retryable; `TransientUpstreamError` sits outside it and stays retryable.

**`seeders/`** — run from the lifespan: genres, admin + optional guest user, then
idempotent backfills (settings, default tags, embeddings, relations, merge and split
candidates, spoiler visibility). They re-run every boot and repair derived data.

### Frontend (`phsar/frontend/`)

SvelteKit with Svelte 5 runes, Tailwind CSS 4, shadcn-svelte. Conventions are in
[.claude/rules/frontend.md](.claude/rules/frontend.md); component, store and theme
detail in [frontend/CLAUDE.md](phsar/frontend/CLAUDE.md).

`lib/api.ts` is the single API client (it handles the maintenance 503),
`lib/stores/` holds auth/settings/spoiler/bell state, `lib/themes.ts` + `app.css`
the theme tokens.

### Maintenance mode

Destructive operations flip a process-wide flag and `MaintenanceGateMiddleware`
returns 503 `{maintenance: true}` for non-allowlisted requests. Two things about it
are easy to break:

- **Middleware order.** `app.add_middleware()` *prepends*, so the last registered is
  outermost. Register the maintenance gate first, then GZip, then CORS — so CORS
  wraps both and a 503 still carries `Access-Control-Allow-Origin`. Without it the
  browser blocks the response, `fetch()` throws, and the user sees a generic error
  instead of the maintenance banner. Pinned by `test_503_carries_cors_headers_for_cross_origin_requests`.
- **It is pure ASGI**, not `BaseHTTPMiddleware` — a short-circuit there doesn't
  compose with CORSMiddleware's send wrapper.

The flag and the scheduled-window pointer are module globals: single-worker
assumption, with a file sentinel or DB row as the documented upgrade path.

## Working With Me

The working contract — approval, commit blocks, the `/ship` pipeline, authoring
style — is in [.claude/rules/workflow.md](.claude/rules/workflow.md), loaded every
session. Two points govern the rest:

- **Ask before changing the repo**: commits, pushes, issues, milestones, releases.
- **Every commit goes through `/ship`**, enforced by `.claude/hooks/pre-commit-gate.sh`.

## Configuration

**Backend, required** — `phsar/.env` with: `DB_USER`, `DB_PASSWORD`, `DB_NAME`,
`ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`, `SEARCH_SECRET_KEY`,
`MY_ANIME_LIST_CLIENT_ID` (the scraper fails closed without it). `DB_HOST` and
`DB_PORT` default to `localhost:5432`.

**Backend, optional** — every tunable is documented with its rationale in
[phsar/.env.example](phsar/.env.example), which is the single list. Adding a setting
to `config.py` means adding it there.

**Frontend, runtime** — read from `$env/dynamic/public`, set as container ENV in
production so no image rebuild is needed: `PUBLIC_API_BASE_URL` (defaults to
`http://localhost:8000`), `PUBLIC_APP_VERSION` (shown in the footer).

## Deployment

Self-hosted on a Coolify-managed VM. Images are built in GitHub Actions and pulled by Coolify — the VM is too small (2 vCPU / 4 GB) to survive a SvelteKit build.

### Services

- **`phsar/Dockerfile`** — multi-stage backend. CPU-only torch from the pytorch CPU index; sentence-transformers model baked into `/opt/st-cache`; runs as non-root `phsar` (UID 1000); `/backups` created and chowned at build time so a bind-mounted host dir matches. `docker/entrypoint.sh` applies Alembic migrations before exec'ing uvicorn.
- **`phsar/frontend/Dockerfile`** — bun build → `node:22-slim` via SvelteKit `adapter-node`.
- **`docker-compose.yml`** (repo root) — all three containers; local parity smoke-testing only, not day-to-day dev.

### Deployment flow

Tag any commit with `v*` (stable `v0.13.0` or preview `v0.13.0-rc1`) and push. `build-images.yml` builds both images in parallel and pushes to `ghcr.io/priapos1004/phsar-{backend,frontend}:<tag>`. In Coolify, point each service at the new image tag and redeploy.

Move both images to the same tag whenever a release changes an API **response shape** rather than only adding to it. The frontend is typed against the backend's DTOs with no version negotiation between them, so a mixed pair breaks the affected page outright instead of degrading.

### Backups — operations

Behaviour (retention pools, the restorability verdict, restart-triggered dumps) is in
[docs/features/backups.md](docs/features/backups.md). What is operational:

- Coolify mounts `/opt/phsar/backups` on the VM to `/backups` in the container. The host directory must be owned by UID 1000 (`chown 1000:1000 /opt/phsar/backups`).
- Admin panel → Backups card covers create, download, delete, rename, restore, upload. Creating is async (202 + `job_uuid`, the bell tracks it); restore stays synchronous, prompts for the admin's username as confirmation, and takes an automatic pre-restore snapshot first.
- Off-host safety net: `scripts/pull-backups.sh user@vm` rsyncs `/opt/phsar/backups/` to a local machine. Run it every couple of months and before any restore.

### Scheduled jobs

Every cron-authed endpoint shares `JOBS_CRON_TOKEN` (Coolify backend env — empty disables all of them, fail closed). The sweep schedulers are allowlisted through the maintenance gate, so a cron retry mid-sweep authenticates instead of 503'ing; `/admin/backups/auto` is not, because a sweep-window 503 there is a benign no-op. `delay_minutes` is bound to `Query(20, ge=0, le=1440)`.

**Recommended Coolify setup — one daily task (~02:30 UTC):**

```
curl -fsS -X POST -H "Authorization: Bearer $JOBS_CRON_TOKEN" \
  "http://localhost:8000/admin/jobs/schedule-nightly?delay_minutes=20"
```

`schedule-nightly` enqueues a `backup` immediately (no delay — `pg_dump` is
MVCC-snapshot, so no banner is needed), an `update_sweep` at `now + delay_minutes`,
a `seasonal_sweep` at the same delay **on Sundays**, and an `upcoming_sweep` at the
same delay **on Wednesdays in the last month of the quarter** (Mar/Jun/Sep/Dec), so
next-quarter shows surface about a month early. The two season sweeps sit on
different weekdays so one nightly run never fires both.

The sweeps share `not_before_at`; the worker drains the backup first, then takes
whichever sweep is next by FIFO. Ordering between them is undefined and immaterial —
all run inside the maintenance window with a sub-second flag bounce.

Individual endpoints stay available for ad-hoc triggers: `POST /admin/backups/auto`,
and `POST /admin/jobs/schedule-{sweep,seasonal,upcoming}?delay_minutes=N`.

## CI

- **Backend Lint** (`backend-lint.yml`): `ruff check .` in `phsar/` — every push/PR
- **Backend Tests** (`backend-test.yml`): `pytest` against a pgvector service container — every push/PR. Also runs **`alembic check`**, which guards two things at once: that models and migrations agree (an index or column declared in only one is what makes the next `--autogenerate` propose a destructive diff), and that the chain still replays from empty. It needs its own throwaway `migrationcheck` DB brought up by `alembic upgrade head` — run against the test DB it would compare `create_all`'s metadata to a schema built from that same metadata, and pass however far the migrations had drifted
- **Frontend Check** (`frontend-check.yml`): `bun run check` + `bun run test` — every push/PR
- **Build & Push Images** (`build-images.yml`): builds + pushes to ghcr.io — tag push (`v*`) or manual dispatch

## Linting Config (pyproject.toml)

Ruff runs a curated ruleset, not the defaults: `select = ["E4","E7","E9","F","I","UP","B","SIM","C4","RUF","RET","ASYNC"]`, with `RUF001`–`RUF003` and `ASYNC240` ignored. `alembic/versions` and `__init__.py` are excluded.

## Test Config

- **Backend** (`pytest.ini`): `asyncio_mode = auto`, so no `@pytest.mark.asyncio` decorators. Tests run against the real database, not mocks; every change is rolled back after each test.
- **Frontend** (`vite.config.ts`): Vitest with jsdom and `@testing-library/svelte`; `resolve.conditions: ['browser']` for Svelte 5. SvelteKit modules (`$app/navigation`, `$app/environment`, `$app/state`) are mocked in `src/tests/setup.ts`.

## License

PolyForm Noncommercial 1.0.0 — free for personal, educational, and non-commercial use.
