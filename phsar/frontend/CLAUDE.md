# Frontend — design notes

SvelteKit + Svelte 5 runes + Tailwind 4 + shadcn-svelte. Loaded on top of root [CLAUDE.md](../../CLAUDE.md) when working in the frontend tree.

## routes/

Pages: home (`/`), login (`/login`), register (`/register`), search (`/search`), media detail (`/media`), anime detail (`/anime`), settings (`/settings`), admin (`/admin`), add to library (`/library/add`).

- `GET /health` endpoint returning `{status, version}` for Coolify liveness — deliberately does not probe backend (liveness should only check what restarting this container can fix)
- `/library/add` — query-input + recent-additions panel; submitting POSTs to `/jobs/scrape` and the navbar bell takes over from there; restricted users see the page but the form is disabled
- **Tab title convention**: every route declares its own `<svelte:head><title>…</title></svelte:head>` in the format `<Page> — Phsar` (em dash, "Phsar" title case). Page name first so users with several PHSAR tabs open can distinguish them in the tab strip; the favicon already conveys "this is PHSAR". Detail pages (anime/media) bind the title reactively to the resolved name and fall back to a generic label while loading. `app.html` only sets the default `PHSAR` so the very first paint isn't blank — every route is expected to override
- **Admin tab navigation**: `/admin` uses a `?tab=` query param to switch between sections (`overview` default, `jobs`, `tokens`, `curation`, `backups`). Tabs eager-render and stay mounted (visibility toggles via `class:hidden`), so first paint pays one parallel fetch per tab and subsequent switches are instant. The tab list, default, and validation live at the top of `routes/admin/+page.svelte`; the tab UI itself is `lib/components/admin/AdminTabNav.svelte`. Adding a tab requires updating three places: `AdminTabKey` in `lib/components/admin/types.ts`, the `TABS` array + content cascade in the page, and the rendering branch
- **Per-job detail page**: `/admin/jobs/[uuid]/+page.svelte` renders an update_sweep v2+ job's full audit trail — header card, counters grid, filterable media-change list (chips: all / dynamic-no-rating / rating / static / has drift; search across all title-language fields) sorted most-substantial-first via `sortMediaChanges` (group static > genre/studio > dynamic > rating-only, then by amount changed; rating-only by search-relevance impact), umbrella reclassification cards. v4 (v0.14.7) renders a **Failed-refresh list card** (per-anime `step1_failures`); v5 (v0.14.8) adds a symmetric **Failed-probe list card** (`probe_failures` — title link + `error_category` + message) and a **progress-divergence warning** when `items_done < items_total` (anime selected but skipped). Failed jobs only show the error banner in the header; v1 sweeps render a "predates v0.14.5" notice. Click-through from `AdminJobsLogTab` is restricted to `update_sweep && version >= 2`; its `payloadSummary()` reads media-grained keys (`media_refreshed`, `media_with_dynamic_changes`) for v5 and the anime-grained keys for v2–v4
- **Settings page** (`/settings`): restricted (guest) users see **all controls disabled, not hidden** — Rating Step, Data Export buttons, and the Spoiler Protection select (pinned to `Off`, since guests can't rate and are excluded from the spoiler cache). Theme / name-language / search-view stay editable. The server also drops a guest's `spoiler_level` update defensively (`user_settings_service`)
- **Detail-page back button**: anime/media routes render `<BackLink searchToken fromParam />` near the top. It decides between "Back to search" (when `?q=<token>` is present, from search results) and "Back to library" (when `?from=library`, e.g. recent-additions panel). New origins extend the `DetailOrigin` type union in `lib/utils/navigation.ts` AND the `target` switch in `BackLink.svelte`. `buildDetailHref()` propagates both flags on internal anime↔media jumps so a deep dive (library → anime → media) stays linkable back to the origin

## lib/components/

App components using Svelte 5 `$props()`, `$state()`, `$derived()`, `$effect()`.

- **SearchBar, MediaInfo, NavBar, TagSelect, DoubleRangeSlider, RatingCard, BulkRateDialog, DangerZone, RelatedMediaCarousel, SpoilerGuard, EChart** — core UI components
- **Tooltip** — the single app-wide hover/focus tooltip (wraps the shadcn-svelte/bits-ui `ui/tooltip` primitive). Themed to the active palette: a faint primary-tinted `popover` surface with a `--primary` border + soft primary glow (see `ui/tooltip/tooltip-content.svelte`), ~500ms delay. **Self-contained** — it renders its own `Tooltip.Provider`, so it works standalone (incl. isolated component tests) with no ancestor Provider. Two modes: pass `children` for non-interactive hints (renders a `cursor-help` span trigger — status dots, labels, chart bars) or a `trigger` snippet for interactive elements (spread `props` onto your own `<Button>`/`<button>` so keyboard focus reveals it and nothing gets double-wrapped; icon-only buttons must add an `aria-label`). **Convention:** use it for intentional hints; keep native `title=` for raw text-overflow reveals on dense data cells (MediaChangeCard / AnimeUmbrellaCard / search-result titles) so they don't each become a keyboard tab stop. Note: a test that mocks `svelte`'s `setContext`/`getContext` must delegate unknown keys to the real impl, or the Provider context breaks (see `tests/media-detail.test.ts`)
- **RatingsOverview** — with sub-components: Stats, Timeline, Notes, Attributes
- **AttributeRadar, AttributeBadges, AttributeDetailBars** — attribute visualization
- **VersionFooter** — renders at the bottom of every page, reads `PUBLIC_APP_VERSION` from `$env/dynamic/public`
- **LoadingScreen** — themed sakura-ring loader shown during initial boot + ~1.5s logout transition
- **Notice** — shared yellow info card (rounded `bg-yellow-50` surface + `AlertTriangle` icon — solid surface so it reads on the dark body gradient)
- **BackLink** — shared back-button used by anime/media detail pages; renders nothing when neither `searchToken` nor a known `fromParam` is set (so direct-URL arrivals stay clean)
- **RelatedMediaCarousel** — sibling-media row on the media detail page. Backend (`media_search_service.get_media_detail`) returns `sibling_media` chronologically via the shared `chronological_media_key()` helper in `filter_service.py` — same key the spoiler frontier and anime-detail media table use — and a `current_position` insertion index. The carousel renders a "You are here" divider at that slot; frontend doesn't compare dates, the backend owns the ordering
- **BackupsCard** — admin-only dump list
  - Create/upload/download/restore/delete with a "Current" badge on the row the DB was last restored from
  - **Rename / pin** (pencil → inline `Input` + Save/Cancel; `PATCH /admin/backups/{filename}`): a non-empty name pins the dump against auto-retention and renders a "Pinned" badge. Pinned rows show a one-click `PinOff` action directly in the row (no need to enter edit mode); saving a blank name in the editor also unpins. `saveName(filename, name)` is the shared call behind `handleRename` (Save) and `handleUnpin` (one-click remove)
  - Refreshes are silent — `refresh()` flips `loading` only on the initial mount, so a refetch after rename/unpin/delete/restore diffs the keyed `{#each}` in place instead of collapsing to a spinner and snapping scroll to the top (same pattern as MergeCandidatesCard)
  - **Restore link**: the `is_current` row shows "Previous state saved as `{previous_state}`"; a `pre_restore` row shows "Snapshot of the state before restoring `{restored_to}`" — both derived from sidecar metadata, no client computation
- **MergeCandidatesCard** / **SplitCandidatesCard** — admin-only review surfaces for pending merge/split candidates
  - Side-by-side anime info (with rating count + earliest aired date as visible justification for recommended A)
  - Similarity score, merge/dismiss with confirm-step, per-row "Swap A/B" button
  - Silent refreshes — keyed each-block diffs in place instead of collapsing to "Loading…"
  - Merges trigger automatic refetch surfacing cascade-resolved pairs and freshly-detected ones
  - Both embed **admin/DismissedDecisionsSection** at the bottom (a "Dismissed decisions" expander; see below), passing `currentUsername` (threaded from the admin page's `getUsername()` context) and `onResurfaced={handleRedetect}`
- **admin/DismissedDecisionsSection** — shared, generic (`<T extends {uuid, dismissed_at}>`) collapsible history of dismissed merge/split decisions, reused by both candidate cards. Lazy-fetches its `listUrl` on first expand; renders each row via a parent-supplied `row` snippet (merge shows A↔B; split shows the source + "would split off:" member titles per cluster). A username-gated confirm dialog (mirrors BackupsCard restore) POSTs `${basePath}/{uuid}/delete`, then calls `onResurfaced()` so the parent re-runs detection and the freed candidate pops back into the pending list. Subscribes to `curationRefresh` (`onBump`) so the counter/list re-fetch when the parent dismisses a new candidate — no stale `(N)`
- **MaintenanceBanner** — wraps a `Notice`, lives in a sticky container in `+layout.svelte` alongside the navbar
  - Polls `GET /maintenance/status` every 30s via raw `fetch` (bypasses `api.ts` so a 503 mid-window can't trigger maintenance redirect and defeat the pre-warning point — 30s instead of 60s because seasonal sweep's maintenance window can be only seconds long)
  - Subscribes to `token` store + `maintenanceRefresh` bump signal so relogin or any 503-with-maintenance response refreshes in milliseconds
  - Countdown wording: `"Scheduled maintenance starts in ~N minute(s) — pause your current episode."` within 30 min; `"Maintenance in progress. Please try again later."` when active; otherwise hidden
- **JobBell** — polls `/jobs/mine`
  - Caps dropdown at 5 entries (older spill to `/library/add`)
  - Hides retry button when `result_summary.retryable === false`
  - Disables retry across all rows while one is in flight
  - Progress bar uses `Math.min(100, Math.round(percentOf(items_done, items_total)))` — backends occasionally over-report a child batch as more items than the initial total estimate; the 100-cap keeps the bar from rendering 137%
- **admin/AdminJobsLogTab** — paginated jobs table with kind/status filters, seasonal_sweep child expander
  - Kind/status filters persist via the `jobsFilter` module store (`lib/stores/adminJobsFilter.ts`), **not** the URL. The store is in-SPA memory that survives admin tab switches AND the round-trip through `/admin/jobs/[uuid]` — both navigate to a bare `/admin?tab=jobs`, and a mounted module store carries the filter through without re-threading it (so the detail back link stays a plain `/admin?tab=jobs`). The tab reads the store via `$derived` (drives the Select + the fetch) and writes it in the filter setters; a `$effect` on `($jobsFilter, offset)` re-fetches. `routes/admin/+layout.svelte` cascades over the whole section and calls `clearJobsFilter()` `onDestroy`, so re-entering /admin from elsewhere (e.g. Settings) starts clean while in-section hops keep the filter. Deliberately **no** URL mirror: it's an internal tool, refresh-survival/shareable-links aren't worth the reconcile complexity, and a URL copy would resurrect a filter on browser-back after leaving. Values are whitelisted against `JOB_KIND_LABELS` / `STATUS_BADGE` keys (`sanitizeKind`/`sanitizeStatus`); pagination offset stays in component state. Helpers unit-tested in `tests/admin-jobs-filter.test.ts`
  - Live-ticking Duration column for `running` rows (shared `formatJobDuration` + a `hasRunning` short-circuit derived so the 1s interval is quiet when nothing is in flight)
  - Click-through to `/admin/jobs/[uuid]` ONLY for `update_sweep && version >= 2` rows — the detail page has nothing to add for other kinds, so the row stays non-clickable (no cursor, no hover, no keyboard handler) and the click affordance matches what's behind it
  - Amber row tint + inline "⚠ N unknown genre tags need seeding" subline when `result_summary.unknown_genre_tags` is non-empty (v3 update_sweep only), so the admin spots seeder-update work without drilling into the detail page
- **admin/SweepTiersCard** — admin Overview card showing where every row sits in the update-sweep cycle, with an **anime/media toggle** (v0.14.8, default anime). Takes `animeTiers` + `mediaTiers`; backend exposes 4 mutually-exclusive **cycle-membership** priority-cascade buckets (airing_now / stabilizing / weekly_cycle / long_cycle) at each grain via `sweep_tiers` + `media_sweep_tiers`; the card renders the selected grain 1:1 (no fold). Membership not due-ness — counts stay stable across sweeps instead of emptying when a sweep refreshes a tier. Per-row horizontal share bar, count, percentage, tooltip with the underlying predicate (stabilize < 3 sweeps, 90-day long cycle — both shared by the two grains). The Stabilizing row expands into per-check **sub-rows** (`stabilizing_by_check` — one per `stable_check_count` 0…threshold-1) so the stabilization pipeline is visible; bar opacity ramps with the check count (closer to graduating = more filled). Media grain buckets each media by its own count; anime grain by its **least-settled member** (MIN across its media). Sub-row count is derived dynamically (`stabilizeThreshold = Object.keys(stabilizing_by_check).length`) so retuning `SWEEP_STABILIZE_THRESHOLD` reshapes the card with no frontend edit
- **admin/JobDetailHeader / JobDetailCounters / MediaChangeCard / AnimeUmbrellaCard** — sub-components of the `/admin/jobs/[uuid]` detail page
  - `MediaChangeCard`: 5 tones (rating-zinc / dynamic-amber / static-sky / genre-fuchsia / studio-indigo) with a colored left border per row; rating sorts last so vote-count churn doesn't drown the actionable bits. Genre / studio drift folds into the same Field/Was/Now table — was-cell shows old tags with removed in red, now-cell shows new tags with added in green; v2 (legacy) drift kinds render a "Not auto-applied" subline since the dispatcher only logged them
  - `AnimeUmbrellaCard`: per-anime 7-field umbrella diff + per-media relation reclassifications + "anchor moved" / "embedding regen" badges
  - `JobDetailCounters`: takes `version`; the STATS array is version-aware — v5 shows media-grained counters (`media_refreshed`, `anime_touched`, `media_skipped_fresh`) and drops the `anime_with_*` rollups, v2–v4 show the anime-grained originals. The `step1_failed` cell renders only for v4+ (older rows show "—", not a misleading `0`) and tints amber when `> 0`; kept unchanged across the v5 bump

## lib/components/ui/

shadcn-svelte base components (button, card, input, badge, slider, dropdown-menu, popover, checkbox, label, select, separator, etc.).

## lib/

- **api.ts** — centralized API client
  - Methods: `get`/`post`/`postForm`/`put`/`del`/`downloadBlob`/`postMultipart`
  - `ApiError` class, automatic auth header injection from token store
  - Maintenance-503 handler: clears token, calls `bumpMaintenanceRefresh()` (covers user-on-/login where `token.set(null)` is a no-op), hard-navigates to `/login`
- **types/api.ts** — TypeScript interfaces mirroring backend Pydantic schemas (`MediaConnected`, `FilterOptions`, `TokenResponse`, etc.)
- **stores/** — Svelte stores for auth, settings, spoiler visibility, bell session, cross-component bumps
  - `jobs.ts`:
    - Three writable bumps via `createBumpStore()` factory + `onBump(store, fn)` helper:
      - `jobsRefresh` — bumped by `/library/add` or BackupsCard after successful POST so bell refetches in ms instead of waiting for 30s idle poll
      - `librarySaved` — bumped by bell when it observes a new `succeeded` `user_scrape` so `/library/add` refreshes recent-additions
      - `backupSaved` — bumped by bell on new `succeeded` `backup` so BackupsCard auto-refreshes
    - Same `announcedSavedUuids` Set covers both kinds — UUIDs are globally unique
    - `optimisticJobs` (writable list) + `addOptimisticJob(job)` / `reconcileOptimisticJobs(fetched)`:
      - Bell merges optimistic ∪ fetched (deduped by UUID) inside `$derived`
      - Callers seed a `queued` row synchronously off returned `job_uuid`; next fetch reconciles (UUID match → optimistic pruned)
    - Store-update helpers short-circuit no-ops (svelte writables notify on every `set()` even with same-reference returns)
  - `maintenance.ts` — `maintenanceRefresh` writable + `bumpMaintenanceRefresh()`; `api.ts` bumps on every 503-with-maintenance, `MaintenanceBanner` subscribes via `onBump`
  - `bell-session.ts` — `BELL_LOGIN_KEY` / `BELL_SEEN_KEY` + `clearBellSession()` helper; `auth.ts` calls it when token transitions to null so logout-and-back-in doesn't inherit previous session state (sessionStorage survives hard navs)
- **utils/** — helpers:
  - String formatting: `formatAiringStatus`, `formatRelationType`, `formatMediaType`, `formatSeasonRange`, `formatDuration`, `formatJobDuration`, `formatDecimalDigits`, `formatShortDate`, `formatShortDateTime`, `formatBytes`
  - Numeric: `percentOf(value, total)` — share-of-total with divide-by-zero guard; callers compose with `Math.round` (integer %) or `.toFixed(1)` (decimal %). `isRatingField(name)` — single source of truth for the score / scored_by sub-bucket split used by `MediaChangeCard.dynamicTone` and the route page filter chip
  - Season logic, search params (`fetchSearchResults`, `fetchAnimeSearchResults`), navigation (`navigateToSearch`, `buildDetailHref`)
  - Chart colors: `CHART_COLORS`, `scoreColor`, `getThemedChartColorPalette`, `RELATION_TYPE_ORDER`, `RELATION_TYPE_COLORS`, `RELATION_TYPE_LABELS`
  - `jobBadges.ts` — `STATUS_BADGE: Record<JobStatus, string>` shared between `AdminJobsLogTab` and `JobDetailHeader` so status pill colors can't drift
  - `spoilerFrontier.ts` — client-side frontier for detail pages
  - `mediaChangeSort.ts` — `sortMediaChanges` for the job-detail media-change list (category-priority then amount-changed; rating-only by weighted `score*log10(scored_by+1)` delta — matches the backend search ranking). Decorate-sort-undecorate so the per-row key is computed once per re-sort; extracted from the page so it's unit-testable
- **themes.ts** — centralized theme config: `THEMES` record mapping keys to CSS classes, character pics, labels; `ThemeKey` type; helpers: `isValidTheme`, `getThemeCssClass`, `getThemePic`, `getThemeFocal`, `getActiveTheme`
- **echarts.ts** — lazy-loaded ECharts singleton (`getEcharts()`) using pre-built ESM bundle (SSR-safe, cached)
- **config.ts** — backend API base URL (consumed only by `api.ts`)

## src/app.css

Theme system: `@property` definitions for `--primary`/`--ring`, `@theme inline` with `var()` indirection, `.theme-red`/`.theme-blue`/`.theme-green` override classes, themeable gradient variables (body dark gradient `--gradient-*` + auth-page light gradient `--auth-gradient-*`). Light elevated surfaces on dark gradient background. Dark mode locked to class-based only.

## tests/

Vitest + @testing-library/svelte component tests.
