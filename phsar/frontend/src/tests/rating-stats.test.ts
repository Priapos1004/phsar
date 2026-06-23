import { describe, it, expect } from 'vitest';
import type { RatingScoreItem, WatchStatus } from '$lib/types/api';
import {
	groupByAnime,
	filterItems,
	sortAnimeRows,
	toScoreBands,
	scoreHistogram,
	alignmentPoints,
	weightedLinearFit,
	spearman,
	tagMetrics,
	attributeCorrelations,
	attributeCategoryEffects,
	ratingSequence,
	movingAverage,
	cumulativeWatchTime,
	totalWatchTime,
} from '$lib/utils/ratingStats';

function item(o: Partial<RatingScoreItem> & { media_uuid: string; anime_uuid: string; rating: number }): RatingScoreItem {
	return {
		media_title: o.media_uuid,
		media_name_eng: null,
		media_name_jap: null,
		anime_title: o.anime_uuid,
		anime_name_eng: null,
		anime_name_jap: null,
		media_cover_image: null,
		anime_cover_image: null,
		watch_status: 'completed' as WatchStatus,
		age_rating_numeric: null,
		genres: [],
		studios: [],
		mal_score: null,
		scored_by: 0,
		episodes: null,
		total_watch_time: null,
		anime_season_name: null,
		anime_season_year: null,
		relation_type: 'main',
		pace: null,
		animation_quality: null,
		has_3d_animation: null,
		watched_format: null,
		fan_service: null,
		dialogue_quality: null,
		character_depth: null,
		ending_type: null,
		ending_quality: null,
		story_quality: null,
		originality: null,
		created_at: '2026-01-01T00:00:00Z',
		modified_at: '2026-01-01T00:00:00Z',
		...o,
	};
}

describe('groupByAnime', () => {
	it('averages media scores, unions genres, picks max modified_at, collapses status', () => {
		const rows = groupByAnime([
			item({ media_uuid: 'm1', anime_uuid: 'A', rating: 8, genres: ['Action'], mal_score: 7, scored_by: 100, anime_cover_image: 'a.jpg', modified_at: '2026-02-01T00:00:00Z' }),
			item({ media_uuid: 'm2', anime_uuid: 'A', rating: 6, genres: ['Drama'], watch_status: 'on_hold', mal_score: null, scored_by: 50, modified_at: '2026-03-01T00:00:00Z' }),
		]);
		expect(rows).toHaveLength(1);
		const r = rows[0];
		expect(r.userScore).toBe(7); // (8 + 6) / 2
		expect(r.malScore).toBe(7); // only m1 has a MAL score
		expect(r.malDelta).toBe(0); // 7 − 7
		expect(r.genres).toEqual(['Action', 'Drama']);
		expect(r.scoredBy).toBe(150);
		expect(r.ratedMediaCount).toBe(2);
		expect(r.statusBadge).toBe('on_hold');
		expect(r.modifiedAt).toBe('2026-03-01T00:00:00Z');
		expect(r.cover_image).toBe('a.jpg');
	});

	it('splits rated media into main (incl. alternative_version) vs side', () => {
		const [r] = groupByAnime([
			item({ media_uuid: '1', anime_uuid: 'A', rating: 8, relation_type: 'main' }),
			item({ media_uuid: '2', anime_uuid: 'A', rating: 8, relation_type: 'alternative_version' }),
			item({ media_uuid: '3', anime_uuid: 'A', rating: 8, relation_type: 'side_story' }),
			item({ media_uuid: '4', anime_uuid: 'A', rating: 8, relation_type: 'summary' }),
		]);
		expect(r.mainCount).toBe(2);
		expect(r.sideCount).toBe(2);
	});

	it('dropped beats on_hold in the status badge; null mal → null delta', () => {
		const [r] = groupByAnime([
			item({ media_uuid: 'm1', anime_uuid: 'A', rating: 5, watch_status: 'dropped' }),
			item({ media_uuid: 'm2', anime_uuid: 'A', rating: 5, watch_status: 'on_hold' }),
		]);
		expect(r.statusBadge).toBe('dropped');
		expect(r.malScore).toBeNull();
		expect(r.malDelta).toBeNull();
	});
});

