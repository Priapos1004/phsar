/**
 * Browse's row cache: kept across a detail detour, dropped on leaving Browse, and on a
 * rating or watchlist write for the rows that read them — the ways it must not show
 * stale rows, and the write that must not cost the rows it can't change. Home's rows
 * outlive the section; a catalogue change and the end of the day drop every entry.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

vi.mock('$lib/api', () => ({
	api: { get: vi.fn(), post: vi.fn() },
	ApiError: class ApiError extends Error {},
}));

import { api } from '$lib/api';
import {
	browsePage, browseRow, carouselResults, clearBrowseRows, discoverWorlds, knownStep, refinedFromDefaults,
	spinWorld,
} from '$lib/stores/browseRows';
import { NO_REFINEMENT } from '$lib/stores/browseRefinements';
import type { BrowseCarousel } from '$lib/types/api';
import { bumpCatalogueChanged } from '$lib/stores/jobs';
import { applyFilterLifecycle } from '$lib/utils/filterLifecycle';
import { invalidateRatingScores } from '$lib/stores/ratingScores';
import { refreshWatchlist } from '$lib/stores/watchlist';
import type { MediaSearchFilters } from '$lib/utils/search';

const get = api.get as unknown as ReturnType<typeof vi.fn>;
const post = api.post as unknown as ReturnType<typeof vi.fn>;
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

describe("Discover's worlds", () => {
	const WORLDS = [{ key: 'cozy', title: 'Cozy Corner' }, { key: 'steel', title: 'Blood & Steel' }];
	const COZY = { world: 'cozy', carousels: [] };

	beforeEach(() => {
		get.mockReset();
		post.mockReset();
		clearBrowseRows();
	});

	// A return from a detail page must land on the world, not on the wheel again.
	it("keeps a user's spin, so the worlds then carry today", async () => {
		get.mockResolvedValue({ worlds: WORLDS, today: null });
		post.mockResolvedValue(COZY);
		expect((await discoverWorlds(false)).spun).toBe(false);
		expect(await spinWorld(false)).toMatchObject({ today: COZY, spun: true });
		expect(await discoverWorlds(false)).toMatchObject({ today: COZY, spun: true });
		expect(get).toHaveBeenCalledTimes(1);
	});

	it('shows a user who spun elsewhere today the world, not the wheel', async () => {
		get.mockResolvedValue({ worlds: WORLDS, today: COZY });
		expect((await discoverWorlds(false)).spun).toBe(true);
	});

	// A guest is read-only: its world is drawn for it, and its spin only lands there.
	it("spins a guest onto the world it was given, without a request", async () => {
		get.mockResolvedValue({ worlds: WORLDS, today: COZY });
		expect((await discoverWorlds(true)).spun).toBe(false);
		expect(await spinWorld(true)).toMatchObject({ today: COZY, spun: true });
		expect(post).not.toHaveBeenCalled();
		expect((await discoverWorlds(true)).spun).toBe(true);
	});
});

describe('refinedFromDefaults', () => {
	const sets = [
		{ key: 'top-50', label: '50%', default_on: true, params: { top_percent: 50 } },
		{ key: 'top-75', label: '75%', default_on: false, params: { top_percent: 75 } },
	];
	const dragons: BrowseCarousel = {
		key: 'dragons', title: 'Dragons', params: { top_percent: 50, sort: 'top_rated' }, see_all_limit: 1000,
		sortable: true, filter_sets: sets, page: 'discover',
	};

	beforeEach(() => {
		get.mockReset();
		get.mockResolvedValue([]);
		clearBrowseRows();
	});

	// Reset hides once the viewer has walked back to the defaults by hand.
	it('reads a choice undone by hand as none', () => {
		expect(refinedFromDefaults(dragons, NO_REFINEMENT)).toBe(false);
		expect(refinedFromDefaults(dragons, { on: ['top-50'], off: [] })).toBe(false);
		expect(refinedFromDefaults(dragons, { on: [], off: [], sort: 'top_rated', sort_dir: 'desc' })).toBe(false);
	});

	it('reads another step or order as a change', () => {
		expect(refinedFromDefaults(dragons, { on: [], off: ['top-50'] })).toBe(true);
		expect(refinedFromDefaults(dragons, { on: [], off: [], sort: 'score' })).toBe(true);
	});

	// A see-all's toggle that narrows the pool must not widen the plain row.
	it('keeps a count to the toggles it ran under', async () => {
		const withToggle = { ...dragons, filter_sets: [...sets, { key: 'on-watchlist', label: 'In list', default_on: false, params: { watchlisted: true } }] };
		await carouselResults(withToggle, { on: ['on-watchlist'], off: [] }, false, 1000);
		expect(knownStep(withToggle, NO_REFINEMENT)).toBeNull();
		expect(knownStep(withToggle, { on: ['on-watchlist'], off: [] })?.refinement).toEqual({
			on: ['on-watchlist', 'top-75'], off: ['top-50'],
		});
	});

	// On a thin row the default Reset returns to is the widened 75%.
	it('measures a thin row against its widened default', async () => {
		await carouselResults(dragons, NO_REFINEMENT, false, 1000);
		expect(refinedFromDefaults(dragons, { on: ['top-75'], off: ['top-50'] })).toBe(false);
		expect(refinedFromDefaults(dragons, { on: ['top-50'], off: [] })).toBe(true);
	});
});
