---
description: Modelling and migration invariants — BaseModel, operational sidecars, and the index rules autogenerate can silently undo.
paths: "phsar/{app/models,app/daos,alembic}/**/*.py"
---

# Database rules

## New tables inherit `BaseModel`

`id + uuid + created_at + modified_at` by default — including cache and sidecar
tables where `uuid` feels unnecessary. The timestamps are debugging signal: when a
row's behaviour diverges from what its content suggests, when it was inserted
versus last touched is sometimes the only evidence available, and consistency
across every table beats per-table justification.

`user_visible_media` is the one table on bare `Base`; its docstring argues the
case for a pure cache table. Treat that as the exception that needs arguing, not
the default — and if a new table has the same case, raise it rather than deciding
alone.

## Operational state goes in a 1:1 sidecar

When adding tracking or audit state — `last_checked_at`, sweep counters, freshness
pointers — to an entity that is serialized to the API, put it in a sidecar table
rather than a column on the canonical row.

Ask: is this **what the entity is**, or **how the system tracks it**? The latter is
a sidecar. Catalog rows reach Pydantic via `model_dump()`, so an inline tracking
column leaks sweep cadence into API responses and widens the row.

Shape: `unique=True` on the FK column to enforce 1:1 (as `anime_search` and
`media_search` do), plus `uselist=False`, `cascade="all, delete-orphan"` and
`lazy="raise"` on the parent relationship. Read paths **`LEFT JOIN` and `COALESCE`**
against a sensible default (e.g. the parent's `created_at`) so a parent inserted
without its sidecar still queries correctly.

Inline columns stay right for fields the API legitimately exposes (`media.score`,
`media.airing_status`) and for the `BaseModel` timestamps.

## Indexes must be declared in the model, not only the migration

An index present in a migration but absent from the model's module-scope
`Index(...)` block will be **proposed for DROP by the next `--autogenerate`**, so a
migration-only index silently loses its query the access path it exists for.
`alembic check` in CI is the guard — it must both agree with the models and replay
from empty.

Do **not** index a sidecar's `last_checked_at`. The planner could not use it (the
staleness predicate is a `coalesce` across a joined table, so it isn't sargable,
and the `ORDER BY` sits on the nullable side of a LEFT JOIN), and it would be worse
than inert: it would be the only indexed *mutable* column on the sidecar, turning
every sweep write into a non-HOT update.