describe('filterItems', () => {
	const items = [
		item({ media_uuid: 'a', anime_uuid: 'A', rating: 9, genres: ['Action', 'Comedy'] }),
		item({ media_uuid: 'b', anime_uuid: 'B', rating: 4, genres: ['Action'] }),
		item({ media_uuid: 'c', anime_uuid: 'C', rating: 7, genres: ['Comedy'] }),
	];
	const base = { genreMode: 'any' as const, ageRatings: [] as number[], seasons: [] as string[] };
	it('no filters → returns all', () => {
		expect(filterItems(items, { ...base, genres: [] })).toHaveLength(3);
	});
	it('genre any vs all', () => {
		const any = filterItems(items, { ...base, genres: ['Action', 'Comedy'], genreMode: 'any' });
		expect(any.map((i) => i.media_uuid)).toEqual(['a', 'b', 'c']);
		const all = filterItems(items, { ...base, genres: ['Action', 'Comedy'], genreMode: 'all' });
		expect(all.map((i) => i.media_uuid)).toEqual(['a']);
	});
	it('filters by age rating (any-match); excludes null age', () => {
		const aged = [
			item({ media_uuid: 'x', anime_uuid: 'X', rating: 8, age_rating_numeric: 13 }),
			item({ media_uuid: 'y', anime_uuid: 'Y', rating: 8, age_rating_numeric: 17 }),
			item({ media_uuid: 'z', anime_uuid: 'Z', rating: 8, age_rating_numeric: null }),
		];
		expect(filterItems(aged, { ...base, genres: [], ageRatings: [13, 17] }).map((i) => i.media_uuid)).toEqual(['x', 'y']);
		expect(filterItems(aged, { ...base, genres: [], ageRatings: [13] }).map((i) => i.media_uuid)).toEqual(['x']);
	});
	it('filters by season (any-match); excludes undated', () => {
		const seasoned = [
			item({ media_uuid: 'x', anime_uuid: 'X', rating: 8, anime_season_name: 'Spring', anime_season_year: 2021 }),
			item({ media_uuid: 'y', anime_uuid: 'Y', rating: 8, anime_season_name: 'Fall', anime_season_year: 2020 }),
			item({ media_uuid: 'z', anime_uuid: 'Z', rating: 8, anime_season_name: null, anime_season_year: null }),
		];
		expect(filterItems(seasoned, { ...base, genres: [], seasons: ['Spring 2021'] }).map((i) => i.media_uuid)).toEqual(['x']);
		expect(filterItems(seasoned, { ...base, genres: [], seasons: ['Spring 2021', 'Fall 2020'] }).map((i) => i.media_uuid)).toEqual(['x', 'y']);
	});
});

describe('sortAnimeRows + toScoreBands', () => {
	const rows = groupByAnime([
		item({ media_uuid: 'm1', anime_uuid: 'A', rating: 9.5, anime_name_eng: 'Zebra' }),
		item({ media_uuid: 'm2', anime_uuid: 'B', rating: 8.2, anime_name_eng: 'Alpha' }),
		item({ media_uuid: 'm3', anime_uuid: 'C', rating: 8.9, anime_name_eng: 'Mango' }),
	]);
	it('sorts by score desc', () => {
		expect(sortAnimeRows(rows, 'score', 'desc', 'english').map((r) => r.anime_uuid)).toEqual(['A', 'C', 'B']);
	});
	it('sorts by title asc', () => {
		expect(sortAnimeRows(rows, 'title', 'asc', 'english').map((r) => r.name_eng)).toEqual(['Alpha', 'Mango', 'Zebra']);
	});
	it('sorts by status asc (dropped < on_hold < completed)', () => {
		const statusRows = groupByAnime([
			item({ media_uuid: 'd', anime_uuid: 'D', rating: 5, watch_status: 'dropped', anime_name_eng: 'D' }),
			item({ media_uuid: 'h', anime_uuid: 'H', rating: 5, watch_status: 'on_hold', anime_name_eng: 'H' }),
			item({ media_uuid: 'c', anime_uuid: 'C', rating: 5, watch_status: 'completed', anime_name_eng: 'C' }),
		]);
		expect(sortAnimeRows(statusRows, 'status', 'asc', 'english').map((r) => r.anime_uuid)).toEqual(['D', 'H', 'C']);
	});
	it('bands by floored score, descending, empty bands omitted', () => {
		const bands = toScoreBands(sortAnimeRows(rows, 'title', 'asc', 'english'));
		expect(bands.map((b) => b.band)).toEqual([9, 8]);
		expect(bands[1].rows.map((r) => r.name_eng)).toEqual(['Alpha', 'Mango']); // 8.x band, title order
	});
});

