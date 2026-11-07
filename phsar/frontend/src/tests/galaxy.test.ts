import { describe, it, expect } from 'vitest';
import {
	COVER_ASPECT,
	COVER_SPAN,
	coverCrop,
	coverSize,
	dailyPicks,
	evenWindows,
	fitWindow,
	groupStats,
	groupView,
	labelCentre,
	spreadLabels,
	nebulaPixels,
	packCovers,
	sectorHues,
	type MapWindow
} from '$lib/utils/galaxy';
import type { GalaxySector, GalaxyStar } from '$lib/types/api';

const sector = (number: number, x: number, y: number): GalaxySector => ({ uuid: `s${number}`, number, name: '', x, y });

const at = (anime_uuid: string, x: number, y: number, sector: number, more: Partial<GalaxyStar> = {}) =>
	({ anime_uuid, x, y, sector, region: sector, genres: [], score: null, top_percent: null, ...more }) as GalaxyStar;

describe('groupView', () => {
	const stars = [at('a', 10, 10, 0), at('b', 30, 20, 0), at('c', 90, 90, 1)];
	const win = { x: [0, 100], y: [0, 100] } as MapWindow;

	it('frames all of a group\'s stars, with a margin', () => {
		const v = groupView(stars, { level: 'sector', number: 0 }, win, 1000, { left: 0, right: 0 });
		expect([v.x, v.y]).toEqual([20, 15]);
		// 20 of 100 wide, the wider side, plus 15%.
		expect(v.width).toBeCloseTo(23);
	});

	it('frames it in the strip the controls leave clear', () => {
		// 200px of 1000 taken on the left: the group spans 800px' worth (20 × 1000/800, plus
		// 15%), and the view shifts left by half of 200px, at 0.02875 units a pixel, so the
		// group lands right of the box's centre.
		const v = groupView(stars, { level: 'sector', number: 0 }, win, 1000, { left: 200, right: 0 });
		expect(v.width).toBeCloseTo(28.75);
		expect(v.x).toBeCloseTo(17.125);
	});
});

describe('groupStats', () => {
	it('counts, averages and ranks the group\'s own anime only', () => {
		const stars = [
			at('a', 0, 0, 0, { score: 8, top_percent: 3, genres: ['Action', 'Drama'] }),
			at('b', 0, 0, 0, { score: 6, top_percent: 40, genres: ['Action'] }),
			at('c', 0, 0, 0, { genres: ['Comedy'] }),
			at('d', 0, 0, 1, { score: 9, top_percent: 1, genres: ['Action'] })
		];
		const stats = groupStats(stars, { level: 'sector', number: 0 }, new Map([['b', 7], ['d', 10]]));
		expect([stats.count, stats.rated, stats.malMean, stats.ownMean]).toEqual([3, 1, 7, 7]);
		expect(stats.genres[0]).toEqual({ name: 'Action', share: 2 / 3 });
		// Unscored anime have no rank to list by.
		expect(stats.top.map((s) => s.anime_uuid)).toEqual(['a', 'b']);
	});
});

