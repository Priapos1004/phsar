import { writable } from 'svelte/store';
import type { WatchlistGrain, WatchlistSortKey, WatchlistView } from '$lib/utils/watchlistStats';

export type WatchlistTabKey = 'watchlists' | 'tags';

export interface WatchlistFilterState {
	view: WatchlistView;
	grain: WatchlistGrain; // anime (default, aggregated) vs media (one card per entry)
	tagUuids: string[]; // multi-select union — [] = all tags
	priorities: number[]; // multi-select union of priority bands — [] = all
	sort: WatchlistSortKey; // table column sort
	sortDir: 'asc' | 'desc';
}

export const DEFAULT_WATCHLIST_FILTER: WatchlistFilterState = {
	view: 'grid',
	grain: 'anime',
	tagUuids: [],
	priorities: [],
	sort: 'priority',
	sortDir: 'asc',
};

// In-SPA memory for the /watchlist list controls — same deliberate choice as
// ratingsFilter: the `?tab=` param owns the URL, and these survive the
// watchlists↔tags tab switch without re-threading. Reset on leaving the section.
export const watchlistFilter = writable<WatchlistFilterState>({ ...DEFAULT_WATCHLIST_FILTER });

// Keep the chosen view + grain across a detail round-trip; reset the value filters.
export function clearWatchlistFilter(): void {
	watchlistFilter.update((f) => ({ ...DEFAULT_WATCHLIST_FILTER, view: f.view, grain: f.grain }));
}
