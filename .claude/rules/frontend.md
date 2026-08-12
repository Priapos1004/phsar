---
description: Frontend conventions — runes, theme tokens, shared components, cross-page consistency, and UI copy.
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

Every `EChart` consumer spreads `chartTooltipStyle` into `option.tooltip` and sets
`emphasis: { disabled: true }`. Neither is optional and neither is type-enforced, so
a new chart only matches its siblings if you copy both.

**A chart `formatter` returns HTML that ECharts writes via `innerHTML`, so Svelte's
escaping never reaches inside it.** Catalog text spliced into one — titles, genre and
studio names — must go through `escapeHtml` (`utils/formatString.ts`). Enum labels,
numbers and ECharts' own `marker` spans are already safe.

## Titles render in the user's name language

Any user-facing title goes through `resolveTitle(title, name_eng, name_jap, nameLanguage)`.
The romaji `title` is the fallback *inside* that helper, never the thing you render
directly — a raw `title` silently ignores the user's setting.

## A toggle's surface decides its component

`SegmentedControl` is the on-card toggle — muted track, solid thumb — and belongs on
the white card surface. A toggle on the dark page surface is a border-fill pill
instead (`GrainToggle`, the ratings view pills). Same job, different surface,
deliberately not the same component; unifying them breaks one of the two.

## Dialog children that cannot shrink

`Dialog.Content` is a CSS grid whose column is floored by its widest item's min-content
width, and every item then inherits the widened track — so a single unshrinkable child
(a `nowrap` title, an image carrying an aspect ratio) pushes the whole dialog past its
`max-w-*`. Give the header and body `min-w-0`. `truncate` alone does not zero that
floor, because its `overflow:hidden` only does so on a grid or flex item.

## UI copy

Say **"anime"**, never "umbrella". That term is internal jargon for the row grouping
media and reads as nonsense to a user. It stays in code, comments and established symbol
names (`AnimeUmbrellaCard`, `umbrella_diff`); this rule governs new user-facing strings.

## The user verifies UI

After a UI-touching change, hand off with a concise **"what to check"** list and wait for
their verdict rather than driving the dev-browser to self-verify — they have the app open.
Offer to look yourself only when genuinely stuck on a bug.
