import { describe, it, expect, vi } from 'vitest';
import {
	carryAcrossView,
	describeGenres,
	effectiveSort,
	fetchAnimeSearchResults,
	filterChips,
	forGuest,
	checkGenres,
	matchesGenres,
	normalizeFilters,
	omitKeys,
	sortLine,
	unusualAnnouncedType,
	stripForGuest,
	withQuery,
	type GenreFilter,
	type GenreGroup,
	type MediaSearchFilters,
} from '$lib/utils/search';
import type { AnimeSearchResult, MediaSearchResult } from '$lib/types/api';
import { sliderGrid, thumbValue, toGrid } from '$lib/components/DoubleRangeSlider.svelte';
import { api } from '$lib/api';

const BASE: MediaSearchFilters = { query: '', search_type: 'title' };

const group = (
	include: string[], exclude: string[] = [], mode: GenreGroup['mode'] = 'all', exclude_mode: GenreGroup['mode'] = 'any',
): GenreGroup => ({ mode, include, exclude_mode, exclude });
const genres = (mode: GenreFilter['mode'], ...groups: GenreGroup[]): GenreFilter => ({ mode, groups });

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
			...BASE, genres: null, studio_mode: 'any', score_min: null,
			top_percent: null, upcoming_main: false, rated: null, watchlisted: null,
		} as MediaSearchFilters;
		expect(filterChips(verified, 'anime')).toEqual([]);
	});

	it('names each applied group once, with what removing it clears', () => {
		const chips = filterChips({
			...BASE,
			rated: ['none', 'dropped'], watchlisted: false, top_percent: 20,
			genres: genres('all', group(['Action', 'Comedy'])), studio_name: ['MAPPA', 'Bones'], studio_mode: 'all',
			scored_by_max: 2_965_820, score_min: 8, score_max: 10,
		}, 'anime');
		expect(chips.map((c) => [c.label, c.keys])).toEqual([
			['Rated: Unrated or Dropped', ['rated']],
			['Not in watchlist', ['watchlisted']],
			['Top 20%', ['top_percent']],
			['Genres: Action & Comedy', ['genres']],
			['Studios: MAPPA & Bones', ['studio_name', 'studio_mode']],
			['Score 8.00–10.00', ['score_min', 'score_max']],
			['Scored by ≤ 2,965,820', ['scored_by_min', 'scored_by_max']],
		]);
	});

	it('removing a chip clears exactly its keys', () => {
		const params = { ...BASE, studio_name: ['MAPPA'], studio_mode: 'all' as const, top_percent: 5 };
		expect(omitKeys(params, ['studio_name', 'studio_mode'])).toEqual({ ...BASE, top_percent: 5 });
	});

	it('marks a genre chip whose groups can never match, or always do', () => {
		const [never] = filterChips({ ...BASE, genres: genres('all', group(['Drama']), group([], ['Drama'])) }, 'anime');
		const [idle] = filterChips({ ...BASE, genres: genres('any', group(['Drama'], ['Ecchi']), group(['Drama'])) }, 'anime');
		expect(idle.warning).toMatch(/^Group 1 changes nothing/);
		expect(never.label).toBe('Genres: Drama AND without Drama');
		expect(never.warning).toMatch(/no anime can match/i);
		const [fine] = filterChips({ ...BASE, genres: genres('all', group(['Drama'], ['Ecchi'])) }, 'anime');
		expect(fine.warning).toBeUndefined();
	});

	it('shows no genre chip for a group with nothing in it', () => {
		expect(filterChips({ ...BASE, genres: genres('all', group([])) }, 'anime')).toEqual([]);
	});
});