describe('dailyPicks', () => {
	// 100 stars, two to each Top N%: Top 5% holds the first ten.
	const stars = Array.from({ length: 100 }, (_, i) => ({ anime_uuid: `a${i}`, top_percent: Math.ceil((i + 1) / 2) }) as GalaxyStar);
	const uuids = (picks: ReturnType<typeof dailyPicks>) => picks.map((p) => p.star.anime_uuid);
	// Rated: twenty anime by your own Top N%, a50 the best and a51 next; a3, in MAL's top 5%,
	// your worst.
	const scores = new Map([...Array.from({ length: 19 }, (_, k) => [`a${50 + k}`, (k + 1) * 5] as const), ['a3', 100] as const]);
	// Listed: two at priority 1, the rest lower; a2 is in the top 5% too.
	const listed = new Map([['a80', 3], ['a81', 1], ['a82', 2], ['a2', 1]]);

	it('takes two favourites and two of the highest-priority watchlist entries', () => {
		const picks = dailyPicks(stars, scores, listed, '2026-11-06');
		expect(picks.map((p) => p.why)).toEqual(['favourite', 'favourite', 'watchlist', 'watchlist', 'top', 'top']);
		// Twenty ratings make a top 10% of two: the best two.
		expect(new Set(uuids(picks).slice(0, 2))).toEqual(new Set(['a50', 'a51']));
		expect(new Set(uuids(picks).slice(2, 4))).toEqual(new Set(['a81', 'a2']));
	});

	it('fills only from the top 5% the viewer has neither rated nor listed, whatever the day', () => {
		for (let d = 1; d <= 30; d++) {
			for (const p of dailyPicks(stars, scores, listed, `2026-11-${d}`).filter((p) => p.why === 'top')) {
				expect(p.star.top_percent).toBeLessThanOrEqual(5);
				expect(['a2', 'a3']).not.toContain(p.star.anime_uuid);
			}
		}
	});

	it('holds all day and changes the next', () => {
		const empty = new Map<string, number>();
		expect(uuids(dailyPicks(stars, empty, empty, '2026-11-06'))).toEqual(uuids(dailyPicks(stars, empty, empty, '2026-11-06')));
		expect(uuids(dailyPicks(stars, empty, empty, '2026-11-06'))).not.toEqual(uuids(dailyPicks(stars, empty, empty, '2026-11-07')));
	});

	it('gives a guest six from the top 5%', () => {
		const picks = dailyPicks(stars, new Map(), new Map(), '2026-11-06');
		expect(picks).toHaveLength(6);
		expect(picks.every((p) => p.why === 'top' && p.star.top_percent! <= 5)).toBe(true);
	});
});

describe('sectorHues', () => {
	it('never gives a sector the hue of one of its nearest neighbours', () => {
		// A ring of twelve sectors: each one's four nearest are the two on either side.
		const ring = Array.from({ length: 12 }, (_, i) =>
			sector(i, Math.cos((i / 12) * 2 * Math.PI) * 10, Math.sin((i / 12) * 2 * Math.PI) * 10)
		);
		const hues = sectorHues(ring);
		for (let i = 0; i < 12; i++)
			for (const d of [1, 2]) expect(hues.get(i)).not.toBe(hues.get((i + d) % 12));
	});
});

describe('fitWindow', () => {
	it('shows one data unit per pixel on both axes, whatever the box', () => {
		const points = [
			{ x: 0, y: 0 },
			{ x: 20, y: 5 }
		];
		// The first box is bound by the points' width, the second by their height.
		for (const [w, h] of [
			[300, 600],
			[800, 100]
		]) {
			const win = fitWindow(points, w, h);
			expect((win.x[1] - win.x[0]) / w).toBeCloseTo((win.y[1] - win.y[0]) / h);
			expect(win.x[0]).toBeLessThan(0);
			expect(win.x[1]).toBeGreaterThan(20);
			expect(win.y[0]).toBeLessThan(0);
			expect(win.y[1]).toBeGreaterThan(5);
		}
	});
});

describe('evenWindows', () => {
	it('widens the axis a zoom-out cut at the edge back to the other', () => {
		// x reached the whole map while y was cut short at its top edge.
		expect(evenWindows([0, 100], [20, 100])).toEqual([
			[0, 100],
			[0, 100]
		]);
		// Cut beside an edge: the cut axis keeps its centre's side, slid inside rather than cut.
		expect(evenWindows([10, 70], [70, 100])).toEqual([
			[10, 70],
			[40, 100]
		]);
		expect(evenWindows([60, 100], [0, 80])).toEqual([
			[20, 100],
			[0, 80]
		]);
	});

	it('leaves windows that already agree alone', () => {
		expect(evenWindows([10, 40], [50, 80])).toEqual([
			[10, 40],
			[50, 80]
		]);
	});
});

