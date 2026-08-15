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
grow a pass-through service — `routers/library.py` and `GET /jobs/mine` do. The
test is fetch-and-return with nothing in between; passing `current_user.id` as a
filter still counts, since it branches on nothing. A quota, an ownership check
that can raise, or a write is business logic and belongs in a service.

Where a router owns a write anyway, it **argues the case in its module
docstring** — that is the bar, and the reason the cron scheduler's enqueue is
allowed to sit next to its endpoints while the user-facing one is not.

The reverse shape exists too — services that execute statements against the
session instead of going through a DAO. It is **tolerated where it already is,
not a pattern to copy**: new SQL goes in a DAO. Assume you are outside the
exception rather than inside it, because the cases that stay are narrow and
argue for themselves at the call site — DDL that has no ORM expression, an
aggregation that exists to be one query, or a write whose transaction boundary
would break if a DAO owned it.

**Seeders reach the model layer directly too**, outside `routers → services →
DAOs`. They run at startup and are also invoked directly by a few routers and
services, so treat them as a backfill layer that may reach the session, not as
services with a different name. **A seeder does not own its transaction** — it
leaves the commit to whoever called it, so that a caller can batch several into
one. That is why a handler invoking one ends in a bare `db.commit()`.

## Async — the two that bite

- **Never `asyncio.gather` coroutines that share one `AsyncSession`.** An
  AsyncSession cannot multiplex concurrent operations; `gather` corrupts
  in-flight query state, so session work runs sequentially. Pure-CPU coroutines
  that never touch the session (an embedding encode via `to_thread.run_sync`)
  are safe to gather. Canonical "don't" in `seasonal_sweep_dispatcher.py`;
  failure mode in `compound-docs/2026-05-09-v0.14.0-content-pipeline.md`.
- **Every relationship is `lazy="raise"`.** Load related rows explicitly with
  `selectinload` in the DAO query; an implicit lazy access raises rather than
  silently emitting a query. The same applies at column grain when a query
  deliberately omits a column: `defer(..., raiseload=True)`, so a path that
  forgot about it faults instead of emitting one lazy load per row.

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
reach an admin mutation. *Write* means it touches the database: a POST that only
encodes or decodes its own body takes no `db` and is not one.

A short, closed set of endpoints is deliberately role-ungated, and nothing should
join it without argument. `/auth/register` and `/auth/login` are public — both
write, which is why they are named here rather than left to the rule above.
`/auth/refresh` and `PUT /users/settings` take bare `get_current_user`, so a guest
keeps its sliding session and its own theme; the settings service drops
`spoiler_level` for a restricted user rather than the endpoint refusing the call.

**A read whose rows are scoped to the caller gates like a write by default**, and
the test is what an empty answer would mean. Usually it reads as a bug rather
than as a permission boundary, which is the failure the gate exists to prevent —
that is why ratings, watchlist and spoiler visibility all 403 a guest instead of
returning nothing. Leave one ungated only where emptiness is the *intended*
state and the UI says so: the bell reads `/jobs/mine` for a guest who can never
own a job, and the navbar comments that it is deliberately always empty.

The admin/non-admin split is not the whole picture: the
[cron-authed schedulers](#triggering-operational-jobs) sit under `/admin` on a
separate chain with no role check at all. Every other
`/admin` sub-router binds its dependency once on the router; theirs binds
per-route, and neither it nor the parent carries one. So an endpoint added to
that module with a plain `@router.post(...)` is **unauthenticated**, not
admin-gated and not even bearer-gated — the decorator has to carry its own
`dependencies=`.

Compare with the `RoleType` enum, never a `.value` string — `.value` belongs
only at a serialization boundary, such as a JWT claim or a log line.

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
