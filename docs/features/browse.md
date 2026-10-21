# Browse

The browse pages: rows of anime (carousels), each one a saved search.

**Code**: `seeders/browse_seeder.py` (the core definitions) → `models/browse.py` →
`services/browse_service.py` (layout + resolver, checked by `schemas/browse_schema.py`)
→ `routers/browse.py` → `BrowsePageRows.svelte` (on Browse and on Home) → `BrowseCarousel.svelte` →
`PosterCard.svelte`; a carousel's see-all is `routes/browse/[key]/+page.svelte` →
`SeeAllResults.svelte`, with `stores/browseRefinements.ts`. Discover: `DiscoverTab.svelte`
(with `DiscoverWheel.svelte`, `WorldParticles.svelte`, `WorldReveal.svelte`,
`utils/discoverWorlds.ts` and `utils/worldReveal.ts`) over `/browse/worlds`; its spins are counted in
`models/discover_progress.py`.

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

The core carousels and filter sets are a repo list, synced by key on every boot, and
again after a backup restore, since the page looks carousels up by key.
Unlike the genre seeder, whatever the list drops is deleted, and links are updated in
place, so an unchanged link keeps its row. Which carousels a page shows, top to
bottom, is `PAGE_LAYOUT` in the service — a constant rather than a table, since no
user or admin chooses it. Home is one of those pages. A carousel sits on one page only and
says which (`page`), since its tiles and its see-all link back there.

## Discover draws one world a day

Discover's rows are grouped into worlds (`WORLDS`): umbrella themes, one of which a
spin of the wheel shows. A row may sit in several worlds; Discover's `PAGE_LAYOUT` entry
holds every world's rows once, so each is still on one page. The world is what combines
kinds — no row unions searches, which would leave it with no search to open or see in
full.

A spin draws the viewer's next world from a shuffle bag of their own (`world_for`). The
bag moves on a spin rather than on the calendar, so a viewer who comes by every few days
still meets every world once a cycle. A user's first spin of the UTC day is counted and
the world it drew kept (`discover_progress`), so any later one that day lands there, and a
release editing the worlds leaves the day's world in place unless it drops it — only the
bag reshuffles. A guest is read-only and cannot spin: the day stands in for its count, so
its world for the day is always there, though with nothing kept an edit may change it.

A row starts on what the viewer hasn't watched. A big pool draws at random over its
better part, since a world comes back every few spins and a top-rated order would lead
with the same anime each time. A description row draws at random whatever its size: its
query picks a set rather than ranking one, and its Top N% cuts the tiny shows that merely
say the word.

The wheel decides nothing: the spin returns the drawn world first and the wheel turns onto
it. A world's look is the frontend's (`utils/discoverWorlds.ts`), keyed by world key. A
fresh spin then cuts to the world under a full-screen reveal: the tab swaps under its flash,
so the cut is never seen, and the rows load behind its title card (`WorldReveal.svelte`).
The dev-only `?reveal=<key>` spins the wheel onto any world through an admin-only preview
(`GET /browse/worlds/{world}`) that counts no spin: how a world and its reveal are checked
without waiting for the draw.

## A thin row widens

`widened` (`stores/browseRefinements.ts`) steps a carousel's default Top 50% up to Top 75%
where it leaves fewer than `WIDEN_BELOW` — that one step, so a row widens into its better
part rather than its whole pool — and only while the viewer hasn't chosen in the Top group.
The row and its see-all both list through `carouselResults` (`stores/browseRows.ts`), so the
two agree; the see-all takes the widened step as its default, what Reset returns to, so a
chosen step is recorded even where it is a default (`selectInGroup`). A count that widened
is remembered, for the toggles it ran under, so the see-all and a return start at 75%
without counting again or passing through 50%. Rows set Top 50% and let this lift a small
pool, rather than defaulting to 75% themselves.

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

Every carousel is listed for everyone, a guest included. For a guest, `refinedSearch`
first drops, with `forGuest`, any filter every anime passes for one, so the row, its
see-all and Open in search run the same search. One still over the caller's own ratings
or watchlist resolves for a guest too; [the search it runs](search.md#personal-filters-and-sort)
is where a guest is refused, so the row shows a guest why instead of running it. It
decides "personal" with `readsOwnData`, the same test that strips a guest's shared link
and leaves a see-all's toggle over the caller's data inert.

---

**Why it is this way**
- [Browse + News](../../compound-docs/2026-10-10-v0.16.2-browse.md) — the decisions behind the definition tables, the see-all routes and the tiles
- [Home + Discover](../../compound-docs/2026-10-12-v0.16.3-home-and-discover.md) — the worlds, the draw, and the count and overlap studies behind Discover's rows
