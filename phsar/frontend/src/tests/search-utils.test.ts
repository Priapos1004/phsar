import { describe, it, expect, vi } from 'vitest';
import {
	carryAcrossView,
	effectiveSort,
	fetchAnimeSearchResults,
	filterChips,
	forGuest,
	normalizeRated,
	omitKeys,
	sortLine,
	unusualAnnouncedType,
	stripForGuest,
	withQuery,
	type MediaSearchFilters,
} from '$lib/utils/search';
import type { AnimeSearchResult, MediaSearchResult } from '$lib/types/api';
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

	it('reads a thumb whose value reaches the bound as no filter', () => {
		// Episodes from 1: positions 1.1–1.3 all read 1.
		const episodes = sliderGrid(1, 1100, 0.1, true);
		for (const position of [1.1, 1.2, 1.3]) expect(thumbValue(position, undefined, 'min', episodes)).toBeUndefined();
		expect(thumbValue(0.3, undefined, 'min', grid)).toBeUndefined();
		// A bound whose position rounds up: the end at 1.5 reads 2, the bound, not a step past it.
		const fromTwo = sliderGrid(2, 1100, 0.1, true);
		expect(thumbValue(fromTwo.lo, undefined, 'min', fromTwo)).toBeUndefined();
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
		sort: 'release', sort_dir: 'desc',
	};

	it('keeps what means the same at both grains and drops the rest', () => {
		expect(carryAcrossView(FULL, 'media')).toEqual({
			query: 'frieren', search_type: 'description', view_type: 'media',
			media_type: ['TV'], age_rating: ['PG-13'], airing_status: ['Finished Airing'],
			anime_season: ['Fall 2023'], genre_name: ['Fantasy'], studio_name: ['Madhouse'], original_source: ['Manga'],
			genre_mode: 'any', studio_mode: 'all', score_min: 8, score_max: 10,
			top_percent: 10, upcoming_main: true, rated: ['on_hold', 'dropped'], watchlisted: true,
			sort: 'release', sort_dir: 'desc',
		});
	});

	it('drops the rated filter when no state survives', () => {
		expect(carryAcrossView({ ...BASE, rated: ['completed'] }, 'anime')).not.toHaveProperty('rated');
	});
});

describe('forGuest', () => {
	it('drops a filter every anime passes for a guest, and keeps one none would', () => {
		expect(forGuest({ ...BASE, rated: ['none', 'in_progress'], watchlisted: false, sort: 'random' })).toEqual({
			...BASE, sort: 'random',
		});
		expect(forGuest({ ...BASE, rated: ['in_progress'], watchlisted: true })).toEqual({
			...BASE, rated: ['in_progress'], watchlisted: true,
		});
	});
});

describe('stripForGuest', () => {
	it('drops what reads your own ratings and watchlist, watchlisted=false included', () => {
		expect(stripForGuest({ ...BASE, watchlisted: false, genre_name: ['Action'] })).toEqual({
			params: { ...BASE, genre_name: ['Action'] }, stripped: true,
		});
		expect(stripForGuest({ ...BASE, rated: null, watchlisted: null, sort: 'score' })).toMatchObject({ stripped: false });
	});

	it('drops a sort by your rating and turns a notes search into a title search', () => {
		expect(stripForGuest({ query: 'cozy', search_type: 'rating_notes', sort: 'your_rating', sort_dir: 'asc' })).toEqual({
			params: { query: 'cozy', search_type: 'title' }, stripped: true,
		});
	});
});

describe('effectiveSort', () => {
	it('reads relevance as top rated without a query, since that is the order the results are in', () => {
		expect(effectiveSort(BASE)).toMatchObject({ sort: 'top_rated', dir: 'desc' });
		expect(effectiveSort({ ...BASE, sort: 'relevance' })).toMatchObject({ sort: 'top_rated', dir: 'desc' });
		expect(effectiveSort({ ...BASE, query: 'frieren' })).toMatchObject({ sort: 'relevance', dir: null });
		expect(effectiveSort({ ...BASE, sort: 'relevance', sort_dir: 'asc' })).toMatchObject({ sort: 'top_rated', dir: 'desc' });
	});

	it('gives a shuffle no direction', () => {
		expect(effectiveSort({ ...BASE, sort: 'random', sort_dir: 'asc' })).toMatchObject({ sort: 'random', dir: null });
	});

	it("takes each key's default direction unless one is set", () => {
		expect(effectiveSort({ ...BASE, sort: 'title' }).dir).toBe('asc');
		expect(effectiveSort({ ...BASE, sort: 'release' }).dir).toBe('asc');
		expect(effectiveSort({ ...BASE, sort: 'score' }).dir).toBe('desc');
		expect(effectiveSort({ ...BASE, sort: 'aired' }).dir).toBe('desc');
		expect(effectiveSort({ ...BASE, sort: 'title', sort_dir: 'desc' }).dir).toBe('desc');
	});
});

