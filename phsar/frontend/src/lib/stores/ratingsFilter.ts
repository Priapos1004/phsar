import { writable } from 'svelte/store';
import type { WatchStatus } from '$lib/types/api';
import type { SortKey } from '$lib/utils/ratingStats';

export type RatingsView = 'grid' | 'table';

export interface RatingsFilterState {
	view: RatingsView;
	sort: SortKey;
	sortDir: 'asc' | 'desc';
	genres: string[];
	genreMode: 'any' | 'all';
	statuses: WatchStatus[];
	scoreMin: number;
	scoreMax: number;
}

export const DEFAULT_RATINGS_FILTER: RatingsFilterState = {
	view: 'grid',
	sort: 'score',
	sortDir: 'desc',
	genres: [],
	genreMode: 'any',
	statuses: [],
	scoreMin: 0,
	scoreMax: 10,
};

// In-SPA memory for the /ratings list controls (view, sort, filters). Lives in a
// module store (not the URL) — the same deliberate choice as adminJobsFilter: the
// `?tab=` param already owns the URL, and these survive the ratings↔stats tab
// switch without re-threading. Cleared when the /ratings section unmounts (see
// routes/ratings/+layout.svelte) so a hard refresh / re-entry starts clean.
export const ratingsFilter = writable<RatingsFilterState>({ ...DEFAULT_RATINGS_FILTER });

export function clearRatingsFilter(): void {
	ratingsFilter.set({ ...DEFAULT_RATINGS_FILTER });
}
