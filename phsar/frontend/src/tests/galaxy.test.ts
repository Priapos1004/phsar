import { describe, it, expect } from 'vitest';
import {
	COVER_ASPECT,
	COVER_SPAN,
	coverCrop,
	coverSize,
	evenWindows,
	fitWindow,
	labelCentre,
	nebulaPixels,
	ownTopPercents,
	packCovers,
	sectorHues
} from '$lib/utils/galaxy';
import type { GalaxySector } from '$lib/types/api';

const sector = (number: number, x: number, y: number): GalaxySector => ({ uuid: `s${number}`, number, name: '', x, y });

describe('ownTopPercents', () => {
	it('ranks the viewer\'s scores as the search rounds its badge, ties sharing their best rank', () => {
		const top = ownTopPercents(new Map([['a', 9], ['b', 7.5], ['c', 7.5], ['d', 6]]));
		// Ranks 1, 2, 2, 4 of 4: rounded up to a percentage, the lowest reads 100.
		expect(Object.fromEntries(top)).toEqual({ a: 25, b: 50, c: 50, d: 100 });
	});

	it('gives a lone rating Top 100%, and nothing for no ratings', () => {
		expect(ownTopPercents(new Map([['a', 8]])).get('a')).toBe(100);
		expect(ownTopPercents(new Map()).size).toBe(0);
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
