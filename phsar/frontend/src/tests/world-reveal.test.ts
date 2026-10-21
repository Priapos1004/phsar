/**
 * The parts of the reveal a test can reach. The timeline: `play` resolves at the flash peak
 * and never later, since the spin waits on it with the wheel showing "Spinning…". The bolt:
 * it lands where it was aimed and stays on screen. What the reveal looks like is a human's
 * check — jsdom has no canvas and no paint.
 */
import { render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import WorldReveal from '$lib/components/WorldReveal.svelte';
import { WORLD_LOOK } from '$lib/utils/discoverWorlds';
import { BEAT, bolt, runReveal } from '$lib/utils/worldReveal';

// mulberry32: a seeded stand-in for Math.random, so a failing bolt can be replayed.
function seeded(seed: number) {
	return () => {
		seed = (seed + 0x6d2b79f5) | 0;
		let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
		t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
		return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
	};
}

describe('WorldReveal', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		// jsdom has no 2D context; returning none on purpose keeps its not-implemented warning out.
		vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);
	});
	afterEach(() => {
		vi.useRealTimers();
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	function start(key = 'power-up') {
		const { component } = render(WorldReveal);
		const state = { peaked: false };
		void component.play(key, 'Power Up').then(() => (state.peaked = true));
		return state;
	}
	const stage = () => document.querySelector('.stage');

	it('resolves at the flash peak, not before, and clears itself at the end', async () => {
		const state = start();
		await vi.advanceTimersByTimeAsync(BEAT.peak - 1);
		expect(state.peaked).toBe(false);
		expect(stage()).not.toBeNull();
		await vi.advanceTimersByTimeAsync(1);
		expect(state.peaked).toBe(true);
		await vi.advanceTimersByTimeAsync(BEAT.end - BEAT.peak);
		expect(stage()).toBeNull();
	});

	it('resolves at once when a tap skips it, then fades out', async () => {
		const state = start();
		await vi.advanceTimersByTimeAsync(100);
		window.dispatchEvent(new PointerEvent('pointerdown'));
		await vi.advanceTimersByTimeAsync(0);
		expect(state.peaked).toBe(true);
		await vi.advanceTimersByTimeAsync(200);
		expect(stage()).toBeNull();
	});

	it('plays nothing under reduced motion', async () => {
		vi.stubGlobal('matchMedia', () => ({ matches: true }));
		const state = start();
		await vi.advanceTimersByTimeAsync(0);
		expect(state.peaked).toBe(true);
		expect(stage()).toBeNull();
	});
});

describe('bolt', () => {
	it('lands on its target and stays inside the screen, forks and all', () => {
		// Narrow and tall, so the displacement certainly reaches past the sides.
		for (const [w, h] of [
			[60, 900],
			[1440, 900],
		]) {
			for (let seed = 1; seed <= 20; seed++) {
				const from = { x: w * 0.3, y: 0 };
				const to = { x: w / 2, y: h / 2 };
				const channels = bolt(from, to, w, h, seeded(seed));
				const main = channels[0].points;
				expect(main[0], `seed ${seed}`).toEqual(from);
				expect(main.at(-1), `seed ${seed}`).toEqual(to);
				for (const { points } of channels) {
					for (const p of points) {
						expect(p.x, `seed ${seed} at ${w}×${h}`).toBeGreaterThanOrEqual(0);
						expect(p.x).toBeLessThanOrEqual(w);
						expect(p.y).toBeGreaterThanOrEqual(0);
						expect(p.y).toBeLessThanOrEqual(h);
					}
				}
			}
		}
	});
});

/**
 * A 2D context that records what a scene asks of it: every alpha it sets, and every call or
 * setting handed a number that isn't finite. Each goes wrong without throwing — a canvas
 * ignores an alpha outside 0–1 and keeps drawing with the last one, and a NaN draws nothing
 * — so this is the check that a signature draws what it means to, short of a human looking
 * at it.
 */
function recordingContext() {
	const seen = { alphas: [] as number[], broken: [] as string[] };
	const check = (key: PropertyKey, args: unknown[]) => {
		if (args.some((a) => typeof a === 'number' && !Number.isFinite(a))) seen.broken.push(String(key));
	};
	const gradient = { addColorStop: () => {} };
	const state: Record<PropertyKey, unknown> = {};
	const ctx = new Proxy(state, {
		get: (target, key) =>
			key in target
				? target[key]
				: (...args: unknown[]) => {
						check(key, args);
						return gradient;
					},
		set: (target, key, value) => {
			if (key === 'globalAlpha') seen.alphas.push(value);
			check(key, [value]);
			target[key] = value;
			return true;
		},
	});
	// A function, not an arrow, so `new Path2D()` can construct it.
	const path = function () {
		return new Proxy({}, { get: (_, key) => (...args: unknown[]) => check(key, args) });
	};
	return { ctx, seen, path };
}

describe('every signature', () => {
	let frames: FrameRequestCallback[] = [];
	afterEach(() => {
		frames = [];
		vi.unstubAllGlobals();
		vi.restoreAllMocks();
	});

	const kinds = [...new Map(Object.values(WORLD_LOOK).map((look) => [look.reveal, look])).values()];
	for (const look of kinds) {
		for (const [w, h] of [
			[390, 844],
			[1440, 900],
		]) {
			it(`${look.reveal} plays through at ${w}×${h}, in range, and stops by itself`, () => {
				const { ctx, seen, path } = recordingContext();
				vi.stubGlobal('Path2D', path);
				vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => frames.push(cb));
				vi.stubGlobal('cancelAnimationFrame', () => {});
				// The sprites a scene paints once are drawn through the same recording context.
				vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(ctx as never);
				const canvas = { getContext: () => ctx, clientWidth: w, clientHeight: h, width: 0, height: 0 } as unknown as HTMLCanvasElement;

				runReveal(canvas, look, seeded(7));
				let now = 0;
				while (frames.length && now <= BEAT.end + 100) {
					const due = frames;
					frames = [];
					due.forEach((cb) => cb(now));
					now += 1000 / 60;
				}

				expect(frames, 'still scheduling frames after the reveal ended').toHaveLength(0);
				expect(seen.broken).toEqual([]);
				expect(seen.alphas.length).toBeGreaterThan(0);
				expect(seen.alphas.filter((a) => !(a >= 0 && a <= 1))).toEqual([]);
			});
		}
	}
});

