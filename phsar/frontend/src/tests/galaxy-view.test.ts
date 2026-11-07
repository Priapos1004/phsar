import { describe, it, expect } from 'vitest';
import { NO_FILTERS, sanitizeFilters } from '$lib/stores/galaxyView';
import type { MediaSearchFilters } from '$lib/utils/search';

describe('sanitizeFilters', () => {
	it('keeps a filter set the sheet wrote', () => {
		const filters: MediaSearchFilters = {
			...NO_FILTERS,
			studio_name: ['MAPPA'],
			studio_mode: 'all',
			airing_status: ['Finished Airing'],
			score_min: 7.5,
			total_watch_time_max: 36000,
			top_percent: 20,
			upcoming_main: true,
			rated: ['none', 'main'],
			watchlisted: false,
			your_score_min: 6.5,
			your_score_max: 9,
			your_top_percent: 25,
			genres: { mode: 'any', groups: [{ mode: 'all', include: ['Action'], exclude_mode: 'any', exclude: ['Ecchi'] }] }
		};
		expect(sanitizeFilters(filters)).toEqual(filters);
	});

	it('drops what no build of the sheet writes', () => {
		expect(
			sanitizeFilters({
				query: 'kept out',
				sort: 'score',
				studio_name: ['MAPPA', 3],
				studio_mode: 'some',
				score_min: 'high',
				top_percent: 0,
				your_top_percent: 101,
				your_score_min: 'high',
				upcoming_main: 'yes',
				rated: ['all', 'bogus'],
				watchlisted: 'no',
				genres: { mode: 'any', groups: Array(5).fill({ include: ['Action'] }) },
				colour: 'neon'
			})
		).toEqual({
			...NO_FILTERS,
			studio_name: ['MAPPA'],
			studio_mode: 'any',
			rated: ['all'],
			genres: {
				mode: 'any',
				groups: Array(3).fill({ mode: 'any', include: ['Action'], exclude_mode: 'any', exclude: [] })
			}
		});
	});

	it('reads anything that is not an object as no filters', () => {
		expect(sanitizeFilters('studio_name=MAPPA')).toEqual(NO_FILTERS);
		expect(sanitizeFilters(null)).toEqual(NO_FILTERS);
	});
});
