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
- **TERMINAL state semantics (v0.14.3 change):** Nodes arrived via identity-breaking edges (`side_story`/`spin-off`/`parent_story`/`other`/`summary`/`full_story`) are TERMINAL — the BFS captures their outgoing edges (so split-detection can see e.g. Vigilante S1's sequel chain leaking out of BNHA's row) but does NOT recurse from them. The for-loop in `search_title` skips queuing TERMINAL targets via `if current_status is TERMINAL: continue`. Pre-v0.14.3 TERMINAL nodes had empty sidecars (`edges=[]`); post-v0.14.3 they carry their MAL relations like WALK nodes

## job_worker.py

Single asyncio FIFO worker draining the `jobs` table.

- Claims jobs via `with_for_update(skip_locked=True)`
- `wakeup` Event for sub-second pickup with a 60s wall-clock fallback (shortens to 2s while `is_maintenance_active()` — restore lifts the gate without calling `notify()`, so the idle poll has to catch the transition itself)
- Dispatcher table maps `JobKind → handler` (registered from `main.py` lifespan)
- Failure handling:
  - Stamps `result_summary.retryable = not isinstance(failure, PermanentPhsarError)` so the bell knows whether to show a retry button
  - Stamps `result_summary.error_category` via `_classify_error`:
    - `upstream_outage` — httpx 5xx + TimeoutException + NetworkError + `TransientUpstreamError` (MAL returning 200 with empty data on a known mal_id)
    - `backup_disk_full` — `BackupDiskSpaceError`
    - `backup_corrupt` — `BackupIntegrityError` (pg_dump output that fails `pg_restore --list` integrity check)
  - The bell renders friendly text instead of raw error strings; uncategorized errors fall through to the raw `error_message`, which is already friendly for custom domain errors
- Session management: sequential per-job sessions (claim-tx then work-tx in fresh sessions) avoid asyncpg pool deadlocks under nested-savepoint patterns
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
- **`update_sweep`**: tier-selects due anime via `AnimeDAO.select_due_for_sweep`, then per anime:
  - **Step 1** — refreshes child media via `JikanScraper.refresh_anime` (`/anime/{id}/full`), diffs volatile fields (`score`, `scored_by`, `episodes`, `airing_status`, `aired_to`) via `_apply_media_diff`, updates `MediaFreshness`, and rewrites `MediaRelationEdges` from the bundled `relations` block (steady-state refresh so MAL additions and bridge-edge restoration for pre-v0.14.1 rows flow in nightly; not counted as `anime_changed` for stable-counter purposes — structural metadata, not volatile fields)
  - **Step 2** (only tier 3 + tier 4 — `not currently_airing AND stable_check_count >= 3`) — probes each Main media's relations via `JikanScraper.search_title(seed_mal_id=...)`, attaches discovered media via `save_service.attach_search_result_to_anime`, advances `AnimeFreshness`
  - Two commits per anime + per-anime try/except:
    - Step 1 always commits durably (crash mid-sweep preserves field-diff work; single bad MAL response fails only that anime)
    - Step 2 only commits on probe success — failure leaves `AnimeFreshness` untouched so the tier query re-selects
  - Per-Main-seed BFS (each main gets its own `visited_ids`) lets the probe reach disjoint sub-graphs — walking from BNHA's main alone wouldn't surface Vigilante S2 because Vigilante S1 is a side-story and BFS stops expanding side-stories once a main is found
- Score stability tracking:
  - `_weighted_score(score, scored_by) = score * log10(scored_by + 1)` — same formula used for search ranking
  - Only counts as stability-resetting when `abs(new − old) >= _SCORE_STABILITY_THRESHOLD = 0.05`
    - Why: without this, a single new vote per night on a million-vote anime resets the counter forever
  - None↔value transitions bypass the threshold (first votes coming in is structural)
  - New values are written through regardless; the threshold gates only the stability *signal*
  - Score/scored_by writes gated on `payload["scored_by"]` being truthy — MAL returns scored_by as None or > 0 (never literally 0), and `extract_information` coerces None → 0 for the not-null column, so a 0 during refresh means the field was omitted; clobbering a populated count would be silent data loss