describe('scoreHistogram', () => {
	it('buckets in fixed 0.5-wide bins', () => {
		const items = [
			item({ media_uuid: 'a', anime_uuid: 'A', rating: 8.0 }),
			item({ media_uuid: 'b', anime_uuid: 'B', rating: 8.0 }),
			item({ media_uuid: 'c', anime_uuid: 'C', rating: 8.5 }),
		];
		expect(scoreHistogram(items)).toEqual([
			{ center: 8.0, count: 2, main: 2, side: 0 },
			{ center: 8.5, count: 1, main: 1, side: 0 },
		]);
	});
	it('splits each bucket into main vs side counts', () => {
		const items = [
			item({ media_uuid: 'a', anime_uuid: 'A', rating: 8.0, relation_type: 'main' }),
			item({ media_uuid: 'b', anime_uuid: 'A', rating: 8.0, relation_type: 'alternative_version' }),
			item({ media_uuid: 'c', anime_uuid: 'A', rating: 8.0, relation_type: 'side_story' }),
		];
		// main + alternative_version count as "main"; everything else as "side".
		expect(scoreHistogram(items)).toEqual([{ center: 8.0, count: 3, main: 2, side: 1 }]);
	});
	it('snaps fine-grained scores to the nearest 0.5', () => {
		// 0.01-step ratings collapse into 0.5 bins (7.53 → 7.5, 8.37 → 8.5).
		const items = [
			item({ media_uuid: 'a', anime_uuid: 'A', rating: 7.5 }),
			item({ media_uuid: 'b', anime_uuid: 'B', rating: 7.53 }),
			item({ media_uuid: 'c', anime_uuid: 'C', rating: 8.37 }),
		];
		expect(scoreHistogram(items)).toEqual([
			{ center: 7.5, count: 2, main: 2, side: 0 },
			{ center: 8.0, count: 0, main: 0, side: 0 },
			{ center: 8.5, count: 1, main: 1, side: 0 },
		]);
	});
	it('fills the gap between min and max with empty buckets', () => {
		const items = [
			item({ media_uuid: 'a', anime_uuid: 'A', rating: 7.0 }),
			item({ media_uuid: 'b', anime_uuid: 'B', rating: 8.5 }),
		];
		expect(scoreHistogram(items)).toEqual([
			{ center: 7.0, count: 1, main: 1, side: 0 },
			{ center: 7.5, count: 0, main: 0, side: 0 },
			{ center: 8.0, count: 0, main: 0, side: 0 },
			{ center: 8.5, count: 1, main: 1, side: 0 },
		]);
	});
	it('empty input → []', () => {
		expect(scoreHistogram([])).toEqual([]);
	});
});

describe('weightedLinearFit', () => {
	it('recovers a known unweighted line y = 0.5x + 1', () => {
		const pts = [
			{ x: 2, y: 2, w: 1 },
			{ x: 4, y: 3, w: 1 },
			{ x: 6, y: 4, w: 1 },
		];
		const fit = weightedLinearFit(pts);
		expect(fit.ok).toBe(true);
		expect(fit.slope).toBeCloseTo(0.5, 6);
		expect(fit.intercept).toBeCloseTo(1, 6);
		expect(fit.r2).toBeCloseTo(1, 6);
	});
	it('weights pull the line toward heavy points', () => {
		const light = weightedLinearFit([
			{ x: 0, y: 0, w: 1 },
			{ x: 1, y: 10, w: 1 },
		]);
		expect(light.slope).toBeCloseTo(10, 6);
	});
	it('ok=false on n<2, constant x, constant y', () => {
		expect(weightedLinearFit([{ x: 1, y: 1, w: 1 }]).ok).toBe(false);
		expect(weightedLinearFit([{ x: 5, y: 1, w: 1 }, { x: 5, y: 9, w: 1 }]).ok).toBe(false);
		expect(weightedLinearFit([{ x: 1, y: 3, w: 1 }, { x: 9, y: 3, w: 1 }]).ok).toBe(false);
	});
});

