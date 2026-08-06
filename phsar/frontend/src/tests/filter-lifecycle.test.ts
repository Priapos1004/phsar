import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import {
	applyFilterLifecycle,
	isDetailRoute,
	sectionsToClearFor,
	SECTION_FILTERS,
} from '$lib/utils/filterLifecycle';
import { ratingsFilter, DEFAULT_RATINGS_FILTER } from '$lib/stores/ratingsFilter';
import { watchlistFilter, DEFAULT_WATCHLIST_FILTER } from '$lib/stores/watchlistFilter';
import { jobsFilter } from '$lib/stores/adminJobsFilter';

const ALL = ['/ratings', '/watchlist', '/admin'];
const clearedFor = (to: string) => sectionsToClearFor(to).map((s) => s.prefix);

describe('isDetailRoute', () => {
	it('matches the two query-param detail routes', () => {
		expect(isDetailRoute('/anime')).toBe(true);
		expect(isDetailRoute('/media')).toBe(true);
	});

	it('does not match a prefix collision', () => {
		expect(isDetailRoute('/animes')).toBe(false);
		expect(isDetailRoute('/media-library')).toBe(false);
	});

	it('does not match unrelated routes', () => {
		expect(isDetailRoute('/ratings')).toBe(false);
		expect(isDetailRoute('/search')).toBe(false);
	});
});

describe('sectionsToClearFor', () => {
	it('registers exactly the three filtered sections', () => {
		expect(SECTION_FILTERS.map((s) => s.prefix)).toEqual(ALL);
	});

	it('clears nothing when the destination is a detail page', () => {
		expect(clearedFor('/media')).toEqual([]);
		expect(clearedFor('/anime')).toEqual([]);
	});

	it('keeps the destination section and clears the others', () => {
		expect(clearedFor('/ratings')).toEqual(['/watchlist', '/admin']);
		expect(clearedFor('/watchlist')).toEqual(['/ratings', '/admin']);
	});

	it('keeps a section across an in-section child route', () => {
		expect(clearedFor('/admin/jobs/abc-123')).not.toContain('/admin');
	});

	it('clears every section for an unrelated destination', () => {
		expect(clearedFor('/search')).toEqual(ALL);
		expect(clearedFor('/settings')).toEqual(ALL);
	});

	it('does not treat a prefix collision as the same section', () => {
		expect(clearedFor('/admin-tools')).toContain('/admin');
	});
});

describe('applyFilterLifecycle', () => {
	beforeEach(() => {
		ratingsFilter.set({ ...DEFAULT_RATINGS_FILTER, view: 'table', genres: ['Action'] });
		watchlistFilter.set({ ...DEFAULT_WATCHLIST_FILTER, priorities: [1] });
		jobsFilter.set({ kind: 'backup', status: 'failed' });
	});

	it('keeps every filter across a detour to a media detail page', () => {
		applyFilterLifecycle('/media');
		expect(get(ratingsFilter).genres).toEqual(['Action']);
		expect(get(watchlistFilter).priorities).toEqual([1]);
		expect(get(jobsFilter)).toEqual({ kind: 'backup', status: 'failed' });
	});

	it('keeps the ratings filter when coming back from the detail page', () => {
		applyFilterLifecycle('/media');
		applyFilterLifecycle('/ratings');
		expect(get(ratingsFilter).genres).toEqual(['Action']);
	});

	it('clears the ratings filter when the detour ends somewhere else', () => {
		applyFilterLifecycle('/media');
		applyFilterLifecycle('/search');
		expect(get(ratingsFilter).genres).toEqual([]);
	});

	it('keeps the chosen view when clearing the value filters', () => {
		applyFilterLifecycle('/search');
		expect(get(ratingsFilter).view).toBe('table');
		expect(get(ratingsFilter).genres).toEqual([]);
	});

	it('keeps the admin filter across a job detail hop', () => {
		applyFilterLifecycle('/admin/jobs/abc-123');
		expect(get(jobsFilter)).toEqual({ kind: 'backup', status: 'failed' });
	});

	it('clears the section left behind on a cross-section hop', () => {
		applyFilterLifecycle('/watchlist');
		expect(get(ratingsFilter).genres).toEqual([]);
		expect(get(watchlistFilter).priorities).toEqual([1]);
	});
});
