import { writable } from 'svelte/store';
import type { SortKey } from '$lib/utils/ratingStats';
import type { StatsSection } from '$lib/components/ratings/types';

export type RatingsView = 'grid' | 'table';

export interface RatingsFilterState {
	view: RatingsView;
	sort: SortKey; // table column sort
	sortDir: 'asc' | 'desc';
	bandDir: 'asc' | 'desc'; // grid score-band section order (desc = 10 on top)
	statsSection: StatsSection; // active Statistics inner section
	genres: string[];
	genreMode: 'any' | 'all';
	ageRatings: number[]; // selected age_rating_numeric buckets; any-match
	seasons: string[]; // selected "Spring 2021" seasons; any-match
}

export const DEFAULT_RATINGS_FILTER: RatingsFilterState = {
	view: 'grid',
	sort: 'score',
	sortDir: 'desc',
	bandDir: 'desc',
	statsSection: 'overview',
	genres: [],
	genreMode: 'any',
	ageRatings: [],
	seasons: [],
};

// In-SPA memory for the /ratings list controls (view, sort, genre filter). Lives
// in a module store (not the URL) — the same deliberate choice as adminJobsFilter:
// the `?tab=` param already owns the URL, and these survive the ratings↔stats tab
// switch without re-threading.
export const ratingsFilter = writable<RatingsFilterState>({ ...DEFAULT_RATINGS_FILTER });

// Reset filters/sort when leaving the section, but KEEP the chosen view + stats
// section: clicking an anime / a chart point → detail page → "Back to …" should land
// on the same grid/table view and the same stats section the user was browsing. (The
// module store survives the route round-trip; a hard refresh re-initialises to default.)
export function clearRatingsFilter(): void {
	ratingsFilter.update((f) => ({ ...DEFAULT_RATINGS_FILTER, view: f.view, statsSection: f.statsSection }));
}