describe('withQuery', () => {
	const sorted: MediaSearchFilters = { ...BASE, query: 'frieren', sort: 'added', sort_dir: 'asc', genre_name: ['Fantasy'] };

	it('starts a different query from Best match, keeping the filters', () => {
		expect(withQuery(sorted, 'dungeon meshi', 'title')).toEqual({
			...BASE, query: 'dungeon meshi', genre_name: ['Fantasy'],
		});
	});

	it('keeps the sort for the same query, padded or in another mode', () => {
		expect(withQuery(sorted, ' frieren ', 'description')).toMatchObject({ sort: 'added', sort_dir: 'asc' });
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

describe('sortLine', () => {
	const anime = {
		avg_score: 8.42, avg_scored_by: 1_234_567, added_at: '2026-10-03T12:00:00Z',
		score_top_percent: 12, sort_season: 'Winter 2030', your_rating: 7.333,
		announced_at: '2026-10-09T12:00:00Z',
	} as unknown as AnimeSearchResult;
	const media = { ...anime, score: 6.1, scored_by: 900 } as unknown as MediaSearchResult;

	it.each([
		['top_rated', 'Top 12%'],
		['score', '⭐ 8.42'],
		['popularity', '1,234,567 votes'],
		['added', 'Added Oct 3'],
		['announced', 'Announced Oct 9'],
		['release', 'Winter 2030'],
		['aired', 'Winter 2030'],
		['your_rating', 'You: 7.33'],
		['title', null],
		['random', null],
		['relevance', null],
	] as const)('shows what %s orders by', (sort, line) => {
		expect(sortLine(sort, anime, 0.5)).toBe(line);
	});

	it('reads the media grain its own score and votes', () => {
		const row = { ...media } as Record<string, unknown>;
		delete row.avg_score;
		delete row.avg_scored_by;
		expect(sortLine('score', row as unknown as MediaSearchResult, 0.5)).toBe('⭐ 6.1');
		expect(sortLine('popularity', row as unknown as MediaSearchResult, 0.5)).toBe('900 votes');
	});

	it('shows nothing where the row has no value for the order', () => {
		const bare = { avg_score: null, avg_scored_by: 0, added_at: '2026-10-03T12:00:00Z' } as unknown as AnimeSearchResult;
		expect(sortLine('top_rated', bare, 0.5)).toBeNull();
		expect(sortLine('score', bare, 0.5)).toBeNull();
		expect(sortLine('release', bare, 0.5)).toBeNull();
		expect(sortLine('your_rating', bare, 0.5)).toBeNull();
		expect(sortLine('announced', bare, 0.5)).toBeNull();
	});
});

describe('unusualAnnouncedType', () => {
	const franchise = (announced: string | null, types: [string, number][]) => ({
		announced_type: announced,
		main_story_types: types.map(([media_type, count]) => ({ media_type, count })),
	}) as unknown as AnimeSearchResult;

	it('names a movie announced for a TV show', () => {
		expect(unusualAnnouncedType(franchise('Movie', [['TV', 3], ['Movie', 1]]))).toBe('Movie');
	});

	it('leaves the announcement out of what the franchise usually is', () => {
		// One season and the announced movie: counted in, the movie would tie the TV.
		expect(unusualAnnouncedType(franchise('Movie', [['TV', 1], ['Movie', 1]]))).toBe('Movie');
		expect(unusualAnnouncedType(franchise('TV', [['TV', 1], ['Movie', 1]]))).toBe('TV');
		// An anime that is only its announcement has nothing to differ from.
		expect(unusualAnnouncedType(franchise('TV', [['TV', 1]]))).toBeNull();
	});

	it('names nothing when the announcement is what the franchise usually is', () => {
		expect(unusualAnnouncedType(franchise('ONA', [['ONA', 2]]))).toBeNull();
		expect(unusualAnnouncedType(franchise('TV', [['TV', 2], ['Movie', 1]]))).toBeNull();
	});

	it('names nothing outside the announcement sort, where no type is carried', () => {
		expect(unusualAnnouncedType(franchise(null, [['TV', 1]]))).toBeNull();
	});

	it('names nothing on a tie, whatever the types are called', () => {
		expect(unusualAnnouncedType(franchise('TV', [['TV', 2], ['Movie', 1]]))).toBeNull();
		expect(unusualAnnouncedType(franchise('Movie', [['TV', 1], ['Movie', 2]]))).toBeNull();
	});
});
