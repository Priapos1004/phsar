/**
 * A carousel see-all's toggles and sort: what survives being read back from storage,
 * and how a choice in a group of key-sharing sets lands as `on` / `off`.
 */
import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import {
	browseRefinements,
	filterSetGroups,
	isSetActive,
	NO_REFINEMENT,
	refinedSearch,
	selectInGroup,
} from '$lib/stores/browseRefinements';
import { restoreAllPersistedFilters } from '$lib/stores/persistedFilter';
import { applyFilterLifecycle } from '$lib/utils/filterLifecycle';
import type { BrowseCarousel, BrowseFilterSet } from '$lib/types/api';

const set = (key: string, params: BrowseFilterSet['params'], default_on = false): BrowseFilterSet => ({
	key, label: key, default_on, params,
});

// A slice of Fresh's offer: two sets from each group, top-75 on by default.
const TOP_20 = set('top-20', { top_percent: 20 });
const TOP_75 = set('top-75', { top_percent: 75 }, true);
const IN_LIST = set('on-watchlist', { watchlisted: true });
const NOT_IN_LIST = set('not-on-watchlist', { watchlisted: false });
const NOT_WATCHED = set('not-watched', { rated: ['none'] });
const WATCHED = set('watched', { rated: ['in_progress', 'on_hold', 'dropped', 'main', 'all'] });
const FRESH = [TOP_20, TOP_75, IN_LIST, NOT_IN_LIST, NOT_WATCHED, WATCHED];

describe('filterSetGroups', () => {
	it('groups the sets that share a param, in position order', () => {
		expect(filterSetGroups(FRESH).map((g) => g.map((s) => s.key))).toEqual([
			['top-20', 'top-75'], ['on-watchlist', 'not-on-watchlist'], ['not-watched', 'watched'],
		]);
	});
});

describe('selectInGroup', () => {
	const watchlist = [IN_LIST, NOT_IN_LIST];
	const top = [TOP_20, TOP_75];

	it('switches the rest of the group off when one is chosen', () => {
		const inList = selectInGroup(watchlist, NO_REFINEMENT, 'on-watchlist');
		const notInList = selectInGroup(watchlist, inList, 'not-on-watchlist');
		expect(notInList).toEqual({ on: ['not-on-watchlist'], off: [] });
	});

	it('turns a default-on set off for "Any", and back on by choosing it', () => {
		const any = selectInGroup(top, NO_REFINEMENT, null);
		expect(any).toEqual({ on: [], off: ['top-75'] });
		expect(isSetActive(TOP_75, any)).toBe(false);
		expect(selectInGroup(top, any, 'top-75')).toEqual({ on: [], off: [] });
	});

	it('choosing another step switches the default-on one off', () => {
		expect(selectInGroup(top, NO_REFINEMENT, 'top-20')).toEqual({ on: ['top-20'], off: ['top-75'] });
	});

	it('leaves other groups and the sort alone', () => {
		const start = { on: ['not-watched'], off: ['top-75'], sort: 'score' as const, sort_dir: 'asc' as const };
		expect(selectInGroup(watchlist, start, 'on-watchlist')).toEqual({ ...start, on: ['not-watched', 'on-watchlist'] });
	});
});

describe('browseRefinements sanitize', () => {
	it('keeps what is valid and drops the rest', () => {
		restoreAllPersistedFilters({
			'phsar.filter.browse': {
				fresh: { on: ['top-20', 3], off: 'top-75', sort: 'score', sort_dir: 'sideways' },
				'next-season': { on: [], off: ['top-75'], sort: 'loudest', sort_dir: 'asc' },
				junk: 'not an object',
				list: ['not', 'a', 'record'],
			},
		});
		expect(get(browseRefinements)).toEqual({
			fresh: { on: ['top-20'], off: [], sort: 'score' },
			'next-season': { on: [], off: ['top-75'], sort_dir: 'asc' },
		});
	});
});

describe('browseRefinements lifecycle', () => {
	it('keeps the toggles across a detail detour and drops them on leaving Browse', () => {
		browseRefinements.set({ fresh: { on: ['top-20'], off: ['top-75'] } });
		applyFilterLifecycle('/anime');
		applyFilterLifecycle('/browse/fresh');
		expect(get(browseRefinements).fresh.on).toEqual(['top-20']);
		applyFilterLifecycle('/search');
		expect(get(browseRefinements)).toEqual({});
	});
});

describe('refinedSearch', () => {
	const carousel = (sortable: boolean): BrowseCarousel => ({
		key: 'next-season', title: 'Coming next season', params: { sort: 'popularity' }, see_all_limit: 1000,
		sortable, filter_sets: [],
	});
	const chosen = { on: [], off: [], sort: 'score' as const, sort_dir: 'asc' as const };

	it('applies a chosen sort to a sortable carousel', () => {
		expect(refinedSearch(carousel(true), chosen)).toMatchObject({ sort: 'score', sort_dir: 'asc' });
	});

	it('keeps an unsortable carousel in its own order whatever was stored', () => {
		expect(refinedSearch(carousel(false), chosen)).toEqual({ query: '', search_type: 'title', sort: 'popularity' });
	});
});