describe('spearman', () => {
	it('perfectly monotonic (non-linear) → ρ = 1', () => {
		const pairs = [
			{ x: 1, y: 1 },
			{ x: 2, y: 4 },
			{ x: 3, y: 9 },
			{ x: 4, y: 16 },
		];
		expect(spearman(pairs).rho).toBeCloseTo(1, 6);
	});
	it('perfectly anti-monotonic → ρ = −1', () => {
		const pairs = [
			{ x: 1, y: 4 },
			{ x: 2, y: 3 },
			{ x: 3, y: 2 },
			{ x: 4, y: 1 },
		];
		expect(spearman(pairs).rho).toBeCloseTo(-1, 6);
	});
	it('handles ties via average ranks', () => {
		const res = spearman([
			{ x: 1, y: 1 },
			{ x: 1, y: 2 },
			{ x: 2, y: 2 },
			{ x: 3, y: 3 },
		]);
		expect(res.ok).toBe(true);
		expect(res.rho).toBeGreaterThan(0);
		expect(res.rho).toBeLessThanOrEqual(1);
	});
	it('ok=false on n<3 or zero rank variance', () => {
		expect(spearman([{ x: 1, y: 1 }, { x: 2, y: 2 }]).ok).toBe(false);
		expect(spearman([{ x: 5, y: 1 }, { x: 5, y: 2 }, { x: 5, y: 3 }]).ok).toBe(false);
	});
});

describe('alignmentPoints', () => {
	it('keeps only media with a MAL score; weight = log10(scored_by+1)', () => {
		const pts = alignmentPoints([
			item({ media_uuid: 'a', anime_uuid: 'A', rating: 8, mal_score: 7.5, scored_by: 9 }),
			item({ media_uuid: 'b', anime_uuid: 'B', rating: 6, mal_score: null, scored_by: 100 }),
		]);
		expect(pts).toHaveLength(1);
		expect(pts[0]).toMatchObject({ x: 7.5, y: 8 });
		expect(pts[0].w).toBeCloseTo(1, 6); // log10(9+1) = 1
	});
});

describe('tagMetrics (genre + studio)', () => {
	const items = [
		// a + b are two media of the SAME anime A → count once at the anime grain.
		item({ media_uuid: 'a', anime_uuid: 'A', rating: 9, genres: ['Action'], studios: ['MAPPA'], total_watch_time: 7200 }),
		item({ media_uuid: 'b', anime_uuid: 'A', rating: 5, genres: ['Action'], studios: ['MAPPA'], total_watch_time: 3600 }),
		item({ media_uuid: 'c', anime_uuid: 'B', rating: 7, genres: ['Action'], studios: ['Bones'], total_watch_time: 1800 }),
		item({ media_uuid: 'd', anime_uuid: 'C', rating: 7, genres: ['Comedy'], studios: ['Kyoto'], total_watch_time: 1800 }),
	];
	it('counts distinct anime (not media), sums media-level watch time', () => {
		const g = tagMetrics(items, 'genres');
		// Action spans 3 media but only 2 anime (A, B); watch time is the media sum.
		expect(g.find((t) => t.tag === 'Action')).toMatchObject({ avg: 7, count: 2, watchSeconds: 12600 });
		// MAPPA = anime A's two media → 1 distinct anime, watch time summed.
		expect(tagMetrics(items, 'studios').find((t) => t.tag === 'MAPPA')).toMatchObject({ count: 1, watchSeconds: 10800 });
	});
	it('normalizes the composite so exactly the strongest tag is 1', () => {
		const g = tagMetrics(items, 'genres');
		// Action: more anime + more watch time at the same avg → strongest.
		expect(g.find((t) => t.tag === 'Action')!.weighted).toBe(1);
		const comedy = g.find((t) => t.tag === 'Comedy')!.weighted;
		expect(comedy).toBeGreaterThan(0);
		expect(comedy).toBeLessThan(1);
		expect(g.filter((t) => t.weighted === 1)).toHaveLength(1);
	});
});

