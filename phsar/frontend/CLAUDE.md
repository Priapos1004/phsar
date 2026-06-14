# Frontend — design notes

SvelteKit + Svelte 5 runes + Tailwind 4 + shadcn-svelte. Loaded on top of root [CLAUDE.md](../../CLAUDE.md) when working in the frontend tree.

## routes/

Pages: home (`/`), login (`/login`), register (`/register`), search (`/search`), media detail (`/media`), anime detail (`/anime`), settings (`/settings`), admin (`/admin`), add to library (`/library/add`).

- `GET /health` endpoint returning `{status, version}` for Coolify liveness — deliberately does not probe backend (liveness should only check what restarting this container can fix)
- `/library/add` — query-input + recent-additions panel; submitting POSTs to `/jobs/scrape` and the navbar bell takes over from there; restricted users see the page but the form is disabled
- **Tab title convention**: every route declares its own `<svelte:head><title>…</title></svelte:head>` in the format `<Page> — Phsar` (em dash, "Phsar" title case). Page name first so users with several PHSAR tabs open can distinguish them in the tab strip; the favicon already conveys "this is PHSAR". Detail pages (anime/media) bind the title reactively to the resolved name and fall back to a generic label while loading. `app.html` only sets the default `PHSAR` so the very first paint isn't blank — every route is expected to override
- **Admin tab navigation**: `/admin` uses a `?tab=` query param to switch between sections (`overview` default, `jobs`, `tokens`, `curation`, `backups`). Tabs eager-render and stay mounted (visibility toggles via `class:hidden`), so first paint pays one parallel fetch per tab and subsequent switches are instant. The tab list, default, and validation live at the top of `routes/admin/+page.svelte`; the tab UI itself is `lib/components/admin/AdminTabNav.svelte`. Adding a tab requires updating three places: `AdminTabKey` in `lib/components/admin/types.ts`, the `TABS` array + content cascade in the page, and the rendering branch
- **Detail-page back button**: anime/media routes render `<BackLink searchToken fromParam />` near the top. It decides between "Back to search" (when `?q=<token>` is present, from search results) and "Back to library" (when `?from=library`, e.g. recent-additions panel). New origins extend the `DetailOrigin` type union in `lib/utils/navigation.ts` AND the `target` switch in `BackLink.svelte`. `buildDetailHref()` propagates both flags on internal anime↔media jumps so a deep dive (library → anime → media) stays linkable back to the origin

## lib/components/

App components using Svelte 5 `$props()`, `$state()`, `$derived()`, `$effect()`.

- **SearchBar, MediaInfo, NavBar, TagSelect, DoubleRangeSlider, RatingCard, BulkRateDialog, DangerZone, RelatedMediaCarousel, SpoilerGuard, EChart** — core UI components
- **RatingsOverview** — with sub-components: Stats, Timeline, Notes, Attributes
- **AttributeRadar, AttributeBadges, AttributeDetailBars** — attribute visualization
- **VersionFooter** — renders at the bottom of every page, reads `PUBLIC_APP_VERSION` from `$env/dynamic/public`
- **LoadingScreen** — themed sakura-ring loader shown during initial boot + ~1.5s logout transition
- **Notice** — shared yellow info card (rounded `bg-yellow-50` surface + `AlertTriangle` icon — solid surface so it reads on the dark body gradient)
- **BackLink** — shared back-button used by anime/media detail pages; renders nothing when neither `searchToken` nor a known `fromParam` is set (so direct-URL arrivals stay clean)
- **RelatedMediaCarousel** — sibling-media row on the media detail page. Backend (`media_search_service.get_media_detail`) returns `sibling_media` chronologically via the shared `chronological_media_key()` helper in `filter_service.py` — same key the spoiler frontier and anime-detail media table use — and a `current_position` insertion index. The carousel renders a "You are here" divider at that slot; frontend doesn't compare dates, the backend owns the ordering
- **BackupsCard** — admin-only dump list
  - Create/upload/download/restore/delete with a "Current" badge on the row the DB was last restored from
- **MergeCandidatesCard** — admin-only review surface for pending merge candidates
  - Side-by-side anime info (with rating count + earliest aired date as visible justification for recommended A)
  - Similarity score, merge/dismiss with confirm-step, per-row "Swap A/B" button
  - Silent refreshes — keyed each-block diffs in place instead of collapsing to "Loading…"
  - Merges trigger automatic refetch surfacing cascade-resolved pairs and freshly-detected ones
- **MaintenanceBanner** — wraps a `Notice`, lives in a sticky container in `+layout.svelte` alongside the navbar
  - Polls `GET /maintenance/status` every 30s via raw `fetch` (bypasses `api.ts` so a 503 mid-window can't trigger maintenance redirect and defeat the pre-warning point — 30s instead of 60s because seasonal sweep's maintenance window can be only seconds long)
  - Subscribes to `token` store + `maintenanceRefresh` bump signal so relogin or any 503-with-maintenance response refreshes in milliseconds
  - Countdown wording: `"Scheduled maintenance starts in ~N minute(s) — pause your current episode."` within 30 min; `"Maintenance in progress. Please try again later."` when active; otherwise hidden
- **JobBell** — polls `/jobs/mine`
  - Caps dropdown at 5 entries (older spill to `/library/add`)
  - Hides retry button when `result_summary.retryable === false`
  - Disables retry across all rows while one is in flight

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
  - String formatting: `formatAiringStatus`, `formatRelationType`, `formatMediaType`, `formatSeasonRange`, `formatDuration`, `formatDecimalDigits`, `formatShortDate`, `formatShortDateTime`, `formatBytes`
  - Season logic, search params (`fetchSearchResults`, `fetchAnimeSearchResults`), navigation (`navigateToSearch`, `buildDetailHref`)
  - Chart colors: `CHART_COLORS`, `scoreColor`, `getThemedChartColorPalette`, `RELATION_TYPE_ORDER`, `RELATION_TYPE_COLORS`, `RELATION_TYPE_LABELS`
  - `spoilerFrontier.ts` — client-side frontier for detail pages
- **themes.ts** — centralized theme config: `THEMES` record mapping keys to CSS classes, character pics, labels; `ThemeKey` type; helpers: `isValidTheme`, `getThemeCssClass`, `getThemePic`, `getThemeFocal`, `getActiveTheme`
- **echarts.ts** — lazy-loaded ECharts singleton (`getEcharts()`) using pre-built ESM bundle (SSR-safe, cached)
- **config.ts** — backend API base URL (consumed only by `api.ts`)

## src/app.css

Theme system: `@property` definitions for `--primary`/`--ring`, `@theme inline` with `var()` indirection, `.theme-red`/`.theme-blue`/`.theme-green` override classes, themeable gradient variables (body dark gradient `--gradient-*` + auth-page light gradient `--auth-gradient-*`). Light elevated surfaces on dark gradient background. Dark mode locked to class-based only.

## tests/

Vitest + @testing-library/svelte component tests.
