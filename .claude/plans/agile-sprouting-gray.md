# Phsar Roadmap — Feature Design & Planning

This document captures design decisions from the feature brainstorming session.
Once all features are discussed, this becomes the basis for GitHub issues and milestones.

---

## Feature 1: Ratings System

### DB Design

**Rating table** (per user, per media — extends existing model):

| Field | Type | Required | Notes |
|---|---|---|---|
| `rating` | Float 0-10 | yes | Two decimal precision in DB, UI step controlled by user settings |
| `dropped` | Boolean | yes | default False, explicit intent flag |
| `episodes_watched` | Integer | no | Auto-filled on "completed" if total known; nullable for unknown ep counts; backfilled by data update pipeline |
| `note` | String | no | Anime-wide notes go on one media (first/last selected) |
| `pace` | Enum | no | slow / normal / fast |
| `animation_quality` | Enum | no | bad / normal / good / very_good |
| `has_3d_animation` | Enum | no | none / partial / full |
| `watched_format` | Enum | no | sub / dub / both |
| `fan_service` | Enum | no | none / rare / medium / heavy |
| `dialogue_quality` | Enum | no | flat / normal / deep |
| `character_depth` | Enum | no | flat / normal / complex |
| `ending` | Enum | no | open_cliffhanger / not_satisfying / satisfying / great |
| `story_quality` | Enum | no | weak / average / good / outstanding |
| `originality` | Enum | no | conventional / unique / experimental |

**RatingSearch table** (new, mirrors MediaSearch pattern):
- `rating_id` (FK)
- `note_embedding` (Vector 384-dim) — generated when note is saved/updated

### Key Decisions
- Ratings always live at media level — no anime-level rating table
- "Rate whole anime" = UI/service convenience: select multiple media, write one Rating row per media with same score
- Note attached to first/last selected media when bulk-rating
- `dropped` kept as explicit boolean (not derived from episodes_watched vs total) because media.episodes can be NULL, can change, and intent matters
- `episodes_watched` nullable — data update pipeline backfills when episode counts become available
- All attributes are scales (not positive-only flags) for richer filtering and analysis
- Attributes are personal per-user opinions, but designed so cross-user aggregation works later
- Users only see their own ratings
- Rating something on watchlist → pop-up asks if it should be removed
- Ratings and watchlist are independent (all four combinations valid)

### Future Features
- "Give it a second chance" browsing section (dropped anime) — computed from ratings data
- "I break up before it breaks me" section (dropped bad anime) — computed from ratings data
- "Love it or hate it" recommendations — derived from MAL vote distributions + user ratings

### Achievements System (v0.18.0+)

**Achievement table** (definitions):

| Field | Type | Notes |
|---|---|---|
| `id` | PK | |
| `name` | String | internal identifier |
| `title` | String | funny display title for user profile (e.g. "Truck-kun Tamer", "Isekai Veteran") |
| `description` | String | how to unlock |
| `rarity` | Enum | e.g. common / uncommon / rare / epic / legendary |

**UserAchievement table** (junction):

| Field | Type | Notes |
|---|---|---|
| `user_id` | FK → users.id | |
| `achievement_id` | FK → achievement.id | |
| `unlocked_at` | DateTime | when achieved |

**Behavior:**
- After each rating, a service checks if new achievements are triggered
- Milestones: 1, 5, 10, 50, 100, 150, 200... anime watched / time watched / all MAL genres covered
- Genre titles: funny titles based on most-watched genre
- User profile shows rarest 1-3 titles from their unlocked achievements
- Achievement overview page on user profile (all achievements, locked and unlocked)
- Private — not visible to other users

---

## Feature 2: Anime-Level Aggregation & Pages

### Anime-Level Search (new default)

**New endpoint:** `GET /search/anime` — groups media by parent anime, returns aggregated results.

**Aggregation rules:**

| Field | Aggregation |
|---|---|
| Score | Average MAL score across all media |
| Total watch time | Sum across all media |
| Episodes | Sum across all media |
| Vector search (description) | Average cosine distance across all media of an anime — consistently relevant anime ranks higher than single lucky match |
| Vector search (title) | Match against anime's own title/names directly |

**Filter behavior at anime level:**

| Filter | Logic |
|---|---|
| Genre | Strict majority (>50% of media must have genre). 1/1=yes, 1/2=no, 2/3=yes, 2/4=no |
| Studio | Any (if any media has the studio, anime matches) |
| Season | Any (match if any media aired in that season) |
| Airing status | Can have multiple statuses simultaneously. "Currently Airing" if any media is currently airing. "Not yet aired" if any media is not yet aired. "Finished Airing" only if all media are finished. An anime can be both "Currently Airing" AND "Not yet aired" (e.g., season 3 airing now + season 4 announced). Filtering: anime matches if it has ANY of the selected statuses. |
| Media type, relation type | Any |
| Age rating | Max across all media (e.g., if one OVA is R+ but rest is PG-13, anime shows R+ so PG-13 filter excludes it) |
| Range filters (score, episodes, watch time, etc.) | Applied against aggregated values (avg score, sum episodes, sum watch time) |

