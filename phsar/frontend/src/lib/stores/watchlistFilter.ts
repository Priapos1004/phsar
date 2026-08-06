import type { WatchlistGrain, WatchlistSortKey, WatchlistView } from '$lib/utils/watchlistStats';
import { PRIORITY_OPTIONS } from '$lib/utils/watchlist';
import { createPersistedFilter, pickKey, pickNumbers, pickStrings } from './persistedFilter';

export type WatchlistTabKey = 'watchlists' | 'tags' | 'stats';
type Direction = 'asc' | 'desc';

export interface WatchlistFilterState {
	view: WatchlistView;
	grain: WatchlistGrain; // anime (default, aggregated) vs media (one card per entry)
	tagUuids: string[]; // multi-select union — [] = all tags
	priorities: number[]; // multi-select union of priority bands — [] = all
	sort: WatchlistSortKey; // table column sort
	sortDir: Direction;
}

export const DEFAULT_WATCHLIST_FILTER: WatchlistFilterState = {
	view: 'grid',
	grain: 'anime',
	tagUuids: [],
	priorities: [],
	sort: 'priority',
	sortDir: 'asc',
};

// Rehydration whitelists — see `pickKey`.
const VIEWS: Record<WatchlistView, true> = { grid: true, table: true };
const GRAINS: Record<WatchlistGrain, true> = { anime: true, media: true };
const DIRECTIONS: Record<Direction, true> = { asc: true, desc: true };
const SORT_KEYS: Record<WatchlistSortKey, true> = {
	title: true,
	priority: true,
	date: true,
	note: true,
};
const PRIORITY_VALUES: readonly number[] = PRIORITY_OPTIONS.map((o) => o.value);

// `tagUuids` needs no key set here: WatchlistFilterBar already prunes uuids
// that aren't in the loaded `tags` store, so a rehydrated filter pointing at a
// deleted list collapses to "all" on mount rather than rendering nothing.
function sanitize(raw: Record<string, unknown>): WatchlistFilterState {
	return {
		view: pickKey(raw.view, VIEWS, DEFAULT_WATCHLIST_FILTER.view),
		grain: pickKey(raw.grain, GRAINS, DEFAULT_WATCHLIST_FILTER.grain),
		tagUuids: pickStrings(raw.tagUuids),
		priorities: pickNumbers(raw.priorities).filter((p) => PRIORITY_VALUES.includes(p)),
		sort: pickKey(raw.sort, SORT_KEYS, DEFAULT_WATCHLIST_FILTER.sort),
		sortDir: pickKey(raw.sortDir, DIRECTIONS, DEFAULT_WATCHLIST_FILTER.sortDir),
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