- Stability counter: resets to 0 when any media is currently airing or any field changed (above threshold), else `min(prev + 1, 99)`
- Coalesced `refresh_spoiler_cache_for_all_users` fires once at sweep end if any new media landed — the probe path uses `attach_search_result_to_anime` (never recomputes) instead of `save_search_results` (always does), so a 200-anime sweep with 50 new media triggers one cache recompute instead of 50
- **`seasonal_sweep`**: paginates `JikanScraper.fetch_current_season` (`/seasons/now`)
  - Dedupes against `Anime.mal_id ∪ Media.mal_id ∪ MediaUnwanted.mal_id` (plus per-run dedupe so MAL's cross-page duplicates don't double-enqueue)
  - Bulk-inserts one system `user_scrape` child per new mal_id with `requested_by_user_id=null` (system jobs skip per-user cap)
  - Bulk-insert instead of per-row commit because the enqueue loop does no MAL I/O — crash-safety argument doesn't apply, shorter maintenance window matters more

## backup_dispatcher.py

Handler for the `backup` JobKind.

- Wraps `backup_service.create_backup(source, label)`
- Progress stages: `Dumping` → `Applying retention` → `Done`
- Stamps `result_summary = {filename, size_bytes, integrity, source, deduped_against}` for the bell to render
- Catches `DuplicateBackupError` → success outcome with `deduped_against` populated (softer "no new data" line)
- `apply_retention()` runs after every job — manual and cron share the same 14-recent + 8-Sunday + 1-known-good pool
- **No maintenance bracket**: `pg_dump` runs on an MVCC snapshot, user writes are safe
- `BackupDiskSpaceError` / `BackupIntegrityError` surface via `_classify_error` as `backup_disk_full` / `backup_corrupt` with friendly bell copy; both stay `retryable=True`

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
- **Third-pass split detection runs alongside classification** (v0.14.3): `find_disjoint_franchises(nodes, edges, anchor)` finds substance-passing media outside the anchor's main+alt chain that form their own connected sequel chain. Result rides on `SearchResultDB.disjoint_franchises`; `save_service` upserts a `SplitCandidate` row when non-empty. See [compound-docs/2026-05-18-v0.14.3-split-candidates.md](../../../compound-docs/2026-05-18-v0.14.3-split-candidates.md)

## Vector + search

- **`vector_embedding_service.py`** — sentence-transformers embeddings
- **`media_search_service.py`** / **`anime_search_service.py`** — filtered DB search
  - Anime variant uses a two-phase query (GROUP BY + HAVING for filter/order, then detail fetch) with majority-genre logic
  - **Anime-view filters mirror the card's derivation in `_compute_anime_aggregates`**, not per-media WHERE: `age_rating` filters against `MAX(age_rating_numeric)`, `airing_status` against the priority-collapsed value (Currently → Finished → Not yet aired). Otherwise an anime with one Finished side-story would surface under the "Finished" filter despite the card showing "Currently Airing"
- **`filter_service.py`** — filter option values; view-type-aware for anime vs media ranges

## Auth / settings / tokens

- **`auth_service.py`** — registration, authentication, token issuance, account deletion
- **`user_settings_service.py`** — user settings CRUD + default creation
- **`token_service.py`** — compressed JWT for shareable filter URLs
- **`admin_service.py`** — registration token list + delete

## Merge detection + reconciliation

