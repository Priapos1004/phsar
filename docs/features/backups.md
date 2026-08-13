# Backups

`pg_dump` / `pg_restore` orchestration, retention, and the verdict on whether a
dump is actually restorable.

**Code**: `services/backup_service.py` (all logic) →
`services/backup_dispatcher.py` (the `backup` job handler) → `routers/admin.py`
for the CRUD sub-router, `routers/admin_jobs.py` for the cron enqueue points.

## Creating a dump

Writes go to a `.partial` file and are renamed atomically, with a sidecar
`.meta.json` beside each dump and content-hash dedupe so an unchanged database
doesn't accumulate identical archives.

Backup creation does **not** enter maintenance mode — `pg_dump` runs on an MVCC
snapshot, so concurrent user writes are safe. Restore does, and is deliberately
synchronous.

All write paths serialize on a module-level `asyncio.Lock` (single-worker
assumption), including the sidecar read-modify-write. Subprocess passwords go via
`PGPASSWORD`, never on the command line.

`enqueue_backup_job` is the single enqueue path for every trigger — the manual
endpoint, the cron endpoints, and the startup self-heal. It lives in the service
because routers depend on services, not the reverse.

## Is this dump restorable?

Two distinct questions, deliberately kept apart:

- **`integrity`** — is the *file* intact? Set at create time and re-verified by
  every backup job.
- **`schema_current`** — does the dump's schema match the live database?

Each dump records the **Alembic revision it carries**, parsed out of the
`COPY public.alembic_version` block during the content-hash stream, so it costs no
extra subprocess. Reading it from the *dump* rather than the live DB is what makes
it correct for an **uploaded** dump, whose schema is not the running one.

**`status` is the composite verdict**: `corrupt` > `outdated` > `unknown` > `ok`.

A dump reads `unknown` when its recorded revision is missing. That happens when the
sidecar was rebuilt from an orphaned dump — `_rebuild_meta` reads the TOC only, so
it can recover neither the revision nor the content hash.

Two design points worth keeping:

- **The schema verdict is not folded into `integrity`.** Retention pins the
  most-recent-`ok` dump as its archival anchor, so a schema verdict inside
  `integrity` would flip every dump non-ok the instant a migration ran — leaving
  retention anchorless exactly when the install is most exposed.
- **`status` is derived server-side, not in the UI.** The card, its sort order, and
  the startup self-heal all answer the same question; while the frontend composed
  it, they disagreed — a revision-less dump rendered a green `ok` pill while the
  self-heal had just judged nothing on disk restorable. So **`unknown` is not
  `ok`**: a dump nothing vouches for should not be advertised as reliable.

The listing returns a `BackupListResponse` envelope carrying the **live** revision
alongside the rows, read once per response. Reading it a second time for the
envelope would let a migration landing between the two reads badge a row "outdated
against X" beside a displayed live revision that isn't X — the exact divergence
`status` exists to remove.

## Restart-triggered backups

`ensure_up_to_date_backup` enqueues a dump when nothing on disk has `status == ok`
and no `backup` job is already active — the in-flight guard keeps a restart storm
from queueing one dump per boot.
The container migrates before the app process starts, so after a migrating deploy
every existing dump carries the previous revision and restoring one would roll the
schema back — this closes the window where an install has nothing restorable until
the next nightly run.

It runs post-yield (listing may shell out `pg_restore --list` per sidecar-less
dump) and **first** among the post-yield passes: those are all idempotent derived-
data repairs that re-run every boot, so a pre-backfill dump loses nothing while a
post-backfill one couldn't recover from a bad backfill.

**An unreadable live revision is a no-op**, even though nothing then looks
restorable. `status` is a comparison against that value, so with it unknown every
dump degrades to `unknown` *and* a fresh dump couldn't clear the condition either —
it would re-fire every restart and fill the archival pool during a crash loop.
Can't tell, don't act.

Convergence depends on the dedupe path stamping the revision onto a matched
sidecar that lacks one. Byte-identical content means the revision applies verbatim,
and this is the only path that can stamp an existing dump; without it an install
whose content already equals its last dump would dump, dedupe and discard the
revision on every boot forever.

## Retention

Three independent pools. Slots are counted over the **un-named** subset of each, so
pinned dumps are kept *on top of* a full rolling window rather than consuming it.

| Pool | Keeps |
|---|---|
| Archival (manual + cron) | 14 most recent + latest-per-Sunday for 8 distinct Sundays + most-recent-known-good |
| Pre-restore | the snapshot tied to the current state, plus the 3 most recent |
| Uploads | 5 most recent |

Pre-restore snapshots are **rollback points, not weekly history**. A pre-restore's
timestamp is the restore moment and could land on a Sunday, so it must never
occupy an archival slot.

"Latest per Sunday" rather than a simple slice, because several dumps on one Sunday
would otherwise eat every weekly slot.

Every pool also pins the dump `.current_db.json` points at, so a run of dedupe-hit
re-confirms can't push the pointed-at dump out of the recent window.

**Re-verification runs before retention.** `reverify_backups` re-runs the cheap
TOC-only `pg_restore --list` across every dump and refreshes `integrity`, so the
"most recent known-good" pin reflects what is on disk *now* rather than a
create-time snapshot. Reversing the order would let retention anchor on a dump that
has since corrupted. It skips a dump deleted mid-loop — backup jobs don't bracket
maintenance, so a concurrent admin delete is respected rather than treated as
corruption that fails the whole job.

## Naming is the pin

Setting a non-empty `name` pins a dump against auto-retention; clearing it unpins.
There is deliberately **no separate pin toggle** — every pinned dump is forced to
carry a human-readable reason, so the admin can't accumulate anonymous pins and
later forget why a dump is protected. The name is the justification.

`name` is the admin display name and never touches the filename, unlike the
creation-time `label` which becomes a filename suffix.

## Restore

The UI requires the admin's username as a confirmation string. A pre-restore
snapshot is taken automatically, then `pg_restore --clean --if-exists --no-owner
--no-privileges` runs with maintenance active.

On success the pre-restore's sidecar is stamped with `restored_to`, and the current
row derives a "Previous state saved as …" link from it. The persisted `restored_to`
survives pointer moves; the derived link mirrors `is_current`.

`.current_db.json` tracks which dump matches the live database. Every successful
create sets it, whatever the source. **Uploads never move it** — uploaded bytes are
external and can't be verified to match live. Deleting the pointed-at dump clears
it.

## Download

The download opts out of gzip, so a dump arrives as raw
`pg_dump -Fc` bytes with a real `Content-Length`. The mechanism and the RFC wart
that comes with it are argued at the call site, `routers/admin.download_backup`.

## Path safety

`get_backup_path` is the single filename chokepoint for delete, restore, rename and
reverify; its filename pattern rejects separators and `..`, so a constructed path
can't escape the backup directory. CodeQL flags the downstream sidecar operations
as `py/path-injection` because it doesn't model the regex as a sanitizer — those
are dismissed as false positives.

---

**Why it is this way**
- [Deployment](../../compound-docs/2026-04-19-v0.13.0-deployment.md) — the original design
- [Backup retention refinement](../../compound-docs/2026-06-16-v0.14.6-backup-refinement.md) — the three pools
- [Quality-of-life upgrades](../../compound-docs/2026-07-27-v0.15.3-quality-of-life.md) — revision stamping and the composite status
