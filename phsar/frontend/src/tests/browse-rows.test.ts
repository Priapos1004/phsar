/**
 * Browse's row cache: kept across a detail detour, dropped on leaving Browse, and on a
 * rating or watchlist write for the rows that read them — the ways it must not show
 * stale rows, and the write that must not cost the rows it can't change. Home's rows
 * outlive the section; a catalogue change and the end of the day drop every entry.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

vi.mock('$lib/api', () => ({
	api: { get: vi.fn() },
	ApiError: class ApiError extends Error {},
}));

import { api } from '$lib/api';
import { browsePage, browseRow, clearBrowseRows } from '$lib/stores/browseRows';
import { bumpCatalogueChanged } from '$lib/stores/jobs';
import { applyFilterLifecycle } from '$lib/utils/filterLifecycle';
import { invalidateRatingScores } from '$lib/stores/ratingScores';
import { refreshWatchlist } from '$lib/stores/watchlist';
import type { MediaSearchFilters } from '$lib/utils/search';

const get = api.get as unknown as ReturnType<typeof vi.fn>;
const FRESH: MediaSearchFilters = { query: '', search_type: 'title', sort: 'aired' };
const CONTINUATIONS: MediaSearchFilters = { query: '', search_type: 'title', rated: ['in_progress'], sort: 'release' };
const rowCalls = () => get.mock.calls.filter(([path]) => path === '/search/anime').length;

describe('browse row cache', () => {
	beforeEach(() => {
		get.mockReset();
		get.mockResolvedValue([]);
		clearBrowseRows();
	});
	afterEach(() => vi.useRealTimers());

	it('fetches a row once for many readers', async () => {
		await browseRow(FRESH, 25);
		await browseRow({ ...FRESH }, 25);
		expect(rowCalls()).toBe(1);
	});

	it('keys a row by its search and limit', async () => {
		await browseRow(FRESH, 25);
		await browseRow(FRESH, 250);
		await browseRow({ ...FRESH, sort: 'popularity' }, 25);
		expect(rowCalls()).toBe(3);
	});

	// A see-all's toggles change its search; each combination's list must not stay.
	it('keeps only the latest search under a see-all slot', async () => {
		const top20 = { ...FRESH, top_percent: 20 };
		await browseRow(FRESH, 250, { slot: 'fresh' });
		await browseRow(top20, 250, { slot: 'fresh' });
		await browseRow(FRESH, 250, { slot: 'fresh' });
		await browseRow(FRESH, 250, { slot: 'fresh' });
		expect(rowCalls()).toBe(3);
	});

	it('keeps the page and its rows across a detail detour', async () => {
		await browsePage('news');
		await browseRow(FRESH, 25);
		applyFilterLifecycle('/anime');
		applyFilterLifecycle('/browse');
		await browsePage('news');
		await browseRow(FRESH, 25);
		expect(get).toHaveBeenCalledTimes(2);
	});

	it('refetches after leaving Browse', async () => {
		await browseRow(FRESH, 25);
		applyFilterLifecycle('/ratings');
		await browseRow(FRESH, 25);
		expect(rowCalls()).toBe(2);
	});

	it("keeps Home's rows after leaving Browse, and refetches them when the catalogue changes", async () => {
		const home = async () => {
			await browsePage('home');
			await browseRow(FRESH, 25, { page: 'home' });
		};
		await home();
		applyFilterLifecycle('/ratings');
		await home();
		expect(get).toHaveBeenCalledTimes(2);
		bumpCatalogueChanged();
		await home();
		expect(get).toHaveBeenCalledTimes(4);
	});

	it('refetches on a new UTC day', async () => {
		vi.useFakeTimers({ toFake: ['Date'] });
		vi.setSystemTime(new Date('2026-10-12T23:59:00Z'));
		await browseRow(FRESH, 25);
		vi.setSystemTime(new Date('2026-10-13T00:01:00Z'));
		await browseRow(FRESH, 25);
		expect(rowCalls()).toBe(2);
	});

	it('refetches a row over your ratings after a rating write, and keeps the rest', async () => {
		await browsePage('news');
		await browseRow(FRESH, 25);
		await browseRow(CONTINUATIONS, 25);
		invalidateRatingScores();
		await browsePage('news');
		await browseRow(FRESH, 25);
		await browseRow(CONTINUATIONS, 25);
		expect(get).toHaveBeenCalledTimes(4);
		expect(rowCalls()).toBe(3);
	});

	it('refetches a row over your watchlist after a watchlist write', async () => {
		await browseRow({ ...FRESH, watchlisted: true }, 25);
		await refreshWatchlist();
		await browseRow({ ...FRESH, watchlisted: true }, 25);
		expect(rowCalls()).toBe(2);
	});

	it('does not replay a failure', async () => {
		get.mockRejectedValueOnce(new Error('boom'));
		await expect(browseRow(FRESH, 25)).rejects.toThrow('boom');
		await browseRow(FRESH, 25);
		expect(rowCalls()).toBe(2);
	});
});
