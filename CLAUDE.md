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
cd phsar/frontend/phsar-frontend
npm install
npm run dev -- --open   # dev server at localhost:5173
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

## Architecture

### Backend (phsar/app/)

Layered architecture with strict dependency flow: **routers → services → DAOs → models**

- **routers/** — FastAPI endpoint definitions. Each router maps to an API prefix (`/auth`, `/search`, `/filters`, `/save`, `/seed`).
- **services/** — Business logic. Key services: `jikan_scraper.py` (MAL API client with retry), `vector_embedding_service.py` (sentence-transformers embeddings), `media_search_service.py` (filtered DB search), `token_service.py` (compressed JWT for shareable filter URLs).
- **daos/** — Data access layer. `BaseDAO` provides generic async CRUD; specialized DAOs (media, anime, genre, studio) add complex queries with vector similarity, filtering, and aggregation.
- **models/** — SQLAlchemy ORM models mapped to PostgreSQL tables. `media_search.py` stores pgvector embeddings for title and description.
- **schemas/** — Pydantic request/response DTOs.
- **core/** — Config (`config.py` loads from `.env`), database engine (`db.py`), auth dependencies (`dependencies.py`), JWT/password security (`security.py`).
- **seeders/** — Run at app startup via lifespan; seed genres and admin user.
- **exceptions.py** — Custom exception hierarchy rooted at `PhsarBaseError`, mapped to HTTP status codes in `main.py`.

### Frontend (phsar/frontend/phsar-frontend/)

SvelteKit with file-based routing, Svelte 5, Tailwind CSS 4.

- **routes/** — Pages: home (`/`), login (`/login`), search (`/search`).
- **lib/components/** — Reusable components (SearchBar, MediaInfo, DoubleRangeSlider, TagSelect, etc.).
- **lib/stores/** — Svelte stores for auth state (JWT token).
- **lib/utils/** — API call helpers, string formatting, season logic, navigation.
- **lib/config.ts** — Backend API base URL.

### Key Patterns

- **Dependency injection**: FastAPI `Depends()` for DB sessions, current user extraction, role-based access (`require_roles()`).
- **Role-based access**: Three roles — `admin`, `user`, `restricted_user`.
- **Async throughout**: asyncpg driver, SQLAlchemy AsyncSession, async service/DAO methods.
- **Vector search**: `paraphrase-multilingual-MiniLM-L12-v2` model generates embeddings stored via pgvector; similarity search on title and description vectors.
- **CORS**: Backend only allows `http://localhost:5173`.

## Working With Me

- Always ask before making changes to the repo such as creating issues, milestones, releases, commits, or pushing code.
- When planning work, discuss the plan with me before executing — don't assume priorities or release groupings.

## Configuration

The backend requires a `phsar/.env` file with: `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`, `SEARCH_SECRET_KEY`.

## CI

GitHub Actions runs `ruff check .` in `phsar/` on every push and PR.

## Linting Config (pyproject.toml)

Ruff excludes `alembic/versions` and `__init__.py` files. Import sorting is enabled (`extend-select = ["I"]`).

## Test Config (pytest.ini)

- `asyncio_mode = auto` — no need for `@pytest.mark.asyncio` decorators.
- Tests use the real database (not mocks); all changes are rolled back after each test.
