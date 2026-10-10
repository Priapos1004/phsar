# Backend services — design notes

Per-service notes for things that live only in this tree. Anything spanning several
modules is written up whole in `docs/features/` and only pointed at from here, so
there is one copy to keep correct.

| Service | Written up in |
|---|---|
| `mal_scraper.py` | [scraping](../../../docs/features/scraping.md) |
| `search_service.py` — BFS output → save/attach/merge decisions | [scraping](../../../docs/features/scraping.md), [relations](../../../docs/features/relations.md) |
| `relation_classifier.py`, `anime_relation_service.py` | [relations](../../../docs/features/relations.md) |
| `merge_detection_service.py`, `merge_candidate_service.py` | [relations](../../../docs/features/relations.md), [curation](../../../docs/features/curation.md) |
| `split_candidate_service.py` (and `seeders/split_candidate_backfiller.py`) | [relations](../../../docs/features/relations.md), [curation](../../../docs/features/curation.md) |
| `delete_candidate_service.py` | [curation](../../../docs/features/curation.md) |
| `job_worker.py`, `progress_reporter.py`, `job_submission_service.py` | [jobs](../../../docs/features/jobs.md) |
| `scrape_dispatcher.py`, `seasonal_sweep_dispatcher.py` | [jobs](../../../docs/features/jobs.md) |
| `backup_dispatcher.py`, `backup_service.py` | [backups](../../../docs/features/backups.md) |
| `browse_service.py` (and `seeders/browse_seeder.py`) | [browse](../../../docs/features/browse.md) |
| `vector_embedding_service.py` | [search](../../../docs/features/search.md) |
| `media_search_service.py`, `anime_search_service.py`, `filter_service.py` | [search](../../../docs/features/search.md) |
| `spoiler_service.py` | [spoilers](../../../docs/features/spoilers.md) |
| `rating_service.py` | [ratings](../../../docs/features/ratings.md) |
| `watchlist_service.py`, `tag_service.py` | [watchlist](../../../docs/features/watchlist.md) |

Two small helpers with no feature doc of their own:

- **`anime_summary.py`** — `summarize_anime(anime, rating_count)` renders the
  side-by-side anime card shared by the merge and split queues, so a future field
  addition lands in one place.
- **`completion_service.py`** — admin story-complete curation: mark (idempotent
  insert), unmark (delete), and the marked list. A **manual** flag with no detector
  and no dismissal history, unlike merge/split. The Completion tab's anime lookup
  reuses the public `/search/anime`, so there is deliberately no search method on
  `AnimeCompletionDAO`.

## Auth / settings / tokens

- **`auth_service.py`** — registration, authentication, token issuance, account deletion
- **`user_settings_service.py`** — user settings CRUD + default creation. `update_settings` takes the caller's `role` and drops `spoiler_level` from the update for `RestrictedUser` (guests are pinned to `off` — they can't rate, and are excluded from the spoiler cache; honouring a non-off value would read an empty cache and hide everything). All other settings stay editable
- **`token_service.py`** — compressed JWT for shareable filter URLs
- **`admin_service.py`** — registration token list + delete; `get_job_for_admin(uuid)` for the `/admin/jobs/[uuid]` detail page (404s on miss; routes through `JobDAO.get_by_uuid_with_relations` which eager-loads `requested_by` + `parent` via the shared `_ADMIN_LOAD_OPTIONS` tuple so list + detail paths can't drift). `result_summary` is the one place the two paths deliberately differ — see [jobs](../../../docs/features/jobs.md); what matters here is that `_job_to_admin_response` stays a single builder for both, so the difference is carried entirely by what the DAO hands it and the list path's rows are read-only by intent
- **`admin_stats_service.py`** — aggregate counts for the admin Overview tab (catalog totals, job health by kind with retryable-failed subset, 7d activity counters, sweep-tier breakdown). **Job health windows each kind separately** via `JOB_HEALTH_WINDOW_DAYS` (keyed on `JobKind`, no default) and ships each window per row as `window_days`; the sizing rationale is on the table itself. Catalog and activity keep their own shared 7d cutoff. All-aggregate by design — no per-user breakdowns; the Jobs Log surfaces that where it's needed for debugging. No caching (admin-only, queries are sub-150ms). `_jobs_stats` gates `retryable_failed` on `requested_by_user_id IS NOT NULL` — the bell's retry button only fires on user-owned rows, so counting system retryables (sweep / cron-backup failures that retry on their own schedule) would imply admin action is available when it isn't. `_sweep_tier_breakdown` / `_media_sweep_tier_breakdown` run `AnimeDAO.count_by_sweep_tier_priority` / `count_media_by_sweep_tier_priority` (mutually-exclusive **cycle-membership** buckets in a priority cascade, enumerated once in `count_by_sweep_tier_priority`'s docstring) at anime and media grain respectively, feeding the Overview `sweep_tiers` + `media_sweep_tiers` for the SweepTiersCard anime/media toggle. Membership-only (staleness atoms excluded) so counts are stable across sweeps. `select_due_media_for_sweep` composes the same media atoms PLUS staleness for the actual due-selection; consumers share `_sweep_atoms()` / `_media_sweep_atoms()` in `anime_dao.py`. The "revisit if any single query crosses ~10 ms" note is why the anime grain reads its atoms from a single pre-aggregated `_anime_sweep_cte` rather than a correlated subquery per atom — see the `_anime_sweep_cte` / `_sweep_atoms` docstrings in `daos/anime_dao.py` for the SubPlan-multiplication that shape causes and the no-coalesce rule that comes with the LEFT JOIN. `_watchlist_stats` adds all-users watchlist aggregates via un-scoped DAO helpers (`WatchlistDAO.count_total` / `count_distinct_anime` / `count_distinct_users`, `TagDAO.count_custom_total`); averages are computed in Python over `users_with_entries` ("per active watchlist user", 0 when none), and the list counts exclude the immutable default tag. `_activity_stats` adds a `watchlist_modifications` counter (`WatchlistDAO.count_modified_since(cutoff)` — entries with `modified_at >= cutoff`, i.e. adds + edits) and folds a third `Watchlist.user_id WHERE modified_at >= cutoff` subquery into the `active_users` UNION, so a user who only touched their watchlist in the window still counts as active

## Export

- **`export_service.py`** — flat media-level export merging catalog + ratings + watchlist; respects user's `name_language` for localized title columns. One tag per entry, so the export carries a single `watchlist_tag` column (the entry's one list name)
