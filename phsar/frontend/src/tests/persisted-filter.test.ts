import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import {
	createPersistedFilter,
	pickKey,
	pickNumbers,
	pickStrings,
	resetAllPersistedFilters,
} from '$lib/stores/persistedFilter';

interface Demo {
	view: 'grid' | 'table';
	genres: string[];
	limit: number;
}

const DEFAULTS: Demo = { view: 'grid', genres: [], limit: 0 };
const VIEWS: Record<Demo['view'], true> = { grid: true, table: true };
const FILLED: Demo = { view: 'table', genres: ['Action'], limit: 5 };

function sanitize(raw: Record<string, unknown>): Demo {
	return {
		view: pickKey(raw.view, VIEWS, DEFAULTS.view),
		genres: pickStrings(raw.genres),
		limit: typeof raw.limit === 'number' ? raw.limit : DEFAULTS.limit,
	};
}

// A fresh key per fixture keeps unrelated cases from colliding.
let counter = 0;
function makeFilter(version = 1, key = `test.filter.${counter++}`) {
	return { key, store: createPersistedFilter<Demo>({ key, version, defaults: DEFAULTS, sanitize }) };
}

const stored = (key: string) => JSON.parse(sessionStorage.getItem(key)!);

describe('createPersistedFilter', () => {
	beforeEach(() => sessionStorage.clear());

	it('starts at the defaults when nothing is stored', () => {
		expect(get(makeFilter().store)).toEqual(DEFAULTS);
	});

	it('writes a change through to sessionStorage', () => {
		const { key, store } = makeFilter();
		store.set(FILLED);
		expect(stored(key)).toEqual({ v: 1, state: FILLED });
	});

	// The subscriber fires immediately on construction; writing there would
	// create a defaults-only key on every page load, for every visitor.
	it('does not write anything when the value never changes', () => {
		const { key } = makeFilter();
		expect(sessionStorage.getItem(key)).toBeNull();
	});

	it('does not rewrite when a change round-trips to the same value', () => {
		const { key, store } = makeFilter();
		store.set(FILLED);
		sessionStorage.removeItem(key);
		store.set({ ...FILLED });
		expect(sessionStorage.getItem(key)).toBeNull();
	});

	it('rehydrates a stored value on the next construction', () => {
		const key = 'test.filter.roundtrip';
		makeFilter(1, key).store.set(FILLED);
		expect(get(makeFilter(1, key).store)).toEqual(FILLED);
	});

	it('discards the stored state when the version moved', () => {
		const key = 'test.filter.version';
		makeFilter(1, key).store.set(FILLED);
		expect(get(makeFilter(2, key).store)).toEqual(DEFAULTS);
	});

	it('falls back to the defaults on corrupt JSON', () => {
		const key = 'test.filter.corrupt';
		sessionStorage.setItem(key, '{not json');
		expect(get(makeFilter(1, key).store)).toEqual(DEFAULTS);
	});

	it('falls back to the defaults when the envelope has no state object', () => {
		const key = 'test.filter.noState';
		sessionStorage.setItem(key, JSON.stringify({ v: 1, state: 'nope' }));
		expect(get(makeFilter(1, key).store)).toEqual(DEFAULTS);
	});

	it('sanitizes rehydrated values rather than trusting them', () => {
		const key = 'test.filter.garbage';
		sessionStorage.setItem(
			key,
			JSON.stringify({ v: 1, state: { view: 'wall', genres: ['ok', 7, null], limit: 'x' } })
		);
		expect(get(makeFilter(1, key).store)).toEqual({ view: 'grid', genres: ['ok'], limit: 0 });
	});
});

describe('resetAllPersistedFilters', () => {
	beforeEach(() => sessionStorage.clear());

	it('returns every registered filter to its defaults and persists that', () => {
		const a = makeFilter();
		const b = makeFilter();
		a.store.set(FILLED);
		b.store.set(FILLED);

		resetAllPersistedFilters();

		expect(get(a.store)).toEqual(DEFAULTS);
		expect(get(b.store)).toEqual(DEFAULTS);
		// A defaults-valued key and an absent key rehydrate identically, so
		// persisting the reset is all that is needed to wipe the user's state.
		expect(stored(a.key).state).toEqual(DEFAULTS);
		expect(get(makeFilter(1, a.key).store)).toEqual(DEFAULTS);
	});
});

describe('sanitize helpers', () => {
	it('pickKey accepts a known key and rejects everything else', () => {
		expect(pickKey('table', VIEWS, 'grid')).toBe('table');
		expect(pickKey('wall', VIEWS, 'grid')).toBe('grid');
		expect(pickKey(7, VIEWS, 'grid')).toBe('grid');
		expect(pickKey(undefined, VIEWS, 'grid')).toBe('grid');
	});

	it('pickKey does not accept inherited Object properties', () => {
		expect(pickKey('toString', VIEWS, 'grid')).toBe('grid');
	});

	it('pickStrings keeps only strings', () => {
		expect(pickStrings(['a', 1, null, 'b'])).toEqual(['a', 'b']);
		expect(pickStrings('a')).toEqual([]);
	});

	it('pickNumbers keeps only finite numbers', () => {
		expect(pickNumbers([1, '2', NaN, 3])).toEqual([1, 3]);
		expect(pickNumbers(null)).toEqual([]);
	});
});
