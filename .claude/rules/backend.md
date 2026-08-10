---
description: Backend invariants — layering, async session rules, exceptions, and how to trigger operational jobs.
paths: "phsar/{app,tests,scripts}/**/*.py"
---

# Backend rules

## Layering

`routers → services → DAOs → models`. **Business logic** lives in services as
module-level async functions; long-lived stateful components are classes
(`MalScraper`, `JobWorker`, `ProgressReporter`). DAOs extend `BaseDAO` and
delegate to `get_by_field()` where it fits.

A thin read endpoint with no business logic may call a DAO directly rather than
grow a pass-through service — `routers/library.py` and `routers/jobs.py` do. Any
logic beyond fetch-and-return belongs in a service.

The reverse exception also exists: several services execute statements directly
rather than through a DAO — bulk cache rewrites, raw `text()` DDL, and one-off
aggregations for stats and export. It is a tolerated shape, not a pattern to copy
— new SQL goes in a DAO.

## Async — the two that bite

- **Never `asyncio.gather` coroutines that share one `AsyncSession`.** An
  AsyncSession cannot multiplex concurrent operations; `gather` corrupts
  in-flight query state, so session work runs sequentially. Pure-CPU coroutines
  that never touch the session (an embedding encode via `to_thread.run_sync`)
  are safe to gather. Canonical "don't" in `seasonal_sweep_dispatcher.py`;
  failure mode in `compound-docs/2026-05-09-v0.14.0-content-pipeline.md`.
- **Every relationship is `lazy="raise"`.** Load related rows explicitly with
  `selectinload` in the DAO query; an implicit lazy access raises rather than
  silently emitting a query.

## Exceptions

Extend `PhsarBaseError` with a `status_code` class attribute — one handler in
`main.py` reads it. `PermanentPhsarError` marks a failure non-retryable, which is
what stops the job bell offering retry on a deterministic failure.

## Roles

Three: `admin` (full access), `user` (read + write), `restricted_user` (a read-only
guest — browse and search, no writes).

**Every non-admin write endpoint gates on `require_user_or_admin`**, so a guest
gets 403. Admin endpoints gate on `require_roles(RoleType.Admin)` instead, bound
once at module load or as a router-level `dependencies=` — a `user` must never
reach an admin mutation.

Three writes are deliberately role-ungated. `/auth/register` and `/auth/login` are
public. `/auth/refresh` and `PUT /users/settings` take bare `get_current_user`, so
a guest keeps its sliding session and its own theme; the settings service drops
`spoiler_level` for a restricted user rather than the endpoint refusing the call.
Rating and watchlist *reads* are gated too, not just their writes: they are
per-user data a guest has none of, so an ungated read would return an empty page
that looks like a bug rather than a permission boundary.

Use the `RoleType` enum directly, never `.value` strings.

## Triggering operational jobs

Sweeps, backups and scrapes run through the **running backend API**, never a
script that imports and calls a dispatcher directly. A direct call skips the real
path — uvicorn/HTTP, the cron and admin endpoints, and the `job_worker` loop with
its maintenance-flag bracketing — so it validates something the deployed app
never does.

Boot `uvicorn app.main:app` from `phsar/` (conda env `phsar`) and wait for
`/health`. The cron-authed schedulers take `Authorization: Bearer $JOBS_CRON_TOKEN`;
polling `GET /admin/jobs/{uuid}` is on the **JWT admin** chain instead, so reuse
of the cron bearer there returns 401.
