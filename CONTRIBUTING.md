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

Conventions live in [`.claude/rules/`](.claude/rules/) — one file per area, kept there so
there is a single copy to keep correct:

| Read before working on | File |
|---|---|
| Backend Python — layering, async/session gotchas, exceptions | [backend.md](.claude/rules/backend.md) |
| Models, DAOs, migrations — sidecars, index rules `alembic check` enforces | [database.md](.claude/rules/database.md) |
| Svelte/TypeScript — runes, theme tokens, shared components | [frontend.md](.claude/rules/frontend.md) |
| Docs — where a fact belongs, how to write it | [docs.md](.claude/rules/docs.md) |

Two async rules in `backend.md` will bite you specifically: every ORM relationship is
`lazy="raise"`, and `asyncio.gather` must never span coroutines sharing one `AsyncSession`.

**Linting**: Ruff, configured in `pyproject.toml` — `ruff check .` and `ruff check . --fix`.

## Architecture reference & tooling

- The nested **`CLAUDE.md`** files are the source of truth for architecture and conventions: [CLAUDE.md](CLAUDE.md) (root), [phsar/app/services/CLAUDE.md](phsar/app/services/CLAUDE.md), [phsar/frontend/CLAUDE.md](phsar/frontend/CLAUDE.md), and [phsar/scripts/CLAUDE.md](phsar/scripts/CLAUDE.md). Read the relevant one before working in that subtree. [phsar/frontend/USER_FLOWS.md](phsar/frontend/USER_FLOWS.md) specifies user-facing behavior.
- **[`.claude/rules/`](.claude/rules/)** holds the invariants worth knowing before you write code — the backend's async-session and `lazy="raise"` rules, the modelling and index rules that `alembic check` enforces, and the frontend's theme-token and shared-component conventions. Claude Code loads each one automatically when you touch matching files; they are plain markdown and worth reading directly otherwise.
- This repo is set up for **Claude Code** with project skills. If you use it, `/ship` runs the whole pre-commit loop (`/update-docs` → `/simplify` → lint) and a `PreToolUse` hook, [`.claude/hooks/pre-commit-gate.sh`](.claude/hooks/pre-commit-gate.sh), blocks `git commit` until it has — so the loop is enforced rather than remembered. Contributing **without** Claude Code is unaffected: the hook only sees Claude's own tool calls, and the plain commands above are all a contribution needs.

## Pull Request Guidelines

- Keep PRs focused — one feature or fix per PR
- Ensure all CI checks pass (backend lint + tests, frontend `bun run check` + tests, build)
- Update documentation when your change affects architecture, file structure, or user flows: the relevant `CLAUDE.md`, the folder tree in [phsar/README.md](phsar/README.md), and [USER_FLOWS.md](phsar/frontend/USER_FLOWS.md)

## Reporting Issues

Use [GitHub Issues](https://github.com/Priapos1004/phsar/issues) to report bugs or suggest features. Please include:
- Steps to reproduce (for bugs)
- Expected vs actual behavior
- Screenshots if relevant