describe('normalizeFilters', () => {
	it('drops a selection of every state — six anime states would break the token cap', () => {
		const all = { ...BASE, rated: ['none', 'in_progress', 'on_hold', 'dropped', 'main', 'all'] as const };
		expect(normalizeFilters({ ...all, rated: [...all.rated] }, 'anime', {}).rated).toBeUndefined();
		expect(normalizeFilters({ ...BASE, rated: ['none', 'main'] }, 'anime', {}).rated).toEqual(['none', 'main']);
	});

	const offered = { airing_status: ['Finished Airing', 'Currently Airing'], studio_name: ['MAPPA', 'Bones'] };

	it('drops a list holding every offered option when it matches any of them', () => {
		const every = normalizeFilters({ ...BASE, airing_status: ['Currently Airing', 'Finished Airing'] }, 'anime', offered);
		expect(every.airing_status).toBeUndefined();
		const some = normalizeFilters({ ...BASE, airing_status: ['Currently Airing'] }, 'anime', offered);
		expect(some.airing_status).toEqual(['Currently Airing']);
	});

	it('keeps every offered option of a list some media leave blank — dropping it would add them', () => {
		const anyStudio = normalizeFilters({ ...BASE, studio_name: ['Bones', 'MAPPA'] }, 'anime', offered);
		expect(anyStudio.studio_name).toEqual(['Bones', 'MAPPA']);
	});

	it('drops an empty genre group and nothing else, a contradiction included', () => {
		const built = genres('all', group(['Drama']), group([]), group([], ['Drama']));
		expect(normalizeFilters({ ...BASE, genres: built }, 'anime', offered).genres).toEqual(
			genres('all', group(['Drama']), group([], ['Drama'])),
		);
		expect(normalizeFilters({ ...BASE, genres: genres('any', group([])) }, 'anime', offered).genres).toBeUndefined();
	});
});

