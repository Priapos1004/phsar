# Backend services — design notes

Per-service rationale for `phsar/app/services/`. Loaded on top of root [CLAUDE.md](../../../CLAUDE.md) when working in the backend tree. Root has the architecture map and cross-cutting Key Patterns; this file has the deep "why" per module.

## jikan_scraper.py

MAL API client with retry + client-side rate limiter.

- Retry: Tenacity `wait_exponential(multiplier=2, min=1, max=30)` × 5 attempts
  - `retry_if_exception(_is_transient_mal_error)` gates retries to 5xx + timeouts + network errors
  - 4xx is deterministic and burns 31s of backoff before failing the same way
  - `reraise=True` surfaces the underlying `HTTPStatusError`/`TimeoutException` instead of wrapping in tenacity's `RetryError`
- Asymmetric 429 handling: retried but capped at 3 total attempts (2 retries — enough to bridge a misaligned per-minute window), while 5xx/timeout/network get the full 5
  - Why: retrying 429 harder masks sustained throttling instead of fixing it; the right response is to slow the source rate
  - Other 4xx (most importantly 404) is deterministic-non-retryable
- Rate limiting: class-level `_rate_lock` + `_MIN_REQUEST_INTERVAL_S=1.0s` spaces request *starts* at 1 req/s
  - Jikan documents 3 req/s burst AND 60 req/min sustained — the per-minute ceiling binds for continuous-request flows like `/seasons/now` pagination and bulk-refresh sweeps
  - 0.35s and 0.5s both observed 429s in practice
  - Jikan's docs also note MAL upstream can rate-limit independently
- BFS in `search_title`:
  - Accepts optional `ProgressReporter` so user-scrape jobs can stream progress to the bell
  - Takes `seed_mal_id` + `seed_payload` so the sweep probe can BFS from a known mal_id instead of the fuzzy `q=<title>` top-3 lookup (that lookup pulls unrelated franchises into the catalog if used for known-mal_id probes — see compound-doc)
  - When `seed_payload` carries a `/full` response with relations bundled, the BFS reuses them instead of paying a second `/anime/{id}/relations` hit
- Skip rules:
  - Anime with `media_type=None` AND `airing_status="Not yet aired"` are skipped silently — they used to land in `media_unwanted` as `Unknown`, permanently blocking rediscovery once the show aired; now only true anomalies (null `media_type` with a non-Not-yet-aired status) get blacklisted
  - Anime with `title=None` are skipped silently — MAL routinely leaves the romanization field null on freshly-announced donghua/Chinese shows and PV stubs (fills in within hours); blacklisting with a `<mal_id:NNNN>` placeholder would pollute `media_unwanted` and block rediscovery
- **TERMINAL state semantics (split-candidates change):** Nodes arrived via identity-breaking edges (`side_story`/`spin-off`/`parent_story`/`other`/`summary`/`full_story`) are TERMINAL — the BFS captures their outgoing edges (so split-detection can see e.g. Vigilante S1's sequel chain leaking out of BNHA's row) but does NOT recurse from them. The for-loop in `search_title` skips queuing TERMINAL targets via `if current_status is TERMINAL: continue`. Pre-split-candidates TERMINAL nodes had empty sidecars (`edges=[]`); post-split-candidates they carry their MAL relations like WALK nodes

## job_worker.py

Single asyncio FIFO worker draining the `jobs` table.

- Claims jobs via `with_for_update(skip_locked=True)`
- `wakeup` Event for sub-second pickup with a 60s wall-clock fallback (shortens to 2s while `is_maintenance_active()` — restore lifts the gate without calling `notify()`, so the idle poll has to catch the transition itself)
- Dispatcher table maps `JobKind → handler` (registered from `main.py` lifespan)
- Failure handling:
  - Stamps `result_summary.retryable = not isinstance(failure, PermanentPhsarError)` so the bell knows whether to show a retry button
  - Stamps `result_summary.error_category` via `classify_error` (public; also reused by `scrape_dispatcher` to tag per-anime step-1 failures):
    - `upstream_outage` — httpx 5xx + TimeoutException + NetworkError + `TransientUpstreamError` (MAL returning 200 with empty data on a known mal_id)
    - `backup_disk_full` — `BackupDiskSpaceError`
    - `backup_corrupt` — `BackupIntegrityError` (pg_dump output that fails `pg_restore --list` integrity check)
  - The bell renders friendly text instead of raw error strings; uncategorized errors fall through to the raw `error_message`, which is already friendly for custom domain errors
- Session management: sequential per-job sessions (claim-tx then work-tx in fresh sessions) avoid asyncpg pool deadlocks under nested-savepoint patterns
- **Post-dispatch failure hardening (v0.14.5):** three guards keep a job from getting stranded in `running` when a downstream crash hits after the dispatcher returned cleanly:
  - `job_uuid_str = str(job.uuid)` captured immediately after claim so the failure logger never reads ORM attributes on a poisoned session (a `mark_succeeded` flush crash leaves the work session in PendingRollback, and any attr read would re-raise mid-cleanup)
  - The inner `work_session.rollback()` is wrapped in try/except — rollback can itself fail after a flush error
  - An outer catch-all around the whole work-session block routes unexpected plumbing failures through the `mark_failed` path. The fail-session write is also wrapped so the worst case still emits an actionable log line. Without this, the row would sit until `reap_orphans` on next startup
