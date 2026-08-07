/**
 * `ratingScores` + `filterOptions` — the two session caches added for the
 * fetch-behaviour pass.
 *
 * The caching itself is barely worth a test; the INVALIDATION contract is. A
 * per-mount fetch could never show stale data, so a real cache trades that
 * safety for the round trips and has to buy it back explicitly. These pin the
 * three properties that make the trade sound: one fetch for many readers, a
 * failure that doesn't stick, and an invalidation that actually refetches.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('$lib/api', () => ({
	api: { get: vi.fn() },
	ApiError: class ApiError extends Error {},
}));

import { api } from '$lib/api';
import {
	ensureRatingScores,
	invalidateRatingScores,
	clearRatingScores,
} from '$lib/stores/ratingScores';
// clearRatingScores is an alias of invalidateRatingScores, so the refetch test
// below covers both; it's used here only to reset state between tests.
import { ensureFilterOptions, clearFilterOptions } from '$lib/stores/filterOptions';

const get = api.get as unknown as ReturnType<typeof vi.fn>;

describe('ratingScores cache', () => {
	beforeEach(() => {
		get.mockReset();
		clearRatingScores();
	});

	it('fetches once for many readers', async () => {
		get.mockResolvedValue([{ media_uuid: 'm1' }]);
		const a = await ensureRatingScores();
		const b = await ensureRatingScores();
		expect(get).toHaveBeenCalledTimes(1);
		expect(b).toBe(a); // same array, not merely equal
	});

	it('coalesces concurrent readers into one request', async () => {
		get.mockResolvedValue([]);
		// The three consumers can mount in the same tick (a page plus a RatingCard).
		await Promise.all([ensureRatingScores(), ensureRatingScores(), ensureRatingScores()]);
		expect(get).toHaveBeenCalledTimes(1);
	});

	it('refetches after invalidation', async () => {
		get.mockResolvedValue([]);
		await ensureRatingScores();
		invalidateRatingScores();
		await ensureRatingScores();
		expect(get).toHaveBeenCalledTimes(2);
	});

	it('does not cache a failure', async () => {
		get.mockRejectedValueOnce(new Error('boom'));
		await expect(ensureRatingScores()).rejects.toThrow('boom');
		// A stuck rejected promise would make the ratings page permanently broken
		// for the rest of the session.
		get.mockResolvedValue([{ media_uuid: 'm1' }]);
		await expect(ensureRatingScores()).resolves.toHaveLength(1);
		expect(get).toHaveBeenCalledTimes(2);
	});
});

describe('filterOptions cache', () => {
	beforeEach(() => {
		get.mockReset();
		clearFilterOptions();
	});

	it('caches per view_type rather than globally', async () => {
		get.mockResolvedValue({});
		await ensureFilterOptions('anime');
		await ensureFilterOptions('anime');
		expect(get).toHaveBeenCalledTimes(1);
		// The two views return different payloads (anime has no per-episode
		// duration filter), so one cache slot for both would serve the wrong bounds.
		await ensureFilterOptions('media');
		expect(get).toHaveBeenCalledTimes(2);
	});

	it('evicts only the failed view', async () => {
		get.mockResolvedValue({});
		await ensureFilterOptions('anime');
		get.mockRejectedValueOnce(new Error('nope'));
		await expect(ensureFilterOptions('media')).rejects.toThrow('nope');

		get.mockResolvedValue({});
		await ensureFilterOptions('media'); // retries
		await ensureFilterOptions('anime'); // still cached
		expect(get).toHaveBeenCalledTimes(3);
	});
});
