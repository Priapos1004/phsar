# Frontend — design notes

SvelteKit + Svelte 5 runes + Tailwind 4 + shadcn-svelte. Loaded on top of root [CLAUDE.md](../../CLAUDE.md) when working in the frontend tree.

## routes/

One page per directory. SSR is on (adapter-node defaults, nothing opts out), but all
*data loading* is client-side: there are no `+page.server.ts` loads and the only
`+layout.ts` is the root navigation guard, which returns early off the browser. What a
page *does* for a user is specified in [USER_FLOWS.md](USER_FLOWS.md); why it is built
the way it is sits in the page itself.

| Route | Worth knowing before editing |
|---|---|
| `/anime`, `/media` | the two detail grains — conceptual siblings, so see the parallel-pages table in [rules/frontend.md](../../.claude/rules/frontend.md) before adding to one |
| `/ratings`, `/watchlist` | a `?tab=` switcher over a list tab and a Statistics tab. The page owns the fetches, so a tab switch never refetches. Whether a tab stays mounted or remounts differs between the two on purpose — each page states which and why |
| `/admin` | `?tab=` again, tabs eager-rendered and kept mounted. `AdminTabKey` in `lib/components/admin/types.ts` lists what adding one touches |
| `/admin/jobs/[uuid]` | the sweep audit trail, rendered per `result_summary` version — the versions themselves are in [jobs](../../docs/features/jobs.md) |
| `/search` | which filters survive an anime↔media switch |
| `/library/add` | enqueues a scrape; the navbar bell owns everything after that |
| `/health` | liveness for the container platform |

Section filters reset from one `afterNavigate` in the root layout, via
`lib/utils/filterLifecycle.ts`.

## lib/components/

A component's reasoning lives in that component — usually a comment at the top of
its `<script>`, sometimes beside the markup it explains. This table names the files
that carry an area's reasoning; it is not an inventory of the tree.

| Area | Start here |
|---|---|
| Charts | `EChart.svelte` — the wrapper, and where the measurement and animation constraints are written down. Then `echarts.ts`, `$lib/utils/chartTheme.ts`, and `ratings/` for the charts themselves |
| Share card | `ShareDialog.svelte` (the capture), `ShareCard.svelte` (the layout budget, and which CSS the rasterizer reproduces), `$lib/utils/shareContent.ts` (what a card may and may not say), `$lib/utils/shareImage.ts` |
| Rating form | `RatingCard.svelte` (the watch-state guards), `ScoreDial`, `AttributeSelect`, `RatingNeighbors`, `BulkRateDialog` |
| Attribute viz | `AttributeRadar` and `AttributeBadges` — the share card renders both unchanged, so each carries one prop that exists only for that. `AttributeDetailBars` is page-only |
| Watchlist | `WatchlistBookmarkIcon` (the mask gradient), `WatchlistDialog`, `BulkWatchlistDialog`, and `watchlist/` for the page's own tabs |
| Admin | `admin/`, plus `BackupsCard`, `MergeCandidatesCard`, `SplitCandidatesCard`. The job-detail page argues its own case in `src/routes/admin/jobs/[uuid]/+page.svelte` |
| Session + status | `SessionTimeoutBanner` with `$lib/utils/sessionTimeout.ts`, `MaintenanceBanner`, `JobBell`, `Toast`/`ToastHost` |
| Search | `SearchBar.svelte`, and `src/routes/search/+page.svelte` for which filters survive an anime↔media switch |

Several of these render a verdict the backend owns — restorability, cycle membership,
merge and split candidates, sibling order — and must not recompute it; the relevant
[feature doc](../../docs/features/) carries the contract. One trap worth naming: the
sweep-tiers card's cycle-membership buckets are **not** the due-ness tiers in
[jobs](../../docs/features/jobs.md), which count the long tail deliberately
differently — the two disagree on how many there are, on purpose.

## lib/

`api.ts` is the single API client. It owns the maintenance-503 behaviour and the
deliberate absence of a global 401 handler, both argued at the throw site.
`types/api.ts` mirrors the backend's Pydantic schemas.

| Area | Start here |
|---|---|
| Stores | `stores/` — each file's header carries its own lifecycle. The two that catch people: `ratingScores.ts` is a real cache, so every rating write has to invalidate it, and `filterOptions.ts` is catalogue-global and deliberately survives a logout |
| Filter persistence | `stores/persistedFilter.ts` — the factory, its version envelope, and the reset registry — under every section's filter store. `utils/filterLifecycle.ts` decides *when* a section resets |
| Per-user cleanup | `clearPerUserStores` in `routes/+layout.svelte`; anything keyed to *which* user belongs in it |
| Formatting | `utils/formatString.ts`, where the score rounding and step-awareness rules live |
| Ratings + watchlist maths | `utils/ratingStats.ts`, `utils/watchlistStats.ts` — pure, unit-tested, and the reason there is no per-user stats endpoint |
| Charts | `utils/chartTheme.ts`, `utils/chartColors.ts`, `echarts.ts` |
| Share | `utils/shareContent.ts`, `utils/shareImage.ts` |
| Navigation | `utils/navigation.ts` — `buildDetailHref` and the closed `DetailOrigin` set |
| Theme | `themes.ts` with `app.css` |

## The rest of the tree

- `lib/components/ui/` — shadcn-svelte primitives. Mostly untouched, but not
  off-limits: `ui/tooltip/tooltip-content.svelte` carries the app's themed surface.
- `app.css` — the theme system: `@property` registration, `@theme inline` `var()`
  indirection, the `.theme-*` override classes and the gradients. The file itself
  explains why the `:root` defaults cannot be left to `@property` alone.
- `tests/` — Vitest with `@testing-library/svelte`. `setup.ts` mocks the SvelteKit
  modules and carries the one non-obvious hook, a flush for bits-ui's deferred
  body-scroll-lock restore.