- **`merge_detection_service.py`** — duplicate-anime detector
  - Three signals feed `merge_candidates`:
    - `title_studio` — SequenceMatcher ratio OR containment ≥ 0.85, gated by studio overlap
      - Containment additionally requires word-boundary on both sides of the match in the longer string AND a size floor of `MIN_CONTAINMENT_MATCH_CHARS=4` chars OR a full match where the shorter title is itself ≥ `MIN_FULL_MATCH_CHARS=3`
    - `title_desc` — weaker title match + description-embedding cosine ≥ 0.85
    - `relation_link` — BFS surfaced a non-crossover related media under a different anime
  - Detection runs at the end of `save_search_results` (new × existing AND new × new — the latter catches single-scrape duplicates without waiting for a restart); startup `backfill_merge_candidates` covers existing × existing, and admin can re-trigger it any time via the manual `POST /admin/merge-candidates/backfill` endpoint
  - `seen_pairs` pre-fetch short-circuits flagged or admin-resolved pairs before any similarity computation

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
  - Substance gate: TV/ONA needs `episodes>=8 AND duration_seconds>=900` (15min) — NULL episodes acceptable for currently-airing/long-running; Movie needs `duration_seconds>=1800` (30min); TVSpecial strict
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
  - Execute: builds (nodes, edges) from the cluster's media subset, verifies the classifier still picks `suggested_anchor_mal_id` (raises `SplitCandidateStaleError(409)` if MAL data shifted between detection and execution), creates a new Anime per cluster, bulk-UPDATEs Media to re-parent, expires the source anime's `.media` collection (the bulk UPDATE bypasses ORM tracking), reclassifies both sides, runs post-split detection on source + each new anime, runs merge detection on the new anime IDs (a freshly-split franchise may match an existing parallel row)
  - **Rating safety property**: Media UUIDs are stable across re-parenting — any `Ratings.media_id` row stays attached to the same media; only the anime aggregation shifts

- **`split_candidate_backfiller.py`** — `detect_split_candidates_for_anime(db, anime, detected_by)` per-anime helper called from inside `relation_backfiller`'s SAVEPOINT loop AND from `merge_candidate_service.merge` post-reclassify; `backfill_split_candidates(db, anime_ids=None)` standalone pass for lifespan startup + admin re-trigger endpoint. The DAO's `upsert_pending` dedupes via cluster-signature so re-runs on unchanged data are no-ops

- **`anime_summary.py`** — `summarize_anime(anime, rating_count) -> MergeCandidateAnimeSummary` shared helper. Both `merge_candidate_service.list_pending` and `split_candidate_service.list_pending` render the same side-by-side anime card, so a future schema addition (e.g. `airing_status`) lands in one place

## Ratings + spoilers

- **`rating_service.py`** — rating CRUD + note search; triggers spoiler-visibility recompute on every change
- **`spoiler_service.py`** — frontier algorithm + precomputed visibility cache in `user_visible_media`
  - Anchor types include `Main` AND `AlternativeVersion` — retellings extend the story so each alt-version gates the next (rating Eva TV reveals Rebuild Movie 1 but not Movies 2-4)
  - Recomputed per-anime on rating changes, per-user on registration, per-user after new scrapes via `save_service`

## Export

- **`export_service.py`** — flat media-level export merging catalog + ratings + watchlist; respects user's `name_language` for localized title columns

## Backup service

- **`backup_service.py`** — pg_dump/pg_restore orchestration
  - Atomic `.partial` writes, sidecar `.meta.json`, content-hash dedupe
  - Retention — two independent pools:
    - Manual + cron: 14 daily + 8 Sunday + most-recent-known-good
      - Pins the `is_current` dump regardless of age — prevents a stack of dedupe-hit re-confirms from pushing the pointed-at older dump out of the 14-recent window
    - Uploads: separate `_UPLOAD_RETENTION_COUNT=5` most-recent pool
      - Also pins `is_current` — ensures a restore-from-upload workflow can't evict the bytes the DB was just restored from
    - Pre-restore snapshots stay retention-exempt entirely — safety net for synchronous restore, admin cleans by hand
  - `.current_db.json` pointer tracks which dump matches the live DB:
    - Set by `restore_backup` (→ restored dump) and by every successful `create_backup` regardless of source — manual / cron / pre_restore, whether unique or dedupe hit
    - Uploads NEVER move the pointer (`save_uploaded_backup` only stamps `is_current` when the new filename equals the unchanged pointer) — uploaded bytes are external, can't verify they match live
    - Deleting the pointed dump clears the pointer
  - All write paths serialized via module-level `asyncio.Lock` (single-worker assumption)
  - Restore flips maintenance flag → other requests 503; backup creation does NOT (MVCC-snapshot read-only)
  - Subprocess password via `PGPASSWORD`, never on the CLI
  - Deeper design notes: [compound-docs/2026-04-19-v0.13.0-deployment.md](../../../compound-docs/2026-04-19-v0.13.0-deployment.md)
