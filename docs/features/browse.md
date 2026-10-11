# Browse

The browse pages: rows of anime (carousels), each one a saved search.

**Code**: `seeders/browse_seeder.py` (the core definitions) → `models/browse.py` →
`services/browse_service.py` (layout + resolver, checked by `schemas/browse_schema.py`)
→ `routers/browse.py` → `routes/browse/+page.svelte` → `BrowseCarousel.svelte` →
`PosterCard.svelte`; a carousel's see-all is `routes/browse/[key]/+page.svelte` →
`SeeAllResults.svelte`, with `stores/browseRefinements.ts`.

## A carousel is a saved search

A carousel stores raw `/search/anime` params — never a search token, which would
freeze the filters as they stood the day it was minted. The client runs whatever the
backend resolves through the ordinary search endpoint, so a carousel sorts and
filters exactly as [search](search.md) does and has no query of its own.

A tile's line is the sort value [search carries](search.md#sorting) (`sortLine`).

A **filter set** is a partial params dict ("Top 20%" is `{top_percent: 20}`) that a
carousel offers as a refinement. `carousel_filter_set` links the two, with a
`position` and whether the set starts on (`default_on`).

## The resolver is the only place params merge

`browse_service.resolve` builds the search: the carousel's params ← its active filter
sets in `position` order, a later set winning a key clash ← the placeholders. A set is
active when it is `default_on`, flipped by the request's `on` / `off` lists — overrides
relative to the default rather than a full list, since a query string cannot tell an
empty list from an absent one.

A `$`-prefixed value in a row is a placeholder the resolver fills. The season ones
read `search_filters.utc_today()` — UTC, not the viewer's clock — so every viewer gets
the same season at the same moment.

The result goes through `CarouselParams`, which forbids unknown keys — its docstring
says why. Every seeded carousel is run as a real search by
`test_every_seeded_carousel_runs_as_a_search`.

## Definitions are seeded, layouts are code

The core carousels and filter sets are a repo list, synced by key on every boot.
Unlike the genre seeder, whatever the list drops is deleted, and links are updated in
place, so an unchanged link keeps its row. Which carousels a page shows, top to
bottom, is `PAGE_LAYOUT` in the service — a constant rather than a table, since no
user or admin chooses it.

## A see-all lists the rest

Every carousel has a see-all page: its search up to `see_all_limit`, with the filter sets
it offers as toggles. The limit is taken in the carousel's order, so a carousel is
`sortable` — its see-all offers another order — only where its params rather than its
order are what it is, and then its limit is the search's own: under a lower one, another
order would change which anime the list holds (`test_a_sortable_carousel_sees_its_whole_search`).

Sets sharing a param exclude each other, since the resolver lets only the later one
count, so the page offers them as one control (`filterSetGroups`). For the same reason a
carousel is offered only the sets that leave its own params alone, which the seeder
works out rather than lists. The top steps are the
filter sheet's own `TOP_PRESETS`, pinned by `test_the_top_steps_are_the_search_sheets`.

A viewer's choices are kept per carousel (`browseRefinements`).

## Guests

Every carousel is listed for everyone, a guest included. One over the caller's own
ratings or watchlist resolves for a guest too; [the search it runs](search.md#personal-filters-and-sort)
is where a guest is refused, so the row shows a guest why instead of running it. It
decides "personal" with `stripForGuest`, the test that strips a shared search link, and
the same test leaves a see-all's toggle over the caller's data inert.

---

**Why it is this way**
- [Browse + News](../../compound-docs/2026-10-10-v0.16.2-browse.md) — the decisions behind the definition tables, the see-all routes and the tiles