describe('carryAcrossView', () => {
	// Every field set, so a field that should drop and doesn't shows up here.
	const FULL: Required<MediaSearchFilters> = {
		query: 'frieren', search_type: 'description', view_type: 'anime',
		relation_type: ['side_story'], media_type: ['TV'], age_rating: ['PG-13'], airing_status: ['Finished Airing'],
		anime_season: ['Fall 2023'], studio_name: ['Madhouse'], original_source: ['Manga'],
		studio_mode: 'all', genres: genres('any', group(['Fantasy'])),
		score_min: 8, score_max: 10, scored_by_min: 1, scored_by_max: 2, episodes_min: 1, episodes_max: 2,
		duration_per_episode_min: 1, duration_per_episode_max: 2, total_watch_time_min: 1, total_watch_time_max: 2,
		top_percent: 10, upcoming_main: true, rated: ['in_progress', 'on_hold', 'dropped'], watchlisted: true,
		sort: 'release', sort_dir: 'desc',
	};

	it('keeps what means the same at both grains and drops the rest', () => {
		expect(carryAcrossView(FULL, 'media')).toEqual({
			query: 'frieren', search_type: 'description', view_type: 'media',
			media_type: ['TV'], age_rating: ['PG-13'], airing_status: ['Finished Airing'],
			anime_season: ['Fall 2023'], studio_name: ['Madhouse'], original_source: ['Manga'],
			studio_mode: 'all', genres: genres('any', group(['Fantasy'])), score_min: 8, score_max: 10,
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
		expect(stripForGuest({ ...BASE, watchlisted: false, genres: genres('all', group(['Action'])) })).toEqual({
			params: { ...BASE, genres: genres('all', group(['Action'])) }, stripped: true,
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
	const sorted: MediaSearchFilters = { ...BASE, query: 'frieren', sort: 'added', sort_dir: 'asc', studio_name: ['MAPPA'] };

	it('starts a different query from Best match, keeping the filters', () => {
		expect(withQuery(sorted, 'dungeon meshi', 'title')).toEqual({
			...BASE, query: 'dungeon meshi', studio_name: ['MAPPA'],
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

	it('sends the genre groups as one JSON param', async () => {
		const get = vi.spyOn(api, 'get').mockResolvedValue([]);
		const sent = genres('any', group(['Fantasy', 'Isekai']), group(['Romance'], ['Drama']));
		await fetchAnimeSearchResults({ ...BASE, genres: sent });
		const params = get.mock.calls[0][1]!.params as URLSearchParams;
		expect(JSON.parse(params.get('genres')!)).toEqual(sent);
		get.mockRestore();
	});
});

describe('genre groups', () => {
	// The user's example: (Fantasy & Isekai) or (Romance & Comedy, without Drama).
	const example = genres('any', group(['Fantasy', 'Isekai']), group(['Romance', 'Comedy'], ['Drama']));
	const carrying = (...names: string[]) => (genre: string) => names.includes(genre);

	it('reads as words', () => {
		expect(describeGenres(example)).toBe('(Fantasy & Isekai) OR (Romance & Comedy, without Drama)');
		expect(describeGenres(genres('all', group(['Fantasy', 'Isekai'], ['Drama'], 'any')))).toBe(
			'Fantasy or Isekai, without Drama',
		);
		expect(describeGenres(genres('all', group([], ['Ecchi', 'Harem'])))).toBe('without Ecchi or Harem');
		expect(describeGenres(genres('all', group(['Romance'], ['Drama', 'Comedy'], 'all', 'all')))).toBe(
			'Romance, without Drama & Comedy together',
		);
		expect(describeGenres(genres('all', group(['Romance'], ['Drama'], 'all', 'all')))).toBe('Romance, without Drama');
		expect(describeGenres(genres('all', group(['Mecha']), group([]), group(['Space'], [], 'any')))).toBe(
			'Mecha AND Space',
		);
	});

	it('matches as the backend does', () => {
		expect(matchesGenres(example, carrying('Fantasy', 'Isekai', 'Drama'))).toBe(true);
		expect(matchesGenres(example, carrying('Romance', 'Comedy'))).toBe(true);
		expect(matchesGenres(example, carrying('Romance', 'Comedy', 'Drama'))).toBe(false);
		expect(matchesGenres(genres('all', group([], ['Drama'])), carrying())).toBe(true);
		expect(matchesGenres(genres('all', group(['A', 'B'], [], 'any'), group([], ['C'])), carrying('B', 'C'))).toBe(false);
		// Without Drama & Comedy together: either alone stays, both go.
		const notBoth = genres('all', group(['Romance'], ['Drama', 'Comedy'], 'all', 'all'));
		expect(matchesGenres(notBoth, carrying('Romance', 'Drama'))).toBe(true);
		expect(matchesGenres(notBoth, carrying('Romance', 'Drama', 'Comedy'))).toBe(false);
	});

	it.each([
		['a contradiction', genres('all', group(['Drama']), group([], ['Drama'])), 'never'],
		['a tautology', genres('any', group(['Drama']), group([], ['Drama'])), 'always'],
		['the example', example, null],
		// No anime may carry all three today, but one could.
		['a rare combination', genres('all', group(['Mecha', 'Sports', 'Isekai'])), null],
		['a contradiction spread over the groups', genres('all', group(['Drama', 'Romance'], [], 'any'), group([], ['Drama', 'Romance'])), 'never'],
		// Only Romance without Drama matches, so Drama, picked and excluded, has to be tried absent.
		['a match through a genre named both ways', genres('all', group(['Drama', 'Romance'], [], 'any'), group([], ['Drama'])), null],
		// Only Drama without Romance misses, so Drama has to be tried present.
		['a miss through a genre named both ways', genres('any', group([], ['Drama']), group(['Drama', 'Romance'])), null],
		['a tautology over three groups', genres('any', group(['A']), group(['B'], ['A']), group([], ['A', 'B'])), 'always'],
		['a near tautology', genres('any', group(['A']), group([], ['A', 'B'])), null],
		['not both, under all', genres('all', group(['Drama']), group([], ['Drama', 'Comedy'], 'all', 'all')), null],
		['never both, under all', genres('all', group(['Drama', 'Comedy']), group([], ['Drama', 'Comedy'], 'all', 'all')), 'never'],
	])('says whether %s can match', (_, built, warning) => {
		const expected = { never: /no anime can match/i, always: /every anime matches/i }[warning ?? ''];
		const check = checkGenres(built);
		if (expected) expect(check.warning).toMatch(expected);
		else expect(check.warning).toBeNull();
		expect(check.idle).toEqual([]);
	});

	it.each([
		// The sheet the user built: Romance alone covers Romance without Drama.
		['a group another covers, under any', genres('any',
			group(['Romance'], ['Drama']),
			group(['Isekai', 'Reincarnation', 'Fantasy', 'Adventure'], ['Urban Fantasy', 'Drama'], 'any'),
			group(['Romance']),
		), [0]],
		['two identical groups, the first of them', genres('any', group(['Romance']), group(['Mecha']), group(['Romance'])), [0]],
		['a group the others imply, under all', genres('all', group(['Romance']), group(['Romance'], ['Drama'])), [0]],
		['a group two others cover together', genres('any', group(['A', 'B'], [], 'any'), group(['A']), group(['B'])), [0]],
		['the empty group skipped in the numbering kept', genres('any', group([]), group(['A'], ['B']), group(['A'])), [1]],
		['groups that each add something', genres('any', group(['Romance'], ['Drama']), group(['Romance', 'Drama'])), []],
	])('flags %s as changing nothing', (_, built, idle) => {
		const check = checkGenres(built);
		expect(check.idle).toEqual(idle);
		if (idle.length) expect(check.warning).toMatch(new RegExp(`^Group ${idle[0] + 1} changes nothing`));
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
		['score', '8.42'],
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
		expect(sortLine('score', row as unknown as MediaSearchResult, 0.5)).toBe('6.1');
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