- **Versioning:** every Job-construction site goes through `make_job(kind, **kw)` (`app/core/job_versions.py`), which stamps `job.version` from the `JOB_KIND_VERSIONS` registry. Frontend reads `job.version` to pick a parser for `result_summary`. Bump the integer per kind when its shape changes — `update_sweep` is at v5 after v0.14.8
- Maintenance bracketing:
  - Sweep-kind jobs (`update_sweep`, `seasonal_sweep`) are bracketed: `set_maintenance(True)` before dispatch, `set_maintenance(False)` + `set_scheduled_at(None)` in `finally` so a crash can't leave the flag stuck
  - `dispatch_one` short-circuits via `is_maintenance_active()` BEFORE claiming any row
    - Why: prevents a queued `backup` job from slipping in during a restore — restore takes its pre-snapshot, releases `_BACKUP_WRITE_LOCK`, then flips maintenance + disposes the pool + `pg_terminate_backend`s every other session; without the early-return, the worker could claim the backup between the pre-snapshot's lock release and `pg_restore` starting
    - The check is unconditional (all kinds) because any job during restore would have its session yanked by `pg_terminate_backend` anyway
    - Sweep-induced maintenance is a no-op for the check: the worker is already running the sweep inside `dispatch_one`, so `_run` doesn't re-enter while the flag is set

## scrape_dispatcher.py / seasonal_sweep_dispatcher.py

Handlers for `user_scrape` and `update_sweep` jobs (the catalog-mutation pair that share `_apply_media_diff` / `_weighted_score`).

`seasonal_sweep` handler lives in its own module `seasonal_sweep_dispatcher.py` because it shares no helpers — it's purely a discovery pass that hands off work to user_scrape.

- **`user_scrape`**: wraps `handle_search_mal_api_results` + `save_search_results` behind a `ProgressReporter`
  - System-enqueued children (from seasonal sweep) carry `seed_mal_id` in payload so each child's BFS skips the fuzzy top-3 lookup and seeds directly off the known mal_id