**Search toggle UX:**
- Default view: anime-level search
- Separate toggle (not in filter panel — it's a view change, not a filter)
- Toggle switches between anime and media result views

### Anime Detail Page (`/anime?uuid=...`)

- Anime metadata: title, names, cover image (from anime table), description, age rating, genres, studios, seasons, airing status, total episodes, total watch time, avg score
- List of all media (clickable → media detail page)
- User's ratings summary for this anime (if any exist)
- "Rate all" action: select multiple media, apply same score in bulk
- Watchlist actions: add all media to watchlist / remove all from watchlist / select specific media to add

### Media Detail Page (`/media?uuid=...`)

- Full media info (expanded version of MediaInfo card)
- Rating UI: popup/modal for creating/editing a rating
- Link back to parent anime page
- User's existing rating displayed (if exists)
- Watchlist action: add/remove this media from watchlist

### Key Decisions
- Vector search results don't surface which media matched — feels like browsing anime, not media
- Anime cover shown on anime page is from the anime table (not media covers)
- Media-level search stays available via toggle for power users

---

## Feature 3: User Settings & Profile

### DB Design

**UserSettings table** (one-to-one with User, separate from User to keep static/dynamic apart):

| Field | Type | Default | Notes |
|---|---|---|---|
| `user_id` | FK → users.id | required | unique, one-to-one |
| `theme` | Enum | default | Theme key: default / red / blue / green — controls app colors + hero pic |
| `name_language` | Enum | english | english / japanese / romaji |
| `default_search_view` | Enum | anime | anime / media |
| `rating_step` | Enum | 0.5 | 0.5 / 0.25 / 0.1 / 0.01 |
| `spoiler_protection` | Boolean | false | Hides descriptions and covers of unrated media. Default set during get-started onboarding. |

### Theme System
- 4 themes: default (purple), red (crimson), blue (ocean), green (forest)
- Each theme sets: `--primary`, `--ring`, gradient colors via `.theme-*` CSS class on `<html>`
- `@property` + `var()` indirection in `@theme inline` forces Tailwind to emit dynamic `var()` utilities
- Character pic per theme displayed as hero banner on home page (InfoDiashow)
- Centralized config in `lib/themes.ts` — single source of truth for all theme data
- Per-theme chart color palettes avoid hue clashes (e.g., red theme swaps static red for teal)
- FOUC prevention via inline localStorage script in `app.html`

### Spoiler Protection Behavior

**Scope:** Media-level only. Anime search cards and anime-level descriptions are always safe (cover is poster art, description is from first main media).

**Three levels:**
- `off` — No protection, everything visible
- `blur` — Blur covers + descriptions of media beyond the spoiler frontier. Per-item click-to-reveal.
- `hide` — In media search: backend filters out media beyond the frontier (correct pagination via `WHERE media.id IN (...)`). On detail pages: falls back to blur behavior (user explicitly navigated there).

**Spoiler Frontier Algorithm** (per anime, media sorted chronologically by `season_year → season_name → mal_id`):
1. Extract **anchor** media in chronological order. Anchors are `relation_type == 'main'` OR `relation_type == 'alternative_version'` (refined in v0.14.1: retellings extend the story, so each alt-version gates the next — rating Eva TV reveals Rebuild Movie 1 but not Movies 2-4)
2. If no ratings exist: first anchor media is visible (or first media if no anchor exists), everything else is protected
3. If ratings exist: find the last rated anchor → the next unrated anchor after it is the **frontier**
4. All media chronologically up to and including the frontier are visible (including side stories, summaries, ONAs between rated anchors and frontier)
5. All media after the frontier are protected

**Example:**
```
S1 (main, rated)      → visible
S2 (main, rated)      → visible
ONA (side_story)      → visible (before frontier)
Summary               → visible (before frontier)
S3 (main, NOT rated)  → visible ← frontier (next main to watch)
OVA (side_story)      → BLUR/HIDE (after frontier)
S4 (main)             → BLUR/HIDE
S5 (main)             → BLUR/HIDE
```

**Implementation:** `GET /ratings/spoiler-visibility` endpoint computes visible media UUIDs. Frontend stores as `Set`. Detail pages compute frontier locally for fresher data. Reusable `SpoilerGuard.svelte` component wraps covers/descriptions.

### Key Decisions
- No profile visibility setting — users are always separated
- Cross-user data only used in background for recommendations and aggregate browsing ("others rated 8.5+")
- No NSFW filter for now (can be added later as a setting)
- No notification setting yet (deferred until content pipeline feature)
- Theme selection controls both app colors and hero character pic (unified setting, not separate)
- Settings created with defaults when user account is created

### Implementation Note (from v0.10.0)
- When `rating_step` changes, existing ratings may have precision that doesn't match the new step (e.g. a score of 7.25 saved with step 0.25, then user switches to step 0.5). Decide on display behavior: show the stored value as-is (preserving precision), or round to the current step for display consistency. The score input already uses `clampAndSnapScore(val, step)` which will snap on edit, but read-only display needs a policy.

---

## Feature 4: Content Pipeline (Add Anime, Updates, Seasonal Scraping)

### User-Triggered "Add Anime"

**Who**: Any user except `restricted_user`.

**Flow:**
1. User searches MAL via existing `/search/mal` → selects anime to add
2. Server creates a job entry in DB, starts background processing
3. Scraper BFS traverses MAL relations, fetching media details and generating embeddings
4. User polls for progress via `GET /jobs/{id}` or sees status in navbar bell/notification area

**Rate limiting:**
- Max 4 concurrent scrape jobs per user
- Job table tracks status: `queued → running → completed → failed`
- Race guard: `SELECT ... FOR UPDATE` on user's running jobs before allowing new one
- If user has 4 running jobs, new request is rejected until one completes

**Progress tracking (stage-based, honest about growing totals):**
- "Discovering related media... (found 12 so far)"
- "Fetching details: 3/12 discovered..."
- "Fetching details: 12/23 discovered..." (denominator grows as BFS finds more)
- "Generating embeddings: 5/23"
- "Done — added [Anime X] with 23 media entries"

**Job table:**

| Field | Type | Notes |
|---|---|---|
| `id` | PK | |
| `user_id` | FK → users.id | who triggered it |
| `status` | Enum | queued / running / completed / failed |
| `stage` | String | current stage description |
| `media_discovered` | Integer | total found so far (grows during BFS) |
| `media_processed` | Integer | fetched/embedded so far |
| `anime_title` | String | for display |
| `result_summary` | String | nullable, filled on completion |
| `error_message` | String | nullable, filled on failure |
| `created_at` | DateTime | |
| `completed_at` | DateTime | nullable |

### Deduplication ✓ shipped (commit 6 of v0.14.0, closes #29)

**Three detectors feed the `merge_candidates` table:**
1. **`title_studio`** — `max(SequenceMatcher.ratio, longest_match_size / min(len)) ≥ 0.85`, gated by studio overlap. The containment branch catches `"X" ⊂ "X: Subtitle"` cases that pure ratio under-counts.
2. **`title_desc`** — title score ≥ 0.5 AND description-embedding cosine ≥ 0.85, also gated by studio overlap. Catches Dr. Stone / Dr. Stone: New World where the subtitle pushes title alone below the rule-1 threshold but the synopses lock onto the same characters/world.
3. **`relation_link`** — `media_relation_edges` sidecar links a media to media owned by a different anime via a strong-link MAL relation (`sequel`, `prequel`, `alternative_version` — the same `ALT_CHAIN_EDGES` set the relation classifier uses to build a chain). Strongest signal (MAL itself asserting the connection); no title or studio gate. The sidecar is the **single source of truth** — save, update_sweep, and backfill all converge through `find_cross_anime_relation_pairs` / `MergeCandidateDAO.get_cross_anime_relation_pairs` so the signal fires identically regardless of which job created the anime rows or when (the Evangelion-shape: NGE TV and Rebuild Movies as separate scrapes were missed by the original BFS-derived path).

**MAL-ID match remains:** `MalIdAlreadyExistsError` raised at save-time if a media's mal_id already exists; this is the hard pre-detector guarantee.

**Admin review only — no auto-merge, no Discord webhook.** Pending candidates surface in the admin panel's Merge Candidates card. Admin merges (re-parents B's media onto A, deletes B with cascade) or dismisses (status flip, row stays so re-detection skips it). Both decisions survive across restarts via the unique `(anime_a_id, anime_b_id)` constraint + `seen_pairs` pre-fetch in detection.

