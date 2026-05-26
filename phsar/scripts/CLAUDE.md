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

## Conventions

- **Read-only by default.** Any script that mutates state requires `--apply` (mirrors the existing convention in `delete_anime_by_title`).
- **No MAL calls.** All scripts operate on the local catalog only. Re-fetching from MAL is the job of the seeders + dispatchers, not these one-off scripts.
- **Module docstrings carry the rationale.** Each script's `"""..."""` header documents the WHY and the usage line. Keep them up to date when behavior changes.
