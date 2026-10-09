import { describe, it, expect, vi } from 'vitest';
import {
	carryAcrossView,
	fetchAnimeSearchResults,
	filterChips,
	normalizeRated,
	omitKeys,
	stripForGuest,
	type MediaSearchFilters,
} from '$lib/utils/search';
import { sliderGrid, thumbValue, toGrid } from '$lib/components/DoubleRangeSlider.svelte';
import { api } from '$lib/api';

const BASE: MediaSearchFilters = { query: '', search_type: 'title' };

describe('sliderGrid', () => {
	// Death Note's vote count, the "Scored by" slider's max — off the 0.1 log grid, where
	// bits-ui's snap would read as a filter.
	const DEATH_NOTE = 3_023_456;

	it('puts both ends on the step grid, outside the bounds', () => {
		const grid = sliderGrid(0, DEATH_NOTE, 0.1, true);
		expect(grid.lo).toBe(0);
		expect(grid.hi).toBe(21.6);
		expect(2 ** grid.hi - 1).toBeGreaterThanOrEqual(DEATH_NOTE);
	});

	it('keeps an on-grid linear range as it is', () => {
		expect(sliderGrid(0, 10, 0.01)).toMatchObject({ lo: 0, hi: 10 });
		expect(sliderGrid(90, 7230, 60)).toMatchObject({ lo: 60, hi: 7260 });
	});
});

describe('thumbValue', () => {
	const grid = sliderGrid(0, 3_023_456, 0.1, true);

	it('reads a thumb at its end of the track as no filter', () => {
		expect(thumbValue(grid.lo, undefined, 'min', grid)).toBeUndefined();
		expect(thumbValue(grid.hi, undefined, 'max', grid)).toBeUndefined();
	});

	it('keeps an untouched value verbatim rather than its snapped position', () => {
		// 10,000 sits at log2 13.29, which the grid snaps to 13.3 — 10,085.
		expect(thumbValue(toGrid(10_000, grid), 10_000, 'min', grid)).toBe(10_000);
	});

	it('reads a moved thumb off the grid', () => {
		expect(thumbValue(13.3, undefined, 'min', grid)).toBe(Math.round(2 ** 13.3 - 1));
		expect(thumbValue(13.3, 500, 'max', grid)).toBe(Math.round(2 ** 13.3 - 1));
	});
});

describe('filterChips', () => {
	it('is empty for a verified token whose fields are all unset', () => {
		const verified = {
			...BASE, genre_name: null, genre_mode: 'all', studio_mode: 'any', score_min: null,
			top_percent: null, upcoming_main: false, rated: null, watchlisted: null,
		} as MediaSearchFilters;
		expect(filterChips(verified, 'anime')).toEqual([]);
	});

	it('names each applied group once, with what removing it clears', () => {
		const chips = filterChips({
			...BASE,
			rated: ['none', 'dropped'], watchlisted: false, top_percent: 20,
			genre_name: ['Action', 'Comedy'], studio_name: ['MAPPA', 'Bones'], studio_mode: 'all',
			scored_by_max: 2_965_820, score_min: 8, score_max: 10,
		}, 'anime');
		expect(chips.map((c) => [c.label, c.keys])).toEqual([
			['Unrated or Dropped', ['rated']],
			['Not in watchlist', ['watchlisted']],
			['Top 20%', ['top_percent']],
			['Genres: Action & Comedy', ['genre_name', 'genre_mode']],
			['Studios: MAPPA & Bones', ['studio_name', 'studio_mode']],
			['Score 8.00–10.00', ['score_min', 'score_max']],
			['Scored by ≤ 2,965,820', ['scored_by_min', 'scored_by_max']],
		]);
	});

	it('removing a chip clears exactly its keys', () => {
		const params = { ...BASE, genre_name: ['Action'], genre_mode: 'any' as const, top_percent: 5 };
		expect(omitKeys(params, ['genre_name', 'genre_mode'])).toEqual({ ...BASE, top_percent: 5 });
	});
});

describe('normalizeRated', () => {
	it('drops a selection of every state — six anime states would break the token cap', () => {
		const all = { ...BASE, rated: ['none', 'in_progress', 'on_hold', 'dropped', 'main', 'all'] as const };
		expect(normalizeRated({ ...all, rated: [...all.rated] }, 'anime').rated).toBeUndefined();
		expect(normalizeRated({ ...BASE, rated: ['none', 'main'] }, 'anime').rated).toEqual(['none', 'main']);
	});
});

describe('carryAcrossView', () => {
	// Every field set, so a field that should drop and doesn't shows up here.
	const FULL: Required<MediaSearchFilters> = {
		query: 'frieren', search_type: 'description', view_type: 'anime',
		relation_type: ['side_story'], media_type: ['TV'], age_rating: ['PG-13'], airing_status: ['Finished Airing'],
		anime_season: ['Fall 2023'], genre_name: ['Fantasy'], studio_name: ['Madhouse'], original_source: ['Manga'],
		genre_mode: 'any', studio_mode: 'all',
		score_min: 8, score_max: 10, scored_by_min: 1, scored_by_max: 2, episodes_min: 1, episodes_max: 2,
		duration_per_episode_min: 1, duration_per_episode_max: 2, total_watch_time_min: 1, total_watch_time_max: 2,
		top_percent: 10, upcoming_main: true, rated: ['in_progress', 'on_hold', 'dropped'], watchlisted: true,
	};

	it('keeps what means the same at both grains and drops the rest', () => {
		expect(carryAcrossView(FULL, 'media')).toEqual({
			query: 'frieren', search_type: 'description', view_type: 'media',
			media_type: ['TV'], age_rating: ['PG-13'], airing_status: ['Finished Airing'],
			anime_season: ['Fall 2023'], genre_name: ['Fantasy'], studio_name: ['Madhouse'], original_source: ['Manga'],
			genre_mode: 'any', studio_mode: 'all', score_min: 8, score_max: 10,
			top_percent: 10, upcoming_main: true, rated: ['on_hold', 'dropped'], watchlisted: true,
		});
	});

	it('drops the rated filter when no state survives', () => {
		expect(carryAcrossView({ ...BASE, rated: ['completed'] }, 'anime')).not.toHaveProperty('rated');
	});
});

describe('stripForGuest', () => {
	it('drops what reads your own ratings and watchlist, watchlisted=false included', () => {
		expect(stripForGuest({ ...BASE, watchlisted: false, genre_name: ['Action'] })).toEqual({
			params: { ...BASE, genre_name: ['Action'] }, stripped: true,
		});
		expect(stripForGuest({ ...BASE, rated: null, watchlisted: null })).toMatchObject({ stripped: false });
	});
});

describe('the search request', () => {
	it('sends watchlisted=false and repeats list values, but leaves unset fields out', async () => {
		const get = vi.spyOn(api, 'get').mockResolvedValue([]);
		await fetchAnimeSearchResults({ ...BASE, watchlisted: false, rated: ['none', 'dropped'], score_min: null });
		const params = get.mock.calls[0][1]!.params as URLSearchParams;
		expect(params.get('watchlisted')).toBe('false');
		expect(params.getAll('rated')).toEqual(['none', 'dropped']);
		expect(params.has('score_min')).toBe(false);
		expect(params.has('query')).toBe(false);
		get.mockRestore();
	});
});
