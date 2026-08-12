---
description: Frontend conventions — runes, theme tokens, shared components, tooltip and chart mechanics, dialog sizing, route titles, restricted accounts, and UI copy.
paths: "phsar/frontend/src/**/*"
---

# Frontend rules

## Stack conventions

- SvelteKit with **Svelte 5 runes** (`$props()`, `$state()`, `$derived()`, `$effect()`).
- UI primitives come from **shadcn-svelte**.
- Style with **theme tokens** (`bg-card`, `text-primary`, `ring-ring`), never hardcoded
  Tailwind colors — themes override tokens, so a literal color silently ignores the
  user's chosen theme.
- API calls go through the centralized client in `$lib/api.ts`; response types live in
  `$lib/types/api.ts`. Two deliberate exceptions use raw `fetch`, both commented in
  place: `MaintenanceBanner` (routing through `api.ts` would trip its own 503 handler
  and log the user out) and `shareImage.ts` (fetches cover bytes from MAL's CDN, not
  from this API).

## Shared components

**Audit every usage before changing one.** Grep for all call sites and review the
contexts first — a change that looks locally correct can be wrong in three other places.

Having done that, prefer changing the component over adding a per-instance override.
Overrides are how one component quietly becomes four variants.

## Parallel pages stay parallel

Pages that are conceptually siblings should present the same concept the same way — the
same formatting for main/side media counts, studios, scores, dates. A second
implementation is how two pages drift into looking like different products.

| Sibling pair | Shared surface |
|---|---|
| `/anime` ↔ `/media` (both take `?uuid=`) | hero, badges, genre chips, studio formatting, bookmark + share affordances |
| `/ratings` ↔ `/watchlist` | list controls, filter lifecycle, card layout, statistics subtab |
| search results: anime view ↔ media view | card layout, badges, score display |

**Before adding a display element to one of a pair, look at its sibling.** If the sibling
already renders that concept differently, either reuse its component or change both. When
planning a large feature, identify which existing components it should reuse *before*
building.

If a pair has a genuine reason to diverge, **raise it for discussion** rather than
deciding alone — divergence is how the pairs drifted apart in the first place.

## Tooltips — pick by what the cursor is over

Never style raw text as a hint. Three mechanisms, and they are the whole set:

| Cursor is over | Use |
|---|---|
| a DOM element | the app `Tooltip` (`lib/components/Tooltip.svelte`) — themed, keyboard-reachable, brings its own Provider |
| a chart canvas | that chart's `option.tooltip`, spreading `chartTooltipStyle` |
| a dense data cell whose text is merely truncated | native `title=` |

The third is not laziness. A per-row app `Tooltip` makes every cell a keyboard tab
stop and mounts a Provider per row, which is why the tables and cover cards use the
native attribute instead.

## Charts

Every chart sets `emphasis: { disabled: true }`, and every chart **that has a hover**
spreads `chartTooltipStyle` into `option.tooltip`. Neither is type-enforced, so a new
chart only matches its siblings if you copy them across. The score gauges are the
legitimate exception on the tooltip half — there is nothing to hover on a gauge — so
don't "fix" them by adding one.

**A chart `formatter` returns HTML that ECharts writes via `innerHTML`, so Svelte's
escaping never reaches inside it.** Catalog text spliced into one — titles, genre and
studio names — must go through `escapeHtml` (`utils/formatString.ts`). Enum labels,
numbers and ECharts' own `marker` spans are already safe.

## Titles render in the user's name language

Any user-facing title goes through `resolveTitle(title, name_eng, name_jap, nameLanguage)`.
The romaji `title` is the fallback *inside* that helper, never the thing you render
directly — a raw `title` silently ignores the user's setting.

## A toggle's surface decides its component

The exception to "prefer changing the component" above. `SegmentedControl` is the
on-card toggle — muted track, solid thumb — and belongs on the white card surface. A
toggle on the dark page surface is a border-fill pill instead (`GrainToggle`, the
ratings view pills). Same job, different surface, deliberately two components:
unifying them makes one of the two illegible against its own background.

## Dialog children that cannot shrink

`Dialog.Content` is a CSS grid whose column is floored by its widest item's min-content
width, and every item then inherits the widened track — so a single unshrinkable child
(a `nowrap` title, an image carrying an aspect ratio) pushes the whole dialog past its
`max-w-*`. Give the header and body `min-w-0`. `truncate` alone does not zero that
floor, because its `overflow:hidden` only does so on a grid or flex item.

## Every route titles its own tab

`<svelte:head><title>` per route, formatted `<Page> — Phsar`: page name first, em
dash, "Phsar" in title case. Several Phsar tabs are a normal way to use the app and
the favicon already says which app it is, so the page name is the only thing telling
them apart. `app.html`'s bare `PHSAR` exists so the first paint isn't blank, not as a
fallback to leave in place.

A **detail** page's title is its subject, not its route: bind it through
`resolveTitle` (above) and fall back to a generic `Anime — Phsar` / `Media — Phsar`
only while loading.

## Restricted accounts lose the action, not the affordance

Scale the treatment to what is being withheld:

- **A single control** renders **inert, not hidden** — a dimmed bookmark or a disabled
  select shows the guest what the account could do, so it reads as limited rather than
  as broken.
- **A whole section** gets an **explanatory replacement** instead: the media page swaps
  the rating form for a card saying why, and the watchlist tabs show a muted
  empty-state. A section silently disabled in place would just look dead.

Never leave a guest facing a control that appears live and fails. Requests that would
403 are skipped or their 403 swallowed — the layout gates the watchlist and tag store
refreshes, pages gate their own fetches, and the detail pages absorb the 403 — and the
backend drops a restricted user's write defensively rather than trusting any of it.

## UI copy

Say **"anime"**, never "umbrella". That term is internal jargon for the row grouping
media and reads as nonsense to a user. It stays in code, comments and established symbol
names (`AnimeUmbrellaCard`, `umbrella_diff`); this rule governs new user-facing strings.

## The user verifies UI

After a UI-touching change, hand off with a concise **"what to check"** list and wait for
their verdict rather than driving the dev-browser to self-verify — they have the app open.
Offer to look yourself only when genuinely stuck on a bug.