describe('attributeCorrelations', () => {
	it('ranks ordinal attributes by how strongly their level tracks the score', () => {
		// animation_quality rises with score; story_quality is flat.
		const items = [
			item({ media_uuid: 'a', anime_uuid: 'A', rating: 3, animation_quality: 'bad', story_quality: 'good' }),
			item({ media_uuid: 'b', anime_uuid: 'B', rating: 5, animation_quality: 'normal', story_quality: 'good' }),
			item({ media_uuid: 'c', anime_uuid: 'C', rating: 7, animation_quality: 'good', story_quality: 'good' }),
			item({ media_uuid: 'd', anime_uuid: 'D', rating: 9, animation_quality: 'very_good', story_quality: 'good' }),
			item({ media_uuid: 'e', anime_uuid: 'E', rating: 8, animation_quality: 'good', story_quality: 'good' }),
		];
		const corr = attributeCorrelations(items);
		const anim = corr.find((c) => c.key === 'animation_quality');
		expect(anim).toBeDefined();
		expect(anim!.rho).toBeGreaterThan(0.8);
		// story_quality has no variance → dropped (spearman ok=false)
		expect(corr.find((c) => c.key === 'story_quality')).toBeUndefined();
	});
});

describe('attributeCategoryEffects', () => {
	it('computes per-category means + eta for nominal attributes', () => {
		const items = [
			item({ media_uuid: 'a', anime_uuid: 'A', rating: 9, ending_type: 'closed' }),
			item({ media_uuid: 'b', anime_uuid: 'B', rating: 8, ending_type: 'closed' }),
			item({ media_uuid: 'c', anime_uuid: 'C', rating: 4, ending_type: 'cliffhanger' }),
			item({ media_uuid: 'd', anime_uuid: 'D', rating: 3, ending_type: 'cliffhanger' }),
			item({ media_uuid: 'e', anime_uuid: 'E', rating: 6, ending_type: 'open' }),
		];
		const eff = attributeCategoryEffects(items).find((e) => e.key === 'ending_type');
		expect(eff).toBeDefined();
		expect(eff!.categories[0].value).toBe('closed'); // highest mean first
		expect(eff!.categories[0].delta).toBeGreaterThan(0);
		expect(eff!.eta).toBeGreaterThan(0.5); // strong separation
	});
});

describe('ratingSequence + movingAverage', () => {
	it('orders scores chronologically by created_at', () => {
		const seq = ratingSequence([
			item({ media_uuid: 'b', anime_uuid: 'B', rating: 7, created_at: '2026-03-01T00:00:00Z' }),
			item({ media_uuid: 'a', anime_uuid: 'A', rating: 9, created_at: '2026-01-01T00:00:00Z' }),
		]);
		expect(seq.map((p) => p.score)).toEqual([9, 7]);
		expect(seq.map((p) => p.index)).toEqual([1, 2]);
	});
	it('trailing moving average smooths the series', () => {
		expect(movingAverage([2, 4, 6, 8], 2)).toEqual([2, 3, 5, 7]);
		expect(movingAverage([], 3)).toEqual([]);
	});
});

describe('cumulativeWatchTime', () => {
	it('accumulates completed watch time by rating date; clips x to a window', () => {
		const items = [
			item({ media_uuid: 'a', anime_uuid: 'A', rating: 8, watch_status: 'completed', total_watch_time: 100, created_at: '2026-01-01T00:00:00Z' }),
			item({ media_uuid: 'b', anime_uuid: 'B', rating: 7, watch_status: 'dropped', total_watch_time: 999, created_at: '2026-02-01T00:00:00Z' }),
			item({ media_uuid: 'c', anime_uuid: 'C', rating: 6, watch_status: 'completed', total_watch_time: 50, created_at: '2026-03-01T00:00:00Z' }),
		];
		expect(cumulativeWatchTime(items)).toEqual([
			{ date: '2026-01-01T00:00:00Z', seconds: 100 },
			{ date: '2026-03-01T00:00:00Z', seconds: 150 }, // dropped excluded; cumulative absolute
		]);
		// window clips x but keeps absolute y
		expect(cumulativeWatchTime(items, '2026-02-15T00:00:00Z')).toEqual([
			{ date: '2026-03-01T00:00:00Z', seconds: 150 },
		]);
	});
});

describe('totalWatchTime', () => {
	it('sums only completed watch time', () => {
		const total = totalWatchTime([
			item({ media_uuid: 'a', anime_uuid: 'A', rating: 8, watch_status: 'completed', total_watch_time: 100 }),
			item({ media_uuid: 'b', anime_uuid: 'B', rating: 7, watch_status: 'completed', total_watch_time: 50 }),
			item({ media_uuid: 'c', anime_uuid: 'C', rating: 6, watch_status: 'dropped', total_watch_time: 999 }),
		]);
		expect(total).toBe(150); // dropped excluded
	});
});
