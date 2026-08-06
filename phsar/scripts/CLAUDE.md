# Dev DB helper scripts

One-off scripts for inspecting and mutating the dev database directly. Useful
for debugging contamination cases, validating sweep behavior, resetting state
between scrape tests, and re-running production-grade detection without
restarting the backend. Future Claude sessions should know these exist —
they're the fastest way to answer "what does the DB actually look like".

Run from the `phsar/` working directory (the `app.*` imports require it):

```bash
cd phsar
python -m scripts.<script_name> [args]
```

## Scripts

| Script | Read/Mutate | Purpose |
|---|---|---|
| `audit_cross_franchise.py` | read-only | Production-spec audit: scans every Anime row and prints (+ JSON-dumps) any that contain disjoint substance-passing main chains. Calls the same `find_disjoint_franchises` function used by detection in `save_service`, the relation-backfiller, and merge-survivor — so the audit IS the production spec. Re-run after any classifier rule change. |
| `audit_relation_backfill.py` | read-only | Dry-run audit of the relation backfiller: shows which anime would have their umbrella row rewritten or media reclassified by the next backfill pass. Safe to re-run; produces a per-anime diff. |
| `find_anime.py` | read-only | Find anime by mal_id OR by substring across `title` / `name_eng` / `name_jap` / `other_names` (the JSONB column the older `inspect_anime_relations` misses). Use when you know the mal_id but not the title, or vice versa. |
| `inspect_anime_relations.py` | read-only | Per-anime detail: prints media count, every Media row's mal_id/type/relation_type/title, and the contents of each `MediaRelationEdges` sidecar. The first place to look when investigating a contamination case. |
| `inspect_jobs.py` | read-only | Inspect the `jobs` table — queued/running/recently-finished rows with progress fields. Use when worker behavior is suspect (a job appears stuck, a sweep didn't fire, the bell is showing stale state). |
| `delete_anime_by_title.py` | **mutates** | Delete Anime rows by title substring. Dry-runs by default; pass `--apply` to actually delete. FK cascades clean up media + ratings + watchlists + merge/split candidates. Use to reset state between re-scrape verification tests. |
| `seed_demo_sweep_job.py` | **mutates** | Insert a realistic demo `update_sweep` **v7** job (built from REAL catalog rows so every link resolves) for visually evaluating the admin job-detail page + Jobs Log without waiting for a nightly sweep — exercises the counters grid, Anime/Media changes (incl. genre/studio drift), the ~10-failure scrollable Failed-refresh/Failed-probe lists, the "Attached via probe" card (Tensei Slime + siblings), the progress-divergence notice, and the Jobs Log amber + blue row tints. Dry-runs by default; `--apply` inserts, `--delete --apply` removes (idempotent via a payload marker), `--no-genre-tags` drops the unknown-genre drift so the row gets NO amber tint (amber outranks blue) — use it to see the blue probe-attach tint in isolation. `--hentai` adds `hentai_removed` entries so the v7 "Removed (Hentai)" card + rose Jobs Log tint render; opt-in because rose OUTRANKS amber/blue, so it masks the other tints on the same row. |
| `backfill_seasonal_sweep_parents.py` | **mutates** | One-shot historical fix: attributes pre-clustering `user_scrape` children with `requested_by_user_id IS NULL` to the most recent `seasonal_sweep` whose `created_at` precedes them. Safe because `seasonal_sweep_dispatcher` is the only production source of NULL-user user_scrapes. Idempotent — only touches rows where `parent_job_id IS NULL`. Already applied to the dev DB; kept around so a future restored backup can be cleaned up the same way. |

## Example invocations

```bash
# Audit the dev DB for cross-franchise contamination
python -m scripts.audit_cross_franchise

# Inspect Boku no Hero Academia + its 27 media + sidecars
python -m scripts.inspect_anime_relations "Boku no Hero"

# Find an anime by mal_id (when title isn't memorable)
python -m scripts.find_anime --mal 31964

# Find an anime by substring across all name fields (incl. other_names JSONB)
python -m scripts.find_anime "ple ple"

# Look at the last 20 jobs
python -m scripts.inspect_jobs

# Reset BNHA to re-scrape it under the new BFS
python -m scripts.delete_anime_by_title "Boku no Hero"            # dry-run
python -m scripts.delete_anime_by_title "Boku no Hero" --apply    # actually delete

# Dry-run the relation backfiller without writing
python -m scripts.audit_relation_backfill
```

## The dev database is a restored prod dump

Since v0.15.4 the dev DB is **`pgvector/pgvector:pg17`** (matching prod) loaded
from a production dump, not a small hand-scraped catalog. Query plans, index
choices and page-load timings are only worth measuring at prod shape, and the
v0.15.3 follow-ups that were "gated on a prod-snapshot plan check" need it.

### 🎯 Use postgresql@17 everywhere — @15 breaks two different things

```
pg_restore: error: unsupported version (1.16) in file header
pg_dump:    error: aborting because of server version mismatch
```

Dumps come from a PostgreSQL 17 server (`pg_dump -Fc`, archive header `v1.16`),
so Homebrew's `postgresql@15` can neither read them nor talk to the container.
Two consequences, and the second is easy to misread as a regression:

- **Your own commands** must use `/opt/homebrew/opt/postgresql@17/bin` over TCP
  (`docker exec` is blocked by the agent sandbox here).
- **The backend shells out to whatever `pg_dump` / `pg_restore` is on `PATH`**
  (`_pg_subprocess`), so a shell with @15 first fails the whole backup test
  suite. Nothing is wrong with the code — prod's container ships matching v17
  tools. Fix the shell profile, or prefix one-off runs:

  ```bash
  PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH" pytest
  ```

### Rebuilding it

```bash
# Credentials come from phsar/.env — DB_USER / DB_PASSWORD / DB_NAME.
docker rm -f anime-postgres && docker volume rm pgdata
docker run --name anime-postgres \
  -e POSTGRES_USER=<DB_USER> -e POSTGRES_PASSWORD=<DB_PASSWORD> \
  -e POSTGRES_DB=<DB_NAME> -v pgdata:/var/lib/postgresql/data \
  -p 5432:5432 -d pgvector/pgvector:pg17

PGB=/opt/homebrew/opt/postgresql@17/bin
export PGPASSWORD=$(grep '^DB_PASSWORD=' phsar/.env | cut -d= -f2-)
$PGB/pg_restore -h localhost -p 5432 -U <DB_USER> -d <DB_NAME> \
    --no-owner --no-privileges backups_prod/phsar-YYYYMMDD-HHMMSS-manual.dump
$PGB/psql -h localhost -p 5432 -U <DB_USER> -d <DB_NAME> -c "VACUUM ANALYZE;"
cd phsar && alembic upgrade head
```

The dump carries its own schema **and** `alembic_version`, so restore into an
empty database and migrate afterwards — never `alembic upgrade` first.

- **`VACUUM ANALYZE` is not optional.** `pg_restore` leaves no planner
  statistics behind, so every `EXPLAIN` before it runs on default estimates and
  is worthless for comparing query shapes.
- **The live `jobs` table restores empty** — `backup_service` dumps with
  `--exclude-table-data=jobs` and stages terminal (`succeeded`/`failed`) rows
  into **`_jobs_dump_staging`** instead. Read that table directly for sweep
  history / `result_summary`, or replay what a real restore does
  (`_merge_jobs_audit_and_record_restore`) to populate the Jobs Log and the
  admin Overview job counters:

  ```sql
  INSERT INTO jobs SELECT * FROM _jobs_dump_staging ON CONFLICT (id) DO NOTHING;
  SELECT setval('jobs_id_seq', GREATEST(COALESCE((SELECT MAX(id) FROM jobs), 0), 1));
  DROP TABLE _jobs_dump_staging;
  ```

- **`pg_stat_user_indexes` resets on restore.** Index *usage* evidence ("0
  lifetime scans", HOT-update ratios) can only come from the live prod DB; a
  restored snapshot answers the *plan* question, not the *usage* one.
- **Set `RELATION_BACKFILL_ON_STARTUP=False`** before booting the backend
  against a fresh restore, or the first startup spends ~14 min at MAL's 1 req/s.
  The seeders will also add a local admin beside prod's users; harmless.
- To keep prod state isolated instead of adopting it wholesale, the same
  `pg_restore` line into a `CREATE DATABASE prod_investigate;` scratch DB still
  works — point `psql` / a `DB_NAME` override at it.

## Conventions

- **Read-only by default.** Any script that mutates state requires `--apply` (mirrors the existing convention in `delete_anime_by_title`).
- **No MAL calls.** All scripts operate on the local catalog only. Re-fetching from MAL is the job of the seeders + dispatchers, not these one-off scripts.
- **Module docstrings carry the rationale.** Each script's `"""..."""` header documents the WHY and the usage line. Keep them up to date when behavior changes.
