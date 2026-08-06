import type { SortKey } from '$lib/utils/ratingStats';
import type { StatsSection } from '$lib/components/ratings/types';
import { createPersistedFilter, pickKey, pickNumbers, pickStrings } from './persistedFilter';

export type RatingsView = 'grid' | 'table';
export type RatingsGrain = 'anime' | 'media';
type Direction = 'asc' | 'desc';
type GenreMode = 'any' | 'all';

export interface RatingsFilterState {
	view: RatingsView;
	grain: RatingsGrain; // list rows: one per anime (default) or one per rated media
	sort: SortKey; // table column sort
	sortDir: Direction;
	bandDir: Direction; // grid score-band section order (desc = 10 on top)
	statsSection: StatsSection; // active Statistics inner section
	genres: string[];
	genreMode: GenreMode;
	ageRatings: number[]; // selected age_rating_numeric buckets; any-match
	seasons: string[]; // selected "Spring 2021" seasons; any-match
}

export const DEFAULT_RATINGS_FILTER: RatingsFilterState = {
	view: 'grid',
	grain: 'anime',
	sort: 'score',
	sortDir: 'desc',
	bandDir: 'desc',
	statsSection: 'overview',
	genres: [],
	genreMode: 'any',
	ageRatings: [],
	seasons: [],
};

// Rehydration whitelists — see `pickKey`.
const VIEWS: Record<RatingsView, true> = { grid: true, table: true };
const GRAINS: Record<RatingsGrain, true> = { anime: true, media: true };
const DIRECTIONS: Record<Direction, true> = { asc: true, desc: true };
const GENRE_MODES: Record<GenreMode, true> = { any: true, all: true };
const SORT_KEYS: Record<SortKey, true> = {
	score: true,
	title: true,
	date: true,
	mal: true,
	malDelta: true,
	status: true,
};
const STATS_SECTIONS: Record<StatsSection, true> = {
	overview: true,
	alignment: true,
	tags: true,
	attributes: true,
	activity: true,
};

// `genres` / `seasons` / `ageRatings` carry catalog values, so there is no fixed
// key set to check them against; a value the catalog no longer has just matches
// nothing, and the chip stays visible so the user can see why.
function sanitize(raw: Record<string, unknown>): RatingsFilterState {
	return {
		view: pickKey(raw.view, VIEWS, DEFAULT_RATINGS_FILTER.view),
		grain: pickKey(raw.grain, GRAINS, DEFAULT_RATINGS_FILTER.grain),
		sort: pickKey(raw.sort, SORT_KEYS, DEFAULT_RATINGS_FILTER.sort),
		sortDir: pickKey(raw.sortDir, DIRECTIONS, DEFAULT_RATINGS_FILTER.sortDir),
		bandDir: pickKey(raw.bandDir, DIRECTIONS, DEFAULT_RATINGS_FILTER.bandDir),
		statsSection: pickKey(raw.statsSection, STATS_SECTIONS, DEFAULT_RATINGS_FILTER.statsSection),
		genres: pickStrings(raw.genres),
		genreMode: pickKey(raw.genreMode, GENRE_MODES, DEFAULT_RATINGS_FILTER.genreMode),
		ageRatings: pickNumbers(raw.ageRatings),
		seasons: pickStrings(raw.seasons),
	};
}

// In-SPA memory for the /ratings list controls (view, sort, genre filter),
// mirrored to sessionStorage so a refresh keeps them too. Deliberately not the
// URL: the `?tab=` param already owns it, and these survive the ratings↔stats
// tab switch without re-threading.
export const ratingsFilter = createPersistedFilter<RatingsFilterState>({
	key: 'phsar.filter.ratings',
	version: 1,
	defaults: DEFAULT_RATINGS_FILTER,
	sanitize,
});

/** Reset the value filters; fired by `utils/filterLifecycle`. `view`/`grain`/
 * `statsSection` survive, so a detail round-trip or a refresh lands back on the
 * same grid/table view, grain and stats section the user was browsing. */
export function clearRatingsFilter(): void {
	ratingsFilter.update((f) => ({
		...DEFAULT_RATINGS_FILTER,
		view: f.view,
		grain: f.grain,
		statsSection: f.statsSection,
	}));
}