- **`update_sweep`** (media-level since v0.14.8): selects the due *media* via `AnimeDAO.select_due_media_for_sweep`, groups them by parent anime (`by_anime`), then per anime refreshes only the grouped due media — a still-airing umbrella's stable old members no longer pay a `/full` call every night. **Two freshness clocks**: `MediaFreshness` (`last_checked_at` + `stable_check_count`) is the per-media *refresh* selection clock; `AnimeFreshness` is the per-anime *probe* clock. Both share `SWEEP_STABILIZE_THRESHOLD` (3) and `SWEEP_LONG_TAIL_DAYS` (90).
  - **Step 1** — `_refresh_one_anime(anime, media_to_refresh)` refreshes each due media via `JikanScraper.refresh_anime` (`/anime/{id}/full`), diffs volatile fields (`score`, `scored_by`, `episodes`, `airing_status`, `aired_to`) via `_apply_media_diff`, advances that media's `MediaFreshness` via `_advance_media_freshness` (counter resets on volatile change or airing, else climbs), and rewrites `MediaRelationEdges` from the bundled `relations` block. `reclassify_anime` + `is_currently_airing` still run over the **full** `anime.media` set (eager-loaded), so umbrella drift + airing detection see the whole franchise even when only some members were refreshed
  - **Step 2** (only tier 3 + tier 4 — `not currently_airing AND AnimeFreshness.stable_check_count >= SWEEP_STABILIZE_THRESHOLD AND last probe ≥ 7 days ago`) — probes each Main media's relations via `JikanScraper.search_title(seed_mal_id=...)`, attaches discovered media via `save_service.attach_search_result_to_anime`, advances `AnimeFreshness`. The **7-day floor** keeps the probe at ~weekly cadence even though media-level selection can re-touch an anime on consecutive nights as its members drain. If the Main anchor wasn't in the due set, `raw_payloads` lacks its `/full` payload and `search_title(seed_payload=None)` fetches `/relations` itself (+1 MAL call) — intentional, the anchor is not force-refreshed
  - Two commits per anime + per-anime try/except:
    - Step 1 always commits durably (crash mid-sweep preserves field-diff work; single bad MAL response fails only that anime)
    - Step 2 only commits on probe success — failure leaves `AnimeFreshness` untouched so the tier query re-selects
  - **Step-1 counters are accumulated right after step-1 commits, before the probe runs** — a later `ProbeFailure` leaves the refreshed media committed (MediaFreshness already advanced, won't re-refresh next sweep), so dropping them from `media_refreshed` / `media_changes` would undercount real work. Only the probe counters depend on the probe outcome
  - **Progress is media-grained**: `items_total = len(due_media)`, `items_done = media_refreshed`. The bar advances in per-anime chunks (one commit per anime) but measures the true MAL-call/time unit. The end gap (`items_total - items_done`) is exactly the media of step-1-failed anime — probe failures don't widen it
  - Per-Main-seed BFS (each main gets its own `visited_ids`) lets the probe reach disjoint sub-graphs — walking from BNHA's main alone wouldn't surface Vigilante S2 because Vigilante S1 is a side-story and BFS stops expanding side-stories once a main is found
  - **First-sweep herd note**: the migration server-defaults every existing `MediaFreshness.stable_check_count` to 0, so on first run after deploy the whole long-tail catalog is "stabilizing"/due at once — drains over `catalog/JOBS_SWEEP_MAX_PER_RUN` nights, same one-time dynamic the anime sweep had at launch
- Score stability tracking:
  - `_weighted_score(score, scored_by) = score * log10(scored_by + 1)` — same formula used for search ranking
  - Only counts as stability-resetting when `abs(new − old) >= _SCORE_STABILITY_THRESHOLD = 0.05`
    - Why: without this, a single new vote per night on a million-vote anime resets the counter forever
  - None↔value transitions bypass the threshold (first votes coming in is structural)
  - New values are written through regardless; the threshold gates only the stability *signal*
  - Score/scored_by writes gated on `payload["scored_by"]` being truthy — MAL returns scored_by as None or > 0 (never literally 0), and `extract_information` coerces None → 0 for the not-null column, so a 0 during refresh means the field was omitted; clobbering a populated count would be silent data loss
- Stability counter (per media, v0.14.8): resets to 0 when that media is currently airing or its volatile fields changed (above threshold), else `min(prev + 1, 99)`. `volatile_changed` is also OR'd across the refreshed media to advance the anime probe counter
- **v5 result_summary (v3 v0.14.5, v4 v0.14.7, v5 v0.14.8):** captures every change as an auditable diff so admins can inspect the per-sweep delta on `/admin/jobs/[uuid]` and roll back if MAL propagates a data bug at scale. Shape: `{counters, media_changes[], anime_umbrella_changes[], unknown_genre_tags[], step1_failures[], probe_failures[], merge_detect_failed, cache_recompute_failed}`. v5 counters went media-grained: `media_refreshed` (renamed from `anime_refreshed`), `anime_touched` (distinct anime with ≥1 media refreshed), `media_skipped_fresh` (media belonging to touched anime not refreshed this run — mostly already-fresh siblings, the work the conversion avoids; observability only, free to compute); the `anime_with_dynamic/static_changes` pair was dropped (`media_with_*` carries the signal). Per-media entries carry old → new for every dynamic + static field write (via the `diff_sink` threaded into `_apply_media_diff` / `_apply_metadata_diff`) plus genre/studio M2M drift; umbrella entries carry the 7-field ReclassifyDiff via `anime_relation_service.umbrella_diff_to_log_entry`. Datetime values coerce to `isoformat()` at the diff-sink site via `_jsonable()`. The rename + removals force the v5 bump; the TS frontend keeps v2/v3/v4 parsers so historical rows still render
- **Step-1 / step-2 failure tracking:** `_try_step1_refresh` returns a typed `Step1Failure` (v4) on a refresh exception → `counters.step1_failed` + `step1_failures[]`. `_try_step2_probe` returns a symmetric typed `ProbeFailure` (v0.14.8) on a probe exception → `counters.probe_failed` + top-level `probe_failures[]` (same `{anime_uuid, title, error_category, error_message}` shape). Both reuse `job_worker.classify_error` so an MAL outage tags `upstream_outage`. Pre-capture `anime.uuid`/`title` before the savepoint (the rollback expires ORM attrs — same MissingGreenlet trap as step 1). Without these a sweep that dropped a chunk of its selection still rendered a clean `succeeded`
- **Drift apply policy (v0.14.5):** `_apply_genre_diff` and `_apply_studio_diff` now write every change (removals via `DELETE` on the M2M, additions via insert). Unknown genre tags still skip — the seed table is the deliberate source of truth for the user-facing taxonomy — but land in the sweep-level aggregate `unknown_genre_tags` so the Jobs Log row tints amber and lists them inline. Studios are a discovered taxonomy: unknown names auto-create a new Studio row. The audit log is the rollback path; the prior conservative log-only policy was spamming the admin with the same drift every sweep because nothing actually got written. Drift kinds shrink to `applied` and `applied_with_unknowns`; the TS frontend keeps the v2 vocabulary in its union so historical rows still render with accurate "not auto-applied" context
- Coalesced spoiler recompute fires once at sweep end if any new media landed, **scoped to `probe_attached_anime_ids`** via `refresh_spoiler_cache_for_anime_ids` — the probe path uses `attach_search_result_to_anime` (never recomputes) instead of `save_search_results` (always does), so a 200-anime sweep with 50 new media triggers one scoped recompute over those ~50 anime instead of 50 whole-catalog passes
- Coalesced `detect_merge_candidates` fires once at sweep end. Two scopes feed it: (a) `probe_attached_anime_ids` for the title_studio / title_desc signals (mirrors save-time detection that the attach path bypasses), and (b) `sidecar_touched_anime_ids` (all step-1 successes) passed to `find_cross_anime_relation_pairs` for the relation_link signal — broader scope because step 1 rewrites sidecars even when no media is attached, so a refresh alone can surface a fresh strong-link pair
- **`seasonal_sweep`**: paginates `JikanScraper.fetch_current_season` (`/seasons/now`)
  - Dedupes against `Anime.mal_id ∪ Media.mal_id ∪ MediaUnwanted.mal_id` (plus per-run dedupe so MAL's cross-page duplicates don't double-enqueue)
  - Bulk-inserts one system `user_scrape` child per new mal_id with `requested_by_user_id=null` (system jobs skip per-user cap)
  - Bulk-insert instead of per-row commit because the enqueue loop does no MAL I/O — crash-safety argument doesn't apply, shorter maintenance window matters more

## backup_dispatcher.py

Handler for the `backup` JobKind.

- Wraps `backup_service.create_backup(source, label)`
- Progress stages: `Dumping` → `Verifying backups` → `Applying retention` → `Done`
- Stamps `result_summary = {filename, size_bytes, integrity, source, deduped_against}` for the bell to render
- Catches `DuplicateBackupError` → success outcome with `deduped_against` populated (softer "no new data" line)
- `reverify_backups()` runs before retention — re-runs the cheap `pg_restore --list` check on every dump and refreshes the sidecar `integrity`, so a dump that corrupted on disk since creation stops listing as `ok` (the create-time flag is a snapshot). Cheap: `--list` reads only the archive TOC, sub-second per dump regardless of size. Ordered before retention so the `most recent known-good` pin reflects current disk state
- `apply_retention()` runs after every job — three pools (archival manual+cron: 14-recent + latest-per-Sunday×8 + 1-known-good; pre-restore: relevance buffer; uploads: 5-recent), with named/pinned dumps kept on top of each
- **No maintenance bracket**: `pg_dump` runs on an MVCC snapshot, user writes are safe
- `BackupDiskSpaceError` / `BackupIntegrityError` surface via `classify_error` as `backup_disk_full` / `backup_corrupt` with friendly bell copy; both stay `retryable=True`

## progress_reporter.py

Short-lived autocommit-tx writer pushing `(stage, items_done, items_total)` updates to a job row. 0.5s throttle with `force=True` bypass for stage transitions — keeps tight BFS loops from opening hundreds of sessions per second.

## search_service.py

Orchestrates BFS output into save/attach/merge decisions.

- Takes graphs from `JikanScraper.search_title`, runs DB-side dedupe against catalog + `media_unwanted`
- Per-graph decision: save as new anime, attach to existing anime, or surface as merge candidate
- Packages as `SaveAction | AttachToExistingAction` for the caller
- **`AttachToExistingAction`**: routes orphan side-story graphs (single cross-link to an existing Media, no main of their own) through `save_service.attach_search_result_to_anime` so a tier-1/2 parent's new side-story gets attached under the right anime instead of becoming a duplicate
- **Seed-mode anchor fallback** (v0.14.1): when the seeded BFS produces no clear main, the two-pass classifier picks the anchor from the captured nodes by anchor tier (TV > ONA > Movie > other) + substance gate + oldest aired_from. Necessary for donghua sub-universes whose canonical main is an ONA, and pilot-aired-before-the-real-show edge (tier > date)
- Cross-link signals are filtered to subtract `media_unwanted` mal_ids before the attach-vs-promote decision so filtered Music/PV entries don't get treated as franchise-overlap evidence
- `alternative_setting` is treated as a graph boundary (like `crossover`) but dropped entirely — MAL's explicit "different story, shared themes" label; conflating those into one Anime row triggered false-positive merge candidates on every sweep
- All MAL relation strings normalized once on entry via `_normalize_relation(rel) = rel.lower().replace(" ", "_")`
  - Before v0.14.0 comparisons used the underscore form but lists held raw MAL strings (`"Parent story"`), so the `is_main_story` gate silently let every franchise movie classify as `main` instead of `side_story`
  - See [compound-docs/2026-05-11-jikan-scraper-quirks.md](../../../compound-docs/2026-05-11-jikan-scraper-quirks.md)
  - Fix applies to new scrapes only; pre-fix catalog rows keep stale labels until re-scraped
- **Third-pass split detection runs alongside classification** (v0.14.2 split-candidates): `find_disjoint_franchises(nodes, edges, anchor)` finds substance-passing media outside the anchor's main+alt chain that form their own connected sequel chain. Result rides on `SearchResultDB.disjoint_franchises`; `save_service` upserts a `SplitCandidate` row when non-empty. **Skipped when the anchor itself fails the substance gate** (seeded weak-anchor saves) — with no meaningful main chain, any substance-passing sub-chain would surface as a false-positive split. Real franchise contamination re-detects when the strong-anchor sibling lands. See [compound-docs/2026-05-18-v0.14.2-split-candidates.md](../../../compound-docs/2026-05-18-v0.14.2-split-candidates.md)

## Vector + search

- **`vector_embedding_service.py`** — sentence-transformers embeddings
- **`media_search_service.py`** / **`anime_search_service.py`** — filtered DB search
  - Anime variant uses a two-phase query (GROUP BY + HAVING for filter/order, then detail fetch) with majority-genre logic
  - **Anime-view filters mirror the card's derivation in `_compute_anime_aggregates`**, not per-media WHERE: `age_rating` filters against `MAX(age_rating_numeric)`, `airing_status` against the priority-collapsed value (Currently → Finished → Not yet aired). Otherwise an anime with one Finished side-story would surface under the "Finished" filter despite the card showing "Currently Airing"
- **`filter_service.py`** — filter option values; view-type-aware for anime vs media ranges
  - Also home to `chronological_media_key(season_year, season_name, mal_id)` — the project-wide sort key for media within an anime. Used by `spoiler_service` (frontier walk), `anime_search_service` (anime-detail media table + timeline chart), and `media_search_service` (related-media carousel + `current_position` marker). All three call sites go through this helper so the order users see in the carousel matches the anime page table matches what the frontier walks — diverging keys = silent UX bug

## Auth / settings / tokens

- **`auth_service.py`** — registration, authentication, token issuance, account deletion
- **`user_settings_service.py`** — user settings CRUD + default creation. `update_settings` takes the caller's `role` and drops `spoiler_level` from the update for `RestrictedUser` (guests are pinned to `off` — they can't rate, and are excluded from the spoiler cache; honouring a non-off value would read an empty cache and hide everything). All other settings stay editable
- **`token_service.py`** — compressed JWT for shareable filter URLs
- **`admin_service.py`** — registration token list + delete; `get_job_for_admin(uuid)` for the `/admin/jobs/[uuid]` detail page (404s on miss; routes through `JobDAO.get_by_uuid_with_relations` which eager-loads `requested_by` + `parent` via the shared `_ADMIN_LOAD_OPTIONS` tuple so list + detail paths can't drift)
- **`admin_stats_service.py`** — aggregate counts for the admin Overview tab (catalog totals, 7d job health by kind with retryable-failed subset, 7d activity counters, sweep-tier breakdown). All-aggregate by design — no per-user breakdowns; the Jobs Log surfaces that where it's needed for debugging. No caching (admin-only, queries are sub-150ms). `_jobs_stats` gates `retryable_failed` on `requested_by_user_id IS NOT NULL` — the bell's retry button only fires on user-owned rows, so counting system retryables (sweep / cron-backup failures that retry on their own schedule) would imply admin action is available when it isn't. `_sweep_tier_breakdown` / `_media_sweep_tier_breakdown` run `AnimeDAO.count_by_sweep_tier_priority` / `count_media_by_sweep_tier_priority` (4 mutually-exclusive **cycle-membership** buckets in priority cascade — airing_now > stabilizing > weekly_cycle > long_cycle) at anime and media grain respectively, feeding the Overview `sweep_tiers` + `media_sweep_tiers` for the SweepTiersCard anime/media toggle (v0.14.8). Membership-only (staleness atoms excluded) so counts are stable across sweeps. `select_due_media_for_sweep` composes the same media atoms PLUS staleness for the actual due-selection; consumers share `_sweep_atoms()` / `_media_sweep_atoms()` in `anime_dao.py`

## Merge detection + reconciliation

- **`merge_detection_service.py`** — duplicate-anime detector
  - Three signals feed `merge_candidates`:
    - `title_studio` — SequenceMatcher ratio OR containment ≥ 0.85, gated by studio overlap
      - Containment additionally requires word-boundary on both sides of the match in the longer string AND a size floor of `MIN_CONTAINMENT_MATCH_CHARS=4` chars OR a full match where the shorter title is itself ≥ `MIN_FULL_MATCH_CHARS=3`
    - `title_desc` — weaker title match + description-embedding cosine ≥ 0.85
    - `relation_link` — `media_relation_edges` sidecar links one anime's media to media under a different anime via a strong-link relation (`sequel`, `prequel`, `alternative_version`). Sidecar is the **single source of truth** for the signal: the alternative would be ephemeral BFS state during a live scrape, which misses pairs created in separate scrape jobs (the Evangelion shape: NGE TV and Rebuild Movies as distinct umbrellas would never surface as candidates)
      - Sidecar-as-truth invariant: *if two catalog anime have media linked through any of the allowlist relations, the next `detect_merge_candidates` run proposes the pair — independent of job ordering, scope, or which catalog wave created them*
      - Allowlist, not blocklist: weaker MAL relation types (`spin-off`, `side_story`, `parent_story`, `summary`, `full_story`, `other`) are MAL asserting "related but distinct," not "duplicates." Validated against the prod catalog — filtering "anything non-crossover" produces dozens of cross-anime edges across ambiguous types; the strong-link allowlist surfaces only legitimate cases. The allowlist is `ALT_CHAIN_EDGES` (shared with `relation_classifier`'s alt-chain edge set — both ask "does MAL say these belong together?") — extend with care
      - Filters: `media_unwanted` targets (filtered franchise-overlap evidence) and same-anime targets (intra-umbrella relations) are excluded in the SQL
  - All three signals converge in `detect_merge_candidates`. The `relation_link` cross-link pairs are derived via `find_cross_anime_relation_pairs(db, scope_anime_ids=...)`, a thin service-layer wrapper around `MergeCandidateDAO.get_cross_anime_relation_pairs` that pins the `ALT_CHAIN_EDGES` allowlist. The DAO method owns the SQL (SQLAlchemy Core, `jsonb_array_elements` LATERAL TVF), matching the codebase convention that all queries live in DAOs. Called from three sites with identical semantics:
    - `save_service.save_search_results` — `scope=new_anime_ids` (sidecars already written this transaction)
    - `scrape_dispatcher.update_sweep_dispatcher` — `scope=sidecar_touched_anime_ids` (every step-1 success; broader than probe-attached so a refresh-only sidecar rewrite can surface a fresh strong-link pair)
    - `backfill_merge_candidates` — `scope=None` (whole catalog; powers admin's manual `POST /admin/merge-candidates/backfill` re-trigger endpoint)
  - Detection runs at the end of `save_search_results` (new × existing AND new × new — the latter catches single-scrape duplicates without waiting for a restart); startup `backfill_merge_candidates` covers existing × existing AND the relation_link sidecar sweep
  - `seen_pairs` pre-fetch short-circuits flagged or admin-resolved pairs before any signal computation — admin's dismiss decisions survive re-detection through every site

- **`merge_candidate_service.py`** — admin operations on merge candidates
  - List pending: ranked per-pair by `(earliest aired_from ASC nulls last, rating_count DESC, anime_id ASC)` so recommended-keep side surfaces as A
    - Uses `MergeCandidateDAO.get_rating_counts_for_anime` for tiebreak
  - Each list-pending item carries `pending_reclassifications: list[{media_uuid, title, old_relation_type, new_relation_type}]` — admin sees the per-media changes that would land before clicking merge (substance-gate demotions, alt-version labels, anchor flips)
  - Dismiss: status flip
  - Merge: re-parents B's media onto A, deletes B via cascade, calls `anime_relation_service.reclassify_anime` over the consolidated set (rewrites umbrella + regenerates embedding only when drift), runs `detect_merge_candidates` against survivor, recomputes spoiler cache
    - Accepts optional `keep_uuid` to swap which side survives — DB invariant `anime_a_id < anime_b_id` unchanged, A/B is presentation only
    - Fail-loud on shared `Media.mal_id` between A and B — global-unique-violation needs human review

## Two-pass classifier + third-pass split detection

- **`relation_classifier.py`** — pure-function two-pass classifier + third-pass split detection (all DB-less)
  - `classify_anime_relations(nodes, edges) -> (dict[mal_id, str], anchor)` — picks anchor by substance gate + tier + age, builds main chain via sequel/prequel closure, classifies alt-chain via `alternative_version` edges, defaults rest to `side_story`; demotes weak Mains via substance gate as final layer
  - `find_disjoint_franchises(nodes, edges, anchor) -> list[DisjointFranchise]` — third pass. Finds substance-passing media outside the anchor's main+alt closure that form their own connected sequel chain (≥2 substance-passing members per cluster). Returns one cluster per disjoint franchise with `member_mal_ids`, `substance_member_mal_ids`, `suggested_anchor_mal_id`, `bridge_edges`. The Overlord+Eminence shape, BNHA+Vigilante shape, Toaru Index+Railgun shape.
  - **Conan exception** (`_is_legitimate_side_story_chain`): movie-only clusters bridged to the anchor via `parent_story` or `summary` stay quiet — MAL is asserting "these are child stories" so they're legitimate side-story chains, not sibling franchises. Conan Movies 20/22 + summary clips trip the disjoint-cluster detector via sequel chains between movies; the exception keeps them inside Conan's anime row. Vigilante (TV-tier members) and Railgun (TV-tier members) are unaffected
  - Substance gate: TV/ONA needs `episodes>=8 AND duration_seconds>=600` (10min) — NULL episodes acceptable for currently-airing/long-running; Movie needs `duration_seconds>=1800` (30min); TVSpecial strict
  - **Not-yet-aired leniency (v0.14.7):** `ClassifierNode` carries `airing_status`; for `airing_status="Not yet aired"` a NULL duration/episodes is unpublished-metadata, not too-thin, so it gets a **provisional pass** (an announced sequel like Hell Mode S2 stays Main instead of being demoted to side_story). A *populated* short duration still fails; Finished-Airing NULL still fails (anomaly). Deliberately NOT extended to Currently Airing — an airing show normally has a published duration, and including it let a mid-franchise airing part steal the anchor (Fei Ren Zai). Provisional-pass nodes are **anchor-ineligible** in `_pick_anchor` (`_is_metadata_pending`) so a short-form franchise whose aired seasons fail the gate (Hyakushou Kizoku) doesn't flip its umbrella onto the unaired next season. `AIRING_STATUS_*` sentinels live here (the pure module); `jikan_scraper` re-imports them to avoid a cycle
  - Anchor tier: TV(1) > ONA(2) > Movie(3) > other(4); within tier oldest aired_from wins
  - `media_to_classifier_node` (ORM projection) + `build_classifier_nodes` (scraper-dict projection) co-located so future ClassifierNode field additions surface both
  - `_build_adjacency(edges, valid_ids)` filters dangling endpoints defensively — sidecars persist unfiltered edges so merge time can resolve previously-dangling bridges

- **`anime_relation_service.py`** — orchestrates `reclassify_anime(db, anime, *, dry_run=False)` over a loaded Anime
  - Detects drift on any of 7 umbrella fields (mal_id, title, name_eng, name_jap, other_names, description, cover_image); rewrites + regenerates embedding when drift present
  - `preview_reclassifications(anime_a, anime_b)` returns the per-media diff that would land if A absorbed B — read-only, powers the merge-candidate preview
  - `build_classifier_graph(media) -> (nodes, edges)` is the shared ORM→(nodes, edges) projection used at all three call sites (reclassify, audit script, split-candidate backfiller). Public function — earned its public name by virtue of multi-module reuse
  - Called from `relation_backfiller` (per catalog row) and `merge_candidate_service.merge` (survivor reclassification)

- **`split_candidate_service.py`** — admin operations on split candidates (parallel to `merge_candidate_service`)
  - List pending: uses `SplitCandidateDAO.list_pending_with_anime` which selectinloads source anime + media + relation_edges + media_studio.studio in one roundtrip; rating counts piggybacked from `MergeCandidateDAO.get_rating_counts_for_anime` (shared helper)
  - Dismiss: status flip
  - Execute: builds (nodes, edges) from the cluster's media subset, verifies the classifier still picks `suggested_anchor_mal_id` (raises `SplitCandidateStaleError(409)` if MAL data shifted between detection and execution), creates a new Anime per cluster, re-parents Media per-row via FK assignment (`m.anime_id = new_anime.id`), expires the source anime's `.media` collection (per-row child assignment doesn't refresh the parent's cached relationship collection), reclassifies both sides, runs post-split detection on source + each new anime, runs merge detection on the new anime IDs (a freshly-split franchise may match an existing parallel row)
  - **Rating safety property**: Media UUIDs are stable across re-parenting — any `Ratings.media_id` row stays attached to the same media; only the anime aggregation shifts

- **`split_candidate_backfiller.py`** — `detect_split_candidates_for_anime(db, anime, detected_by)` per-anime helper called from inside `relation_backfiller`'s SAVEPOINT loop AND from `merge_candidate_service.merge` post-reclassify; `backfill_split_candidates(db, anime_ids=None)` standalone pass for lifespan startup + admin re-trigger endpoint. The DAO's `upsert_pending` dedupes via cluster-signature so re-runs on unchanged data are no-ops

- **`anime_summary.py`** — `summarize_anime(anime, rating_count) -> MergeCandidateAnimeSummary` shared helper. Both `merge_candidate_service.list_pending` and `split_candidate_service.list_pending` render the same side-by-side anime card, so a future schema addition (e.g. `airing_status`) lands in one place

## Ratings + spoilers

- **`rating_service.py`** — rating CRUD + note search; triggers spoiler-visibility recompute on every change
- **`spoiler_service.py`** — frontier algorithm + precomputed visibility cache in `user_visible_media`
  - Anchor types include `Main` AND `AlternativeVersion` — retellings extend the story so each alt-version gates the next (rating Eva TV reveals Rebuild Movie 1 but not Movies 2-4)
  - **Recompute paths** (v0.14.7): per-(user, anime) on rating changes (`recompute_visibility_for_anime`); per-user whole-catalog on registration + startup backfill (`recompute_visibility_for_user`); and **per-anime-set across non-restricted users after catalog mutations** (`refresh_spoiler_cache_for_anime_ids`). The last replaced the whole-catalog `refresh_spoiler_cache_for_all_users` (deleted — no callers left): the frontier is per-anime and the cache keys on media_id, and media ids only move *between the named anime* on merge/split, so scoping is sufficient — O(users × changed) not O(users × all). Call sites pass the set they track (save → `new_anime_ids`; sweep → `probe_attached_anime_ids`; merge → survivor; split → source + new). The three workers share `_replace_user_visible_media`; the reads share `_fetch_media_lightweight`
  - **Restricted users are excluded** from the scoped recompute, both registration recompute paths, and the `backfill_spoiler_visibility` query (pinned to `spoiler=off`; never read the cache — the hide-mode read in `search.py` short-circuits when `spoiler_level != hide`). The pin has two altitudes: `user_settings_service.update_settings` guards the write path (drops `spoiler_level` for `RestrictedUser`), and the startup `user_seeder.purge_restricted_user_spoiler_cache` repairs data-at-rest — it resets any legacy non-off `spoiler_level` to off AND deletes their cache rows (a user demoted to `restricted_user` via DB edit while holding `hide` would otherwise read an empty cache and blank the catalogue; the write-guard can't fix rows that predate it)

## Export

- **`export_service.py`** — flat media-level export merging catalog + ratings + watchlist; respects user's `name_language` for localized title columns

## Backup service

- **`backup_service.py`** — pg_dump/pg_restore orchestration
  - Atomic `.partial` writes, sidecar `.meta.json`, content-hash dedupe
  - Retention (`apply_retention`) — three independent pools, slots counted over the *un-named* (auto-managed) subset of each so pins are kept ON TOP of a full rolling window:
    - **Archival (manual + cron)**: 14 most-recent + latest-per-Sunday for the last 8 distinct Sundays (`_latest_per_sunday` — keeps one dump per Sunday, fixing the old `[:8]` slice that let several same-Sunday dumps eat every weekly slot) + most-recent-known-good
    - **Pre-restore**: relevance-based, NOT archival. Pre-restores are rollback points, not weekly history — a pre-restore's `created_at` is the restore moment and could fall on a Sunday, so it must never occupy an archival Sunday/recent slot. Keeps the snapshot tied to the current state (`restored_to == current_filename`) + the `_PRE_RESTORE_RETENTION_COUNT=3` most-recent buffer; older ones age out
    - **Uploads**: separate `_UPLOAD_RETENTION_COUNT=5` most-recent pool (2 GiB each, kept off the archival window)
    - Every pool pins via shared `_evict`: `is_current` (prevents a stack of dedupe-hit re-confirms from evicting the pointed-at dump) and any **named** dump (the admin actively chose to keep it)
  - **Naming / pinning** (`set_backup_name` → `_set_meta_field`): a non-empty `name` on the sidecar pins the dump against auto-retention; clearing it (blank/None) unpins. `name` is the admin display name — distinct from the creation-time `label` that becomes a filename suffix; it never touches the filename. Exposed via `PATCH /admin/backups/{filename}`
    - **Why naming IS the pin (no separate pin toggle):** every pinned dump is forced to carry a human-readable reason, so the admin can never accumulate anonymous pins and later forget why a dump is protected. The name is the justification; an un-named dump is never pinned
  - **Restore link**: on a successful restore, `restore_backup` stamps `restored_to=<restored filename>` on the pre-restore snapshot's sidecar. `list_backups` derives `previous_state` on the current row (the pre-restore whose `restored_to` matches the pointer) — the "state before the current restore", surfaced in the card. Persisted `restored_to` survives pointer moves; derived `previous_state` mirrors `is_current`
    - **Dedup edge case (intentional):** `create_backup(pre_restore)` dedupes silently, so when the live DB already matched an existing dump, `pre_snapshot.filename` is that (often manual/cron) dump and `restored_to` lands on its sidecar. Correct — the matched dump genuinely IS the pre-restore state and is already retained — but (1) a manual/cron sidecar can then carry `restored_to` (only `previous_state` derivation reads it; harmless) and (2) it's protected by its own archival rules, not the pre-restore pool's `restored_to` pin, so the "Previous state" link can dangle if it ages out of the archival window. Left as-is because the link is truthful; suppressing it would lose a correct link. See the comment at the `_set_meta_field` call in `restore_backup`. **Self-reference sub-case:** when the matched dump IS the restore target itself (restoring a dump whose content already equals the live DB), `restored_to` lands on the current row's own sidecar; `list_backups` guards the `previous_state` derivation with `m.filename != current_filename` so the current row never advertises itself as its own previous state
  - **Integrity re-verification** (`reverify_backups`): the sidecar `integrity` is set once at create time (via `pg_restore --list`); the nightly backup job re-runs that same cheap check across all dumps and refreshes the flag, so on-disk corruption (truncation, bad sector, partial copy) doesn't keep listing as `ok`. `--list` is TOC-only (sub-second/dump, size-independent) — the full-decompress check stays at create time. Closes the v0.13.0-flagged "stale integrity" gap. Skips a dump deleted mid-loop (backup jobs don't bracket maintenance, so a concurrent admin delete is respected, not treated as corruption that fails the whole job)
  - `.current_db.json` pointer tracks which dump matches the live DB:
    - Set by `restore_backup` (→ restored dump) and by every successful `create_backup` regardless of source — manual / cron / pre_restore, whether unique or dedupe hit
    - Uploads NEVER move the pointer (`save_uploaded_backup` only stamps `is_current` when the new filename equals the unchanged pointer) — uploaded bytes are external, can't verify they match live
    - Deleting the pointed dump clears the pointer
  - All write paths serialized via module-level `asyncio.Lock` (single-worker assumption) — including `_set_meta_field`'s read-modify-write
  - `get_backup_path` is the single filename chokepoint (delete / restore / rename / reverify) — `_FILENAME_PATTERN` is the path-traversal guard (no separators, no `..`, so the constructed path can't escape the backup dir). CodeQL flags the downstream sidecar file ops as `py/path-injection` because it doesn't model the regex as a sanitizer; these are dismissed as false positives. A `resolve()`/`is_relative_to()` containment check was tried to satisfy CodeQL and reverted — CodeQL doesn't credit it either and it only added noise (2 extra alerts on its own lines)
  - Restore flips maintenance flag → other requests 503; backup creation does NOT (MVCC-snapshot read-only)
  - Subprocess password via `PGPASSWORD`, never on the CLI
  - Deeper design notes: [compound-docs/2026-04-19-v0.13.0-deployment.md](../../../compound-docs/2026-04-19-v0.13.0-deployment.md)