**BFS boundary rule (shipped):**
- Crossover relations no longer get traversed: `JikanScraper.search_title` records the crossover anime in the relation graph but skips its `fetch_relations` call. Naturally separates franchises like FATE into distinct anime entries.
- BFS persists every captured edge (filtered only for crossover / character / adaptation / alternative_setting at parse time) into the per-media `media_relation_edges` sidecar. The merge detector reads from that sidecar (see detector #3 above) — the BFS no longer needs to surface a per-graph cross-link signal of its own.

**Backfiller:** `merge_detection_service.backfill_merge_candidates` runs in app lifespan after `backfill_embeddings`. One-shot existing × existing pair sweep so duplicates that pre-date the detector get flagged on first restart after upgrade. Idempotent: pre-fetched seen-pairs short-circuits subsequent restarts.

**v0.14.1 extensions:**
- Detection now also runs at the end of `save_search_results` covering new × new (single-scrape duplicates surface without waiting for a restart). Save-time + startup-backfill together cover all three pair classes (new × new, new × existing, existing × existing).
- Admin can re-trigger the existing × existing backfill on demand via `POST /admin/merge-candidates/backfill` — primarily for the post-restore workflow (restore is synchronous, so the lifespan-startup backfill never sees the restored catalog).
- Each pending pair carries a **reclassification preview**: per-media diffs (`old_relation_type → new_relation_type`) that would land if A absorbed B, surfaced inline in the admin card so structural impact (substance-gate demotions, alt-version labels, anchor flips) is visible before clicking merge.
- Merge survivor flow runs `anime_relation_service.reclassify_anime` over the consolidated set — rewrites the 7 umbrella fields only on cross-field drift, regenerates the anime embedding only when title-affecting fields shifted.

### Maintenance Window ✓ shipped (commit 7a of v0.14.0)

Foundation for any destructive/long-running periodic job. Consumed by both the data-refresh sweep (7b) and the seasonal sweep (commit 8).

- **Sidecar tables** (`anime_freshness`, `media_freshness`) hold operational state outside the canonical catalog rows so sweep cadence can't leak into Pydantic schemas via `model_dump()`. Each row is born with a sidecar; the migration backfilled existing rows to the parent's `created_at`.
- **`core/maintenance.py`** module-level `_active` (already from v0.13.0 backup restore) gains `_scheduled_at`. The cron schedule endpoint sets `_scheduled_at` to a future timestamp; the worker brackets each sweep dispatch with `set_maintenance(True/False)` + `set_scheduled_at(None)` in try/finally so a crash can't leave the flag stuck.
- **`MaintenanceGateMiddleware`** (pure ASGI class) returns 503 `{maintenance: true}` for everything except `/`, `/health`, `/maintenance/status`, `/admin/jobs/schedule-sweep`, `/admin/jobs/schedule-seasonal`, `/admin/jobs/schedule-nightly`. Registered BEFORE `CORSMiddleware` so CORS ends up outermost — `app.add_middleware()` prepends, so registration order reverses the apparent stacking. Without that ordering, cross-origin 503s drop CORS headers and the browser blocks them.
- **`MaintenanceBanner`** sticky at the top alongside the navbar (single sticky container in `+layout.svelte`); renders a `Notice` card with a countdown when within 30 min, "in progress" while active. Subscribes to the auth token store + a `maintenanceRefresh` bump signal so it reacts in ms to login transitions and 503-with-maintenance responses, not just the 60s poll.

### Automated Updates (Periodic)

**Triggered via**: Coolify scheduled task (cron) calling `POST /admin/jobs/schedule-nightly?delay_minutes=20` — the combined daily entry that enqueues backup + `update_sweep` + (on Sundays UTC) `seasonal_sweep`. The three single-purpose endpoints (`schedule-sweep`, `schedule-seasonal`, `backups/auto`) remain for ad-hoc triggers. All four endpoints share `JOBS_CRON_TOKEN` and are allowlisted in the maintenance gate.

**Status:** ✓ shipped end-to-end. Data-refresh dispatcher + tier query landed in commit 7b; relations probe + coalesced spoiler recompute landed in commit 7c (closes #30).

**What 7b shipped (data refresh):**
- `update_sweep` dispatcher tier-selects due anime via a 4-tier OR query (LEFT JOIN against `anime_freshness`):
  - Tier 1: any media currently airing → always due
  - Tier 2: `stable_check_count < 3` → still stabilizing
  - Tier 3: last-checked > 7 days AND has a main media whose `aired_from` is within `SWEEP_RECENT_MAIN_YEARS = 5` years (refined from "any main media exists" so dormant main-only franchises don't ride weekly cycles)
  - Tier 4: last-checked > 180 days → long-tail safety net
- For each due anime: refreshes child media via `/anime/{id}/full`, diffs `score`/`scored_by`/`episodes`/`airing_status`/`aired_to`. **Per-anime commit + per-anime try/except** — a worker crash mid-sweep preserves earlier successes; a single bad MAL response fails *that* anime only.
- Score and scored_by are bundled through `_weighted_score(score, scored_by) = score * log10(scored_by + 1)` and only count as stability-resetting when `abs(new − old) >= 0.05`. Without this, every popular anime (One Piece, BNHA, Naruto:Shippuuden) would never stabilize because daily vote drift moved `scored_by`. New values are written through to the DB regardless; the threshold gates only the stability *signal*.
- Episodes-was-NULL → known: `logger.info(...)` only. Per-user `episodes_watched` is NOT auto-set because we don't know what the user actually watched.

**What 7c shipped (relations probe + coalesced spoiler recompute):**
- Probe runs on **tier 3 + tier 4** (`not currently_airing AND stable_check_count >= 3`). Tier 4 was added on user feedback — long-tail franchises can announce sequels years post-finale, and the 6-month cadence is the right place to catch them. Tier 1 stays excluded (re-checked nightly anyway); tier 2 stays excluded (brand-new shows have no announcement to discover yet).
- **Per-Main-seed BFS** via `JikanScraper.search_title(seed_mal_id=...)`: one BFS per Main media on the parent anime, fresh `visited_ids` each pass. The mal_id-based seed bypasses the fuzzy `q=<title>` top-3 lookup user_scrape uses — early prototype hit that path and pulled Bocchi the Rock! into a Vigilante S2 lookup because MAL's fuzzy search ranked an unrelated "2nd Season" token highly. Per-main isolation lets the probe reach disjoint sub-graphs (e.g., the Vigilante branch off BNHA, where Vigilante S1 is a side-story under BNHA and `search_title`'s BFS would otherwise stop expanding once BNHA's main is found).
- New `save_service.attach_search_result_to_anime` saves discovered media under the existing parent anime — no new Anime row, no fuzzy main-story-required check that would drop orphan side-stories like a freshly-announced TVSpecial.
- **Two commits per anime**: step 1 (field-diff + MediaFreshness) always durable; step 2 (probe + AnimeFreshness) only commits on probe success. A probe failure leaves AnimeFreshness untouched so the next sweep re-selects the anime via tier 3/4 — the field-diff work isn't lost.
- The dispatcher calls `refresh_spoiler_cache_for_all_users` once at the end if any new media landed — coalesced because the probe path saves through `save_service.attach_search_result_to_anime` (which never recomputes) instead of `save_search_results` (which always does), so a 200-anime sweep with 50 new media triggers exactly one cache recompute instead of 50.
- **Bonus fix surfaced by end-to-end testing:** `JikanScraper.search_title` was inserting `media_type=None` anime into `media_unwanted` as "Unknown" even when `airing_status="Not yet aired"` — just-announced sequels got permanently blacklisted before MAL had classified them, and never got picked up once they aired. Now skipped silently; `media_unwanted` only catches true MAL anomalies. Alembic migration `2f1a8e3c4d5b` clears the existing Unknown backlog so previously-trapped anime can be rediscovered by the next sweep.

**Frequency**: Coolify cron daily. Tier query LIMITs at `JOBS_SWEEP_MAX_PER_RUN=200` so a fully-saturated catalog still completes within a maintenance window.

**What 7d shipped (post-review hardening):** Seven commits stacked on the v0.14.0-update-sweep branch addressing reviewer findings before PR merge.

- **Score-write guard (`2b80641`):** `_apply_media_diff` was treating `payload["scored_by"] or 0` as authoritative and unconditionally writing it back. MAL's scored_by is None or > 0 (never literally 0), and `extract_information` coerces None → 0 to satisfy the not-null insert column — so a 0 during a refresh meant the field was omitted, and we'd silently overwrite a populated 5M-vote count with 0 (also tripping the structural-reset branch and dragging the row back to tier-1 cadence). Skip the score write when `scored_by` is falsy. Mirrors the existing `airing_status` guard.
- **Unwanted-media flush propagation (`2b80641`):** the probe's `create_unwanted_media` call was wrapped in a bare `except` that swallowed flush() failures. An IntegrityError or connection drop would leave the session in `PendingRollbackError` and the next `attach_search_result_to_anime` would surface as a confusing cascade. Drop the inner try/except — let the failure propagate to the outer probe handler which already does the right thing.
- **Drop dead `defer_spoiler_recompute` parameter (`60c6e7a`):** never invoked with `True`; CLAUDE.md described a fictional mechanism. Removed.
- **Schedule-sweep clobber + delay bound (`91fa580`):** the worker's `finally` unconditionally cleared `_scheduled_at`, so a Coolify cron retry that landed mid-sweep (allowlisted endpoint) would write the next window's timestamp and have it wiped on exit. Now we only clear if the timestamp is in the past — future ones belong to a different window. Plus `delay_minutes` switched to `Query(20, ge=0, le=1440)` for defense-in-depth.
- **Jikan rate limiter (`e9ce488`):** class-level `asyncio.Lock` + monotonic-time gate spaces request *starts* at ~2.85 req/s (under MAL's 3 req/s). Without it, a 200-anime sweep would burst hundreds of requests as fast as TCP allows; tenacity caught the 429s but didn't avoid them.
- **Sweep-selection indexes (`e9ce488`):** new migration `8d4f2a1c9e7b` adds `ix_anime_freshness_last_checked_at` (the ORDER BY), `ix_media_airing_now` (partial on `media(anime_id) WHERE airing_status = 'Currently Airing'`), and `ix_media_main_aired_from` (composite for the recent-main EXISTS as index-only). Resolves the open follow-up flagged in the v0.14.0 compound doc.
- **Spoiler recompute hoist (`2eba9b4`):** `refresh_spoiler_cache_for_all_users` was O(users × media) — the catalog read ran inside the per-user loop. Hoist the snapshot once and pass it through to a new `_recompute_user_against_catalog` worker; `recompute_visibility_for_user` (seeders) builds a single-user snapshot and delegates to the same worker, so the delete + bulk-insert tail isn't duplicated.
- **`MaintenanceGateMiddleware` extracted (`951873d`):** moved out of `main.py` into its own `core/maintenance_middleware.py` module. The middleware's invariant comments (pure-ASGI choice + CORS-must-wrap-it ordering) travel with the class.
- **Sweep loop refactor + test harness (`096be4e`):** extract `_try_step1_refresh` / `_try_step2_probe` so the loop reads as straight orchestration instead of two near-identical try/except blocks. Add a `_run_dispatcher_harness` test helper bundling the four monkeypatches the dispatcher integration tests duplicated 8+ times.

### Seasonal Scraping

**Triggered via**: Coolify scheduled task (weekly).

**What it does:**
- Scrapes all anime from the current MAL season
- Adds new anime not already in DB
- Deduplication rules apply (MAL ID check, title similarity flagging)
- Starts from the season the feature launches, going forward only

---

## Feature 5: Watchlist

### DB Design (already exists, no changes needed)

**Watchlist table** (per user, per media):

| Field | Type | Notes |
|---|---|---|
| `user_id` | FK → users.id | |
| `media_id` | FK → media.id | |
| `note` | String | optional |
| `priority` | Integer 1-3 | 1=low, 3=high |

**Tag table** (per user):

| Field | Type | Notes |
|---|---|---|
| `user_id` | FK → users.id | |
| `name` | String | free-text, e.g. "Overpowered MC", "recommendation from Lewis", "Good for lunch" |
| `color` | String | hex color |

**WatchlistTag** junction table links tags to watchlist entries.

### Key Design
- Tags and priority are **independent dimensions** — can be combined freely but not nested
- Storage at media level, UI groups by parent anime
- Watchlist icons visible in search results (already added indicator + quick-add button)
- Rating an anime on watchlist → popup asks if it should be removed

### Watchlist Page UI
- Standard view: covers + titles with filtering by tags, priority
- Link to browse page for deeper exploration

---

## Feature 5b: Browse Page

### Concept
Separate page/route — the "deep dive" version of home page sections.

**Toggle**: "All anime in DB" vs "Only my watchlist"

### Sections (horizontal scrollable card rows — Crunchyroll-style, same as home page)
- **Recommendation algo** (top of page) — dropdown/selector to choose algorithm. Designed for experimentation — swap in new algos over time, users can try different ones. Could also be a user setting.
- **Give it a second chance** — dropped anime (from ratings data)
- **Continue watching** — anime on watchlist with partial ratings (e.g. watched S1, S2 waiting)
- **Genre-based sections** — "Vampire Lovers", "Isekai Adventures", etc. (derived from user's top-rated genres)
- **Unexplored territory** — cluster-based discovery, anime outside user's usual selection
- **Others also liked** — cross-user signal (users who rated similar anime highly)
- **Rising on MAL** — high `log(scored_by) * score` weighting

### Recommendation Algorithms (iterative, start simple)

**v1 (simple):**
- Weighted MAL score: `log(scored_by) * score`
- Top watchlist picks: prio 3, mix of old and new additions
- "Others also liked" based on overlapping high ratings

**v2+ (advanced, future):**
- User rating + actuality combo
- Pattern prediction (isekai → romance cooldown cycle detection)
- HDBSCAN clustering over description embeddings — find gaps in user's coverage
- Production company analysis over embeddings

### Key Decisions
- Algorithm selector (dropdown or user setting) keeps backend flexible for experimentation
- Advanced recommendation algos are separate work items — not blocking browse page v1
- Browse page and home page share section components but home is lightweight subset

---

## Feature 5c: Home Page

### Concept
Eye-catching landing page — light version of browse, serves new and returning users.

### Sections (keep existing placeholders, horizontal scrollable card rows — Crunchyroll-style)
- **Current season diashow** (existing) — rotate through new anime of the season
- **Recommended** (existing placeholder) — from selected algo
- **Lucky Find** (existing placeholder) — surprise/random picks
- **Upcoming** (existing placeholder) — upcoming anime releases

### UI Pattern
- Horizontal scrollable card rows (like Crunchyroll app) for all sections
- Same pattern used on browse page — lots of options in compact space
- Anime cover cards that scroll left/right

### Key Decisions
- Recommendation section uses same algo as browse page top section
- Home page sections reuse browse page components (lighter presentation)
- For logged-out / new users: show season diashow, popular, recently added (skip personalized sections)
- `RelatedMediaCarousel` (from v0.10.0) is a starting point — generalize it into a reusable horizontal card carousel component that accepts any card content (anime covers, media cards, recommendations) for both browse and home page sections

---

## Feature 6: Search & Browse Enhancements

### Approach: One Search Bar, Contextual Filters
- Reuse the same SearchBar component everywhere, with context-dependent filter options
- On `/search`: full filters + two new toggles: "in watchlist" / "already watched"
- On watchlist page: same search bar, pre-filtered to watchlist items, plus tag/priority filters
- On browse page: same search bar, collapsed by default (sections are main navigation)
- Avoids building multiple search components

### New Filters
- **In watchlist** (boolean toggle) — filter results to only anime on user's watchlist
- **Already watched** (boolean toggle) — filter to anime the user has rated
- These require joining against user's watchlist/ratings tables in the search query

### General Browsing
- Browse page (Feature 5b) covers this — sections + search bar with filters gives full browsing capability
- No separate "all anime" page needed if browse page has "all anime in DB" toggle

---

## Feature 7: User Data Export

### What
- User downloads their own data as flat media-level rows (one row per media with a rating or watchlist entry)
- No embeddings included
- Purpose: personal analysis of own ratings and watchlist data

### Format
- CSV or JSON (user chooses via query param)
- Endpoint: `GET /users/export?format=json|csv` (authenticated, user/admin only)
- Filename: `phsar_export_{username}_{YYYY_MM_DD}.json/csv`

### Contents per row
- **Anime/media catalog**: anime_title, (anime_name), title, (name), anime_mal_id, mal_id, type, relation, episodes, episode_duration_seconds, season, season_year, age_rating, mal_score, mal_scored_by
- **Rating data** (null if only watchlisted): rating, dropped, episodes_watched, rating_note, rated_at, rating_updated_at, + 11 attribute enums
- **Watchlist data** (null if only rated): watchlist_priority, watchlist_note, watchlist_tags, watchlist_added_at
- **Conditional name columns**: `anime_name` and `name` only included when user's `name_language` setting is not romaji and at least one resolved name differs from the romaji title

### Key Decisions
- Flat media-level structure (not separate ratings/watchlist sections) for analysis-ready data
- Includes MAL scores for correlation analysis, season/age_rating/duration for user analytics
- Name columns are conditional to avoid empty columns when user uses romaji

### Future
- Document the export schema (column definitions, conditional columns, format differences) on the getting-started page

---

## Feature 8: Database Backup & Restore

### Why
- Users will invest significant effort (200+ ratings) — data loss is unacceptable
- Need both automated snapshots and manual restore capability

### Approach: pg_dump + dual storage

**Server-side (automated):**
- Admin endpoint triggers `pg_dump` → compressed backup file
- Stored on server disk (or object storage if available)
- Coolify cron for scheduled backups (daily or weekly)
- Admin can download backup file or trigger restore via admin panel

**Local backup (safety net):**
- Admin can download dump file from admin panel to local machine
- Periodic manual download or scripted pull
- Last resort if server itself has issues

**Restore:**
- Admin endpoint for `pg_restore` from uploaded or server-stored backup
- Requires confirmation step (destructive operation)

### Key Decisions
- **Content-level dedupe, not raw-bytes.** `pg_dump -Fc` output is non-deterministic (embedded timestamps, `\restrict` tokens), so we hash `pg_restore -f -` output with per-run-variable lines stripped. Identical DB state → identical hash, so download→upload round-trips idempotent.
- **Per-source dedupe policy.** Manual raises `DuplicateBackupError` (admin gets explicit feedback); cron + pre_restore silently return the existing dump so schedulers and restore snapshots don't accumulate identical files.
- **"Current" badge follows DB state, not restore history.** `.current_db.json` pointer is set by restore, or by ANY successful manual/cron/pre_restore create (whether the dump is unique or a dedupe hit — pg_dump captured live state, so the resulting dump IS live). Uploads NEVER move the pointer — uploaded bytes are external (could be any historical or third-party dump) and we have no way to verify they match the live DB. Deleting the pointed dump clears the pointer. The frontend pins the Current row to the top of the "Newest first" sort so a post-restore older dump stays salient.
- **Backup creation is async via the jobs table (commits 10–12 of v0.14.0).** Admin clicks Create → POST returns 202 with `job_uuid` → bell shows a queued stub (synchronously seeded via the `optimisticJobs` store) → worker dumps in the background → bell tracks `Dumping` → `Verifying backups` → `Applying retention` → `Done` → BackupsCard auto-refreshes on the bell's `backupSaved` bump. Restore stays synchronous on purpose — it's meant to be blocking (drops schema, terminates sessions, flips maintenance).
- **Pre-restore snapshot is automatic.** Every restore first dumps the live DB (also subject to dedupe).
- **Three retention pools, named dumps pinned on top (v0.14.6).** `apply_retention` splits into (1) **archival** manual+cron — 14-recent + latest-per-Sunday for 8 distinct Sundays (`_latest_per_sunday`, fixing the old `[:8]` slice that let several same-Sunday dumps eat every weekly slot) + most-recent-known-good; (2) **pre-restore** — relevance-based, NOT archival (a pre-restore's `created_at` is the restore moment and could fall on a Sunday, so it must never occupy an archival slot): keeps the snapshot tied to the current state + the 3 most-recent buffer, older ones age out; (3) **uploads** — 5-recent cap. Each pool's window slots are counted over the *un-named* subset so a non-empty admin `name` PINS a dump on top of a full rolling window (else 14 pinned dumps would evict every fresh nightly backup). `is_current` is pinned everywhere.
- **Rename = pin (v0.14.6).** `PATCH /admin/backups/{filename}` sets/clears a sidecar `name`; non-empty pins against retention, blank unpins. Decoupled from the creation-time `label` (filename suffix) — `name` never touches the filename, so it allows spaces/case. Decision: no separate pin toggle; naming IS the pin (matches "named backups are not auto-deleted"). Rationale: forcing every pin to carry a name means a protected dump always records *why* it was kept — the admin can't accumulate anonymous pins and later forget the reason.
- **Nightly integrity re-verification (v0.14.6).** `reverify_backups` re-runs `pg_restore --list` across all dumps at the start of every backup job (before retention) and refreshes the sidecar `integrity`. Closes the v0.13.0 gap where the create-time flag was never re-checked and a bit-rotted dump kept listing `ok`. `--list` is TOC-only (sub-second/dump, size-independent), so it's cheap enough to run every night; the full-decompress check stays at create time. Ordered before retention so the "most recent known-good" pin can't crown a now-corrupt dump.
- **Restore link via sidecar + UI (v0.14.6).** A successful restore stamps the pre-restore snapshot's `restored_to=<restored dump>`; `list_backups` derives `previous_state` on the current row (the pre-restore whose `restored_to` matches the pointer). Chosen over encoding the link in the filename (filename is the identity used by pointer/restore/delete — fragile + length-limited). Surfaces as "Previous state saved as …" on the current row and "Snapshot of the state before restoring …" on the pre-restore.
- **Retention runs after every backup job, not cron-only.** Both manual and cron dispatcher paths end with `apply_retention()`. Without this, manual creates pile up indefinitely on installs where cron is disabled (empty `JOBS_CRON_TOKEN`) or rarely fires — the cron path was historically the only one wired to retention.
- **Single cron token + combined nightly endpoint (v0.14.0 late).** Originally three cron-authed endpoints with two bearer tokens (`BACKUP_CRON_TOKEN` for `/backups/auto`, `JOBS_CRON_TOKEN` for the two sweep schedulers). Consolidated to a single `JOBS_CRON_TOKEN` and added `POST /admin/jobs/schedule-nightly` that enqueues backup (immediate) + `update_sweep` (delayed) + Sunday-UTC-only `seasonal_sweep` (same delay). The weekday check lives in the endpoint so one Coolify scheduled task covers everything; the three single-purpose endpoints stay for ad-hoc triggers. Sunday-UTC is intentional — the existing seasonal cron already ran weekly Sunday, so piggybacking that day on the daily maintenance window keeps the user-visible banner pattern unchanged. Ordering between `update_sweep` and `seasonal_sweep` is FIFO-with-tie-on-not_before_at (worker picks one, runs it, then the other); the maintenance flag bounces sub-second between them which is acceptable for an admin-only system flow.
- **Maintenance mode during restore.** Process-wide in-memory flag; HTTP middleware 503s everything except `/` and `/health`, frontend bounces users to `/login?maintenance=1`. Single-worker assumption documented. Backup creation does NOT flip maintenance — `pg_dump` is read-only via MVCC, so user writes are safe during a dump window.
- **Password handling.** `PGPASSWORD` env var on the subprocess, never on the CLI.

---

## Feature 9: Statistics & Analytics

### Scope: High-level for now — endless ideas, will detail iteratively

### Standard Graphs
- Watch history over time
- Genre distribution (what genres user watches most)
- Score distribution (histogram of user's ratings)
- Watch time stats (total, by genre, by year)
- Dropped rate by genre/studio
- Rating attribute distributions (pace, animation quality, etc.)

### Advanced Analytics (later iterations)
- HDBSCAN clustering over description embeddings — 2D map of all anime, highlight unexplored areas
- Production company analysis over embeddings
- Monthly pre-computed reports (if real-time reprocessing is too expensive)
- Pattern detection (genre rotation habits, seasonal preferences)

### Key Decisions
- Start with standard graphs, add advanced analytics incrementally
- May need pre-computed/cached results for expensive operations (clustering, embedding analysis)
- Statistics page is its own route, user-specific data only

---

## Feature 10: Get-Started Page

### Concept
- Mandatory onboarding flow — forced on first login, user must complete it before accessing the app
- Serves as tutorial + initial settings configuration
- User sets: theme, name language, rating step, spoiler protection, default search view
- Brief walkthrough of key features (search, ratings, watchlist)

---

## Feature 11: Home Page Design

*Visual design and layout — separate from functional home page sections (Feature 5c)*

---

## Milestone & Issue Organization

### Version Roadmap

| Version | Scope | Notes |
|---|---|---|
| **v0.9.0** | ✓ Ratings backend + rating enums/migration + DAO optimization | Pure backend. Lock DB schema for ratings. Clean up DAO query patterns (single-queries) while touching this layer. |
| **v0.10.0** | ✓ Media detail page + rating UI | First visible ratings. Rating modal/popup. Media page with full info + link to anime (anime page not yet built). |
| **v0.11.0** | ✓ Anime-level search + anime detail page | Aggregated search as default. Anime↔media navigation loop complete. View toggle (anime/media). View-type-aware filter options. |
| **v0.12.0** | ✓ User settings + user page UI + data export + admin + account deletion | Settings table, theme system (app color + hero pic via `@property`/`var()` indirection), rating step, name language, spoiler protection. Flat media-level data export (ratings + watchlist + catalog info per media, respects name_language, dated filename). Token expiry dialog. Registration page. Guest account. Admin page for registration token management. Account deletion with glass crack UX, password confirmation, DB cascade (SET NULL on registration tokens). |
| **v0.13.0** | ✓ Deployment (Coolify) + switch to bun + CI image builds + DB backup/restore | Deployment-ready: Coolify config for db/frontend/backend services. Switch frontend from npm to bun. Build images in GitHub Actions → push to ghcr.io → Coolify pulls (VM too small for on-host bun/SvelteKit build). pg_dump backup system (automated + local download). Prerequisite for content pipeline cron jobs. |
| **v0.14.0** | ✓ Content pipeline (scraper jobs, dedup, updates, seasonal) | User-triggered scraping with job tracking. Automated daily/weekly updates. Seasonal scraping. Dedup + admin merge candidates. Maintenance mode + sticky banner. Combined nightly cron endpoint (backup + update_sweep + Sunday seasonal_sweep). |
| **v0.14.1** | ✓ Search & data fixes (relation classifier redesign) | Two-pass relation classifier (BFS captures edges; pure-function classifier picks anchor + classifies). `AlternativeVersion` type for retellings (Eva Rebuild). `MediaRelationEdges` sidecar persists edges so bridge edges activate on later merges. Substance gate demotes weak Mains. Merge survivor reclassification + per-pair preview. Title-search ranking (substring + pg_trgm bonus). Season-suffix stripping on umbrella names. |
| **v0.14.2** | ✓ Split candidates + sweep & scrape stability | Third detection pass: admin-reviewed split candidates for disjoint franchise chains under one anime row (media UUIDs preserved so ratings stay attached). Strict WALK/TERMINAL BFS prevents cross-franchise contamination. Sweep refreshes non-volatile metadata + genre/studio drift. Dev DB helper scripts under `phsar/scripts/`. CLAUDE.md split per-tree. |
| **v0.14.3** | ✓ Admin page rework + detail-page UX | `/admin` restructured around a `?tab=` switcher (Overview / Jobs Log / Curation). Overview stats + paginated Jobs Log with filters and seasonal-sweep child clustering. Pending merge/split candidates surface in the admin bell. Related-media carousel chronological + "you are here" marker. "Back to library" nav origin. 50/day `user_scrape` cap. |
| **v0.14.4** | ✓ Merge-candidate detector fix (sidecar-as-truth) | `media_relation_edges` becomes the single source of truth for the `relation_link` merge signal; all three trigger sites (save / sweep / backfill) converge through one DAO query. Allowlist tightened to strong-link relations. Backfill runs the relation_link sweep so Evangelion-shape pairs (NGE TV ↔ Rebuild Movies) surface. |
| **v0.14.5** | ✓ Sweep observability (per-job detail page, relaxed drift apply) | `update_sweep` writes a v3 `result_summary` auditable via a new `/admin/jobs/[uuid]` detail page. Genre/studio drift auto-applies (audit log is the rollback path); unknown genre tags surface as an amber Jobs Log tint. Per-kind `jobs.version` registry + `make_job()` so shape changes don't break historical rows. JobWorker hardened against stranded `running` jobs. |
| **v0.14.6** | ✓ Backup retention, naming & restore-link | Retention reworked into three pools (archival / pre-restore / uploads). Admin can rename a backup to pin it against auto-deletion. Restore links the pre-restore snapshot to the restored dump. Nightly job re-verifies every dump's integrity. Metadata in `.meta.json` sidecars — no migration. |
| **v0.14.7** | ✓ Little fixes | Sweep step-1 MAL-failure logging (`result_summary` v4). Not-yet-aired sequels stay Main via a provisional substance pass. Spoiler-cache recompute scoped per-anime instead of whole-catalog; guests dropped from the cache. |
| **v0.14.8** | ✓ Media-level update sweep | Nightly sweep refreshes individually-due media, not whole anime (`result_summary` v5, media-grained counters). Two-clock model (MediaFreshness refresh / AnimeFreshness probe). SweepTiersCard anime/media toggle. |
| **v0.14.9** | ✓ Cleanup sweep | Themed Tooltip component. Admin "Dismissed decisions" history with delete-to-resurface. Per-check stabilizing breakdown (threshold 5→3). Probe-attached media persisted (`result_summary` v6) + job-detail audit polish. "Back to job" nav origin. |
| **v0.15.0** | Watchlist backend + UI | Watchlist CRUD, tags, priority. Watchlist page with filtering. Watchlist icons in search results. |
| **v0.15.1** | Search enhancements + design polish | "In watchlist"/"already watched" search filters. Search filter QoL improvements. Component design polish. Note: consider enlarging the watchlist bookmark icon on the media detail page for better tap target and visual presence. |
| **v0.16.0** | Browse page + home page redesign | Crunchyroll-style horizontal card rows. Browse sections with algo selector. Home page as light version. Get-started page. |
| **v0.17.0** | Statistics & analytics (v1) | Standard graphs (watch history, genre distribution, score histogram, etc.). Statistics page route. |
| **v0.18.0+** | Advanced recommendations, achievements, advanced analytics | HDBSCAN clustering, pattern prediction, "love it or hate it", achievements system with titles. Iterative. |

### Key Dependencies
- v0.10.0 (media pages) depends on v0.9.0 (ratings backend)
- v0.11.0 (anime search) depends on v0.10.0 (media pages exist to link to)
- v0.13.0 (deployment) must come before v0.14.0 (content pipeline needs Coolify cron)
- v0.15.0 (watchlist) depends on v0.11.0 (anime/media pages for navigation)
- v0.16.0 (browse) depends on v0.15.0 (watchlist) + v0.9.0 (ratings) for section data
- v0.17.0 (statistics) depends on v0.9.0 (ratings data to analyze)
