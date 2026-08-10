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

## Async — the two that bite

- **Never `asyncio.gather` coroutines that share one `AsyncSession`.** An
  AsyncSession cannot multiplex concurrent operations; `gather` corrupts
  in-flight query state, so session work runs sequentially. Pure-CPU coroutines
  that never touch the session (an embedding encode via `to_thread.run_sync`)
  are safe to gather. Canonical "don't" at `seasonal_sweep_dispatcher.py:48-51`;
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

**Every write endpoint gates on `require_user_or_admin`**, so a guest gets 403.
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
