import type { WatchlistGrain, WatchlistSortKey, WatchlistView } from '$lib/utils/watchlistStats';
import type { ReadyFilterKey } from '$lib/utils/watchlistReady';
import {
	createPersistedFilter,
	DIRECTION_KEYS,
	GRAIN_KEYS,
	pickKey,
	pickNumbers,
	pickStrings,
	VIEW_KEYS,
	type Direction,
} from './persistedFilter';

export type WatchlistTabKey = 'watchlists' | 'tags' | 'stats';

export interface WatchlistFilterState {
	view: WatchlistView;
	grain: WatchlistGrain; // anime (default, aggregated) vs media (one card per entry)
	tagUuids: string[]; // multi-select union — [] = all tags
	priorities: number[]; // multi-select union of priority bands — [] = all
	readiness: ReadyFilterKey[]; // multi-select union of readiness verdicts — [] = all
	sort: WatchlistSortKey; // table column sort
	sortDir: Direction;
}

export const DEFAULT_WATCHLIST_FILTER: WatchlistFilterState = {
	view: 'grid',
	grain: 'anime',
	tagUuids: [],
	priorities: [],
	readiness: [],
	sort: 'priority',
	sortDir: 'asc',
};

// Rehydration whitelists — see `pickKey`. View/grain/direction come from
// persistedFilter; only the sort keys are section-specific.
const SORT_KEYS: Record<WatchlistSortKey, true> = {
	title: true,
	priority: true,
	date: true,
	note: true,
};
// The three priority bands, inlined rather than derived from
// `utils/watchlist.PRIORITY_OPTIONS`: this store is reachable from the ROOT
// layout (via filterLifecycle), and that import chain pulls `utils/color`'s
// wheel builder into every route's entry chunk — including /login.
const PRIORITY_VALUES: readonly number[] = [1, 2, 3];
// A key set rather than an array, like SORT_KEYS above: TypeScript checks it covers the
// union, so adding a chip without listing it here is a compile error rather than a filter
// value that silently vanishes on rehydration.
//
// Spelled out rather than derived from `READY_FILTERS` for the same reason as
// PRIORITY_VALUES: this store is reachable from the ROOT layout, and that import chain
// would pull the readiness rules into every route's entry chunk, /login included.
const READINESS_KEYS: Record<ReadyFilterKey, true> = { ready: true, hot: true, waiting: true };

// `tagUuids` needs no key set here: WatchlistFilterBar already prunes uuids
// that aren't in the loaded `tags` store, so a rehydrated filter pointing at a
// deleted list collapses to "all" on mount rather than rendering nothing.
function sanitize(raw: Record<string, unknown>): WatchlistFilterState {
	return {
		view: pickKey(raw.view, VIEW_KEYS, DEFAULT_WATCHLIST_FILTER.view),
		grain: pickKey(raw.grain, GRAIN_KEYS, DEFAULT_WATCHLIST_FILTER.grain),
		tagUuids: pickStrings(raw.tagUuids),
		priorities: pickNumbers(raw.priorities).filter((p) => PRIORITY_VALUES.includes(p)),
		// Whitelisted like the priority bands — a rehydrated key the chips no longer
		// offer would filter everything out with no way to clear it from the UI.
		readiness: pickStrings(raw.readiness).filter((k): k is ReadyFilterKey =>
			Object.hasOwn(READINESS_KEYS, k),
		),
		sort: pickKey(raw.sort, SORT_KEYS, DEFAULT_WATCHLIST_FILTER.sort),
		sortDir: pickKey(raw.sortDir, DIRECTION_KEYS, DEFAULT_WATCHLIST_FILTER.sortDir),
	};
}

// In-SPA memory for the /watchlist list controls, mirrored to sessionStorage —
// same deliberate not-the-URL choice as ratingsFilter: the `?tab=` param owns
// the URL, and these survive the watchlists↔tags tab switch without re-threading.
export const watchlistFilter = createPersistedFilter<WatchlistFilterState>({
	key: 'phsar.filter.watchlist',
	version: 1,
	defaults: DEFAULT_WATCHLIST_FILTER,
	sanitize,
});

/** Reset the value filters, keeping view + grain; fired by `utils/filterLifecycle`. */
export function clearWatchlistFilter(): void {
	watchlistFilter.update((f) => ({ ...DEFAULT_WATCHLIST_FILTER, view: f.view, grain: f.grain }));
}
