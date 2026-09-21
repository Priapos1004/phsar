/**
 * `ratingCoverage` — the lazy per-anime coverage cache.
 *
 * The caching is barely worth a test; the INVALIDATION contract is, for the
 * reason `rating-scores-store.test.ts` states for its sibling: a real cache
 * trades per-mount safety for round trips and has to buy it back explicitly.
 * The race these pin is the one that made the eager version wrong — an
 * invalidate landing while a fetch is in flight must not let the pre-write
 * response win and then mark the store fresh.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('$lib/api', () => ({
	api: { get: vi.fn() },
	ApiError: class ApiError extends Error {}
}));

import { get as storeGet } from 'svelte/store';
import { api } from '$lib/api';
import {
	ratingCoverage,
	ensureRatingCoverage,
	invalidateRatingCoverage,
	clearRatingCoverage
} from '$lib/stores/ratingCoverage';

const apiGet = api.get as unknown as ReturnType<typeof vi.fn>;
const entry = (uuid: string, tier = 'all') => [{ anime_uuid: uuid, tier }];

describe('ratingCoverage cache', () => {
	beforeEach(() => {
		clearRatingCoverage();
		apiGet.mockReset();
	});

	it('serves many readers from one fetch', async () => {
		apiGet.mockResolvedValue(entry('a'));
		await Promise.all([ensureRatingCoverage(), ensureRatingCoverage()]);
		await ensureRatingCoverage();
		expect(apiGet).toHaveBeenCalledTimes(1);
		expect(storeGet(ratingCoverage).get('a')).toBe('all');
	});

	it('refetches after an invalidation', async () => {
		apiGet.mockResolvedValue(entry('a'));
		await ensureRatingCoverage();
		invalidateRatingCoverage();
		await ensureRatingCoverage();
		expect(apiGet).toHaveBeenCalledTimes(2);
	});

	it('does not let a fetch invalidated mid-flight settle as fresh', async () => {
		// The bug the eager version shipped: rate something while /search's fetch is
		// still open, and the pre-write response would land, populate, and mark the
		// cache current — leaving stale tiers until the next write.
		let resolveFirst!: (v: unknown) => void;
		apiGet.mockReturnValueOnce(new Promise((r) => (resolveFirst = r)));

		const first = ensureRatingCoverage();
		invalidateRatingCoverage();
		resolveFirst(entry('stale', 'main'));
		await first;

		expect(storeGet(ratingCoverage).has('stale')).toBe(false);

		apiGet.mockResolvedValue(entry('fresh'));
		await ensureRatingCoverage();
		expect(apiGet).toHaveBeenCalledTimes(2);
		expect(storeGet(ratingCoverage).get('fresh')).toBe('all');
	});

	it('does not leak the previous user after a switch mid-flight', async () => {
		let resolveFirst!: (v: unknown) => void;
		apiGet.mockReturnValueOnce(new Promise((r) => (resolveFirst = r)));

		const first = ensureRatingCoverage();
		clearRatingCoverage();
		resolveFirst(entry('user-a-anime'));
		await first;

		expect(storeGet(ratingCoverage).size).toBe(0);
	});

	it('retries after a failure instead of replaying it', async () => {
		apiGet.mockRejectedValueOnce(new Error('403'));
		await expect(ensureRatingCoverage()).resolves.toBeUndefined();

		apiGet.mockResolvedValue(entry('a'));
		await ensureRatingCoverage();
		expect(apiGet).toHaveBeenCalledTimes(2);
		expect(storeGet(ratingCoverage).get('a')).toBe('all');
	});
});
