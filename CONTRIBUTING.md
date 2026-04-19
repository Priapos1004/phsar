# Contributing to Phsar

Thank you for your interest in contributing to Phsar! This project is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE) — contributions are welcome for non-commercial purposes.

## Getting Started

1. **Fork** the repository
2. **Clone** your fork and create a new branch from `main`
3. **Set up** the development environment:
   - Backend: `cd phsar && pip install -r requirements.txt`
   - Frontend: `cd phsar/frontend && bun install`
   - Database: Start a PostgreSQL container with pgvector (see [README](phsar/README.md))
4. **Create a `.env` file** in `phsar/` (see README for required variables)

## Development Workflow

1. Create a feature branch: `git checkout -b feature/your-feature`
2. Make your changes
3. Run tests before committing:
   - Backend: `cd phsar && ruff check . && pytest`
   - Frontend: `cd phsar/frontend && bun run test`
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

### Frontend (TypeScript/Svelte)
- **Framework**: SvelteKit with Svelte 5 runes (`$props()`, `$state()`, `$derived()`, `$effect()`)
- **Components**: Use shadcn-svelte for UI primitives
- **Styling**: Theme tokens (`bg-card`, `text-primary`, etc.) instead of hardcoded Tailwind colors
- **API calls**: Use the centralized `api` client from `$lib/api.ts`
- **Types**: Define API response types in `$lib/types/api.ts`

## Pull Request Guidelines

- Keep PRs focused — one feature or fix per PR
- Ensure all tests pass (CI runs automatically)
- Update documentation if your change affects architecture, file structure, or user flows

## Reporting Issues

Use [GitHub Issues](https://github.com/Priapos1004/phsar/issues) to report bugs or suggest features. Please include:
- Steps to reproduce (for bugs)
- Expected vs actual behavior
- Screenshots if relevant
