/**
 * The parts of the reveal a test can reach. The timeline: `play` resolves at the flash peak
 * and never later, since the spin waits on it with the wheel showing "Spinning…". The bolt:
 * it lands where it was aimed and stays on screen. What the reveal looks like is a human's
 * check — jsdom has no canvas and no paint.
 */
import { render } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import WorldReveal from '$lib/components/WorldReveal.svelte';
import { BEAT, bolt } from '$lib/utils/worldReveal';

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