describe('labelCentre', () => {
	const box: [number, number] = [400, 300];
	it('moves a label inward only where it would overrun an edge', () => {
		expect(labelCentre([20, 100], [100, 20], box)).toEqual([58, 100]);
		expect(labelCentre([390, 295], [100, 20], box)).toEqual([342, 282]);
		expect(labelCentre([200, 150], [100, 20], box)).toEqual([200, 150]);
	});

	it('leaves a label anchored off the map where it is', () => {
		expect(labelCentre([-40, 100], [100, 20], box)).toEqual([-40, 100]);
		expect(labelCentre([200, 320], [100, 20], box)).toEqual([200, 320]);
	});
});

describe('spreadLabels', () => {
	const box = (x: number, y: number) => ({ x, y, width: 100, height: 10 });
	// To a tenth of a pixel: the solver stops once a sweep moves nothing by a hundredth.
	const spread = (...boxes: ReturnType<typeof box>[]) => spreadLabels(boxes, 300).map((y) => Math.round(y * 10) / 10);

	it('leaves names side by side where they are', () => {
		expect(spread(box(100, 150), box(200, 150))).toEqual([150, 150]);
	});

	it('moves names that share their width apart evenly, keeping their order', () => {
		// 12 apart (heights 10, gap 2): the least squared shift splits it about their mean.
		expect(spread(box(100, 150), box(150, 152))).toEqual([145, 157]);
		expect(spread(box(100, 150), box(120, 150), box(140, 150))).toEqual([138, 150, 162]);
	});

	it('keeps a name inside the map, the one below taking the push', () => {
		// The top name stops at pad 8 + half its height.
		expect(spread(box(100, 5), box(100, 10))).toEqual([13, 25]);
	});
});

describe('packCovers', () => {
	it('keeps covers apart, earlier points first', () => {
		const kept = packCovers(
			[
				[100, 100],
				[110, 105], // overlaps the first, which outranks it
				[200, 100]
			],
			[40, 56]
		);
		expect(kept).toEqual([0, 2]);
	});
});

describe('coverSize', () => {
	it('grows as the view narrows, poster-shaped', () => {
		const [w1, h1] = coverSize(COVER_SPAN);
		const [w2, h2] = coverSize(COVER_SPAN / 2);
		expect(h2).toBeGreaterThan(h1);
		expect(w2 / h2).toBeCloseTo(COVER_ASPECT, 1);
	});
});

describe('coverCrop', () => {
	it('cuts the centre of a cover to the tile shape, whichever way it is off', () => {
		// Too wide: the sides go.
		expect(coverCrop(300, 300, 2 / 3)).toEqual([50, 0, 200, 300]);
		// Too tall: top and bottom go.
		expect(coverCrop(200, 400, 2 / 3)).toEqual([0, 50, 200, 300]);
		// Already the shape: all of it.
		expect(coverCrop(200, 300, 2 / 3)).toEqual([0, 0, 200, 300]);
	});
});

describe('nebulaPixels', () => {
	it('lets a veil-only star shape the veil without lighting the haze', () => {
		const win = { x: [0, 100] as [number, number], y: [0, 100] as [number, number] };
		const { pixels, width } = nebulaPixels(
			[
				{ x: 10, y: 50, weight: 1, tint: [255, 0, 0] },
				{ x: 90, y: 50, weight: 1, tint: [0, 255, 0], veilOnly: true }
			],
			win,
			100,
			[0, 0, 255]
		);
		const at = (col: number) => pixels.slice((50 * width + col) * 4, (50 * width + col) * 4 + 4);
		const [r, g, b, a] = at(89);
		// Veil there, in the veil's tint and no stronger than it ever draws…
		expect([r, g, b > 0]).toEqual([0, 0, true]);
		expect(a).toBeLessThanOrEqual(0.2 * 255);
		// …while the lit star glows in its own.
		expect(at(10)[0]).toBeGreaterThan(at(10)[2]);
	});
});
