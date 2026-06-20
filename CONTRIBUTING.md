# Contributing to Phsar

Thank you for your interest in contributing to Phsar! This project is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE) — contributions are welcome for non-commercial purposes.

## Getting Started

1. **Fork** the repository
2. **Clone** your fork and create a new branch from `main`
3. **Set up** the development environment (see [README](README.md) + [phsar/README.md](phsar/README.md) for the full walkthrough):
   - Backend: create the conda env (`conda create -yn phsar python=3.12 && conda activate phsar`), then `cd phsar && pip install -r requirements.txt`
   - Frontend: `cd phsar/frontend && bun install`
   - Database: start a PostgreSQL container with pgvector (see [phsar/README.md](phsar/README.md)) — it must be running for the app and the backend tests
4. **Create a `.env` file** in `phsar/` (see README for required variables)
5. **Apply migrations**: `cd phsar && alembic upgrade head`

## Development Workflow

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Make your changes. If you change a SQLAlchemy model, generate a migration:
   `cd phsar && alembic revision --autogenerate -m "Describe change"` then `alembic upgrade head`
3. Run the checks before committing (the DB container must be running for `pytest`):
   - Backend: `cd phsar && ruff check . && pytest`
   - Frontend: `cd phsar/frontend && bun run check && bun run test`
4. Commit with clear, descriptive messages
5. Push and open a pull request against `main`

## Code Style

### Backend (Python)
- **Linter**: Ruff (config in `pyproject.toml`) — run `ruff check .` and `ruff check . --fix`
- **Architecture**: routers → services → DAOs → models (strict dependency flow)
- **Services**: Module-level async functions (not classes)
- **Exceptions**: Extend `PhsarBaseError` with a `status_code` class attribute
- **DAOs**: Extend `BaseDAO` and delegate to `get_by_field()` where possible
- **Role checks**: Use `RoleType` enum directly, not `.value` strings
- **Async gotchas** (these will bite you — see [CLAUDE.md](CLAUDE.md) for the full rationale):
  - All ORM relationships use `lazy="raise"` — load related rows explicitly with `selectinload` in the DAO query; an implicit lazy access raises
  - Never `asyncio.gather` coroutines that share one `AsyncSession`. It corrupts in-flight query state. Run session work sequentially

### Frontend (TypeScript/Svelte)
- **Framework**: SvelteKit with Svelte 5 runes (`$props()`, `$state()`, `$derived()`, `$effect()`)
- **Components**: Use shadcn-svelte for UI primitives
- **Styling**: Theme tokens (`bg-card`, `text-primary`, etc.) instead of hardcoded Tailwind colors
- **API calls**: Use the centralized `api` client from `$lib/api.ts`
- **Types**: Define API response types in `$lib/types/api.ts`

## Architecture reference & tooling

- The nested **`CLAUDE.md`** files are the source of truth for architecture and conventions: [CLAUDE.md](CLAUDE.md) (root), [phsar/app/services/CLAUDE.md](phsar/app/services/CLAUDE.md), [phsar/frontend/CLAUDE.md](phsar/frontend/CLAUDE.md), and [phsar/scripts/CLAUDE.md](phsar/scripts/CLAUDE.md). Read the relevant one before working in that subtree. [phsar/frontend/USER_FLOWS.md](phsar/frontend/USER_FLOWS.md) specifies user-facing behavior.
- This repo is set up for **Claude Code** with project skills (`/update-docs`, `/simplify`, and others). If you use it, the conventional loop is implement → `/update-docs` → `/simplify` → lint/tests → commit. These are optional helpers — the plain commands above are all a contribution needs.

## Pull Request Guidelines

- Keep PRs focused — one feature or fix per PR
- Ensure all CI checks pass (backend lint + tests, frontend `bun run check` + tests, build)
- Update documentation when your change affects architecture, file structure, or user flows: the relevant `CLAUDE.md`, the folder tree in [phsar/README.md](phsar/README.md), and [USER_FLOWS.md](phsar/frontend/USER_FLOWS.md)

## Reporting Issues

Use [GitHub Issues](https://github.com/Priapos1004/phsar/issues) to report bugs or suggest features. Please include:
- Steps to reproduce (for bugs)
- Expected vs actual behavior
- Screenshots if relevant
