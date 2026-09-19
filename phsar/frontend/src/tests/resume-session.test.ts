/**
 * `utils/resumeSession` — the stash that carries a lapsed session's filters
 * across the re-login.
 *
 * The owner check is the load-bearing one: it is the ONLY thing standing between
 * one user's filter set and the next person to sign in at the same browser, and
 * a `foreign` verdict is also what stops that person inheriting the `?next=`
 * captured for someone else.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';
import {
	createPersistedFilter,
	pickKey,
	pickStrings,
	resetAllPersistedFilters,
} from '$lib/stores/persistedFilter';
import { token } from '$lib/stores/auth';
import {
	captureReturnTarget,
	clearResume,
	consumeResume,
	landAfterAuth,
	stashResume,
} from '$lib/utils/resumeSession';
import { fakeJwt } from './fixtures/jwt';

interface Demo {
	view: 'grid' | 'table';
	genres: string[];
}

const DEFAULTS: Demo = { view: 'grid', genres: [] };
const VIEWS: Record<Demo['view'], true> = { grid: true, table: true };
const FILLED: Demo = { view: 'table', genres: ['Action'] };

// Registered once, at module evaluation, exactly as the real filters are.
const demo = createPersistedFilter<Demo>({
	key: 'test.resume.demo',
	version: 1,
	defaults: DEFAULTS,
	sanitize: (raw) => ({
		view: pickKey(raw.view, VIEWS, DEFAULTS.view),
		genres: pickStrings(raw.genres),
	}),
});

const THREE_HOURS = 3 * 60 * 60 * 1000;
const envelope = () => JSON.parse(sessionStorage.getItem('phsar.resume')!);

/** What every capture site does, in order: stash, then clear the live stores. */
function expireSessionFor(owner: string) {
	stashResume(owner);
	resetAllPersistedFilters();
}

describe('resumeSession', () => {
	beforeEach(() => {
		sessionStorage.clear();
		resetAllPersistedFilters();
	});

	afterEach(() => vi.useRealTimers());

	it('restores the same user, in the same tab, right away', () => {
		demo.set(FILLED);
		expireSessionFor('sam');
		expect(get(demo)).toEqual(DEFAULTS); // the live stores really were cleared

		expect(consumeResume('sam')).toBe('restored');
		expect(get(demo)).toEqual(FILLED);
	});

	// The whole point of the owner stamp.
	it('reports foreign and restores nothing for a different user', () => {
		demo.set(FILLED);
		expireSessionFor('sam');

		expect(consumeResume('alex')).toBe('foreign');
		expect(get(demo)).toEqual(DEFAULTS);
	});

	it('reports stale past the TTL and restores nothing', () => {
		vi.useFakeTimers();
		demo.set(FILLED);
		expireSessionFor('sam');

		vi.advanceTimersByTime(THREE_HOURS + 1);
		expect(consumeResume('sam')).toBe('stale');
		expect(get(demo)).toEqual(DEFAULTS);
	});

	it('still restores just inside the TTL', () => {
		vi.useFakeTimers();
		demo.set(FILLED);
		expireSessionFor('sam');

		vi.advanceTimersByTime(THREE_HOURS - 1000);
		expect(consumeResume('sam')).toBe('restored');
		expect(get(demo)).toEqual(FILLED);
	});

	// One-shot, whatever the verdict: a stash that survived its first login could
	// be applied to a later, unrelated one in the same tab.
	it.each([
		['a match', 'sam'],
		['a mismatch', 'alex'],
	])('removes the key after %s', (_label, owner) => {
		demo.set(FILLED);
		expireSessionFor('sam');

		consumeResume(owner);
		expect(sessionStorage.getItem('phsar.resume')).toBeNull();
		expect(consumeResume('sam')).toBe('none');
	});

	it('reports none when nothing was ever stashed', () => {
		expect(consumeResume('sam')).toBe('none');
	});

	// "Cannot prove this is the same user" has to land on the same side as "this
	// is a different user" — an undecodable token must not inherit a filter set.
	it('treats an unidentifiable session as foreign and drops the stash', () => {
		demo.set(FILLED);
		expireSessionFor('sam');

		expect(consumeResume(null)).toBe('foreign');
		expect(get(demo)).toEqual(DEFAULTS);
		expect(sessionStorage.getItem('phsar.resume')).toBeNull();
	});

	it('writes nothing without an owner to bind to', () => {
		demo.set(FILLED);
		stashResume(null);
		expect(sessionStorage.getItem('phsar.resume')).toBeNull();
	});

	it('clearResume drops the stash, as a deliberate sign-out does', () => {
		demo.set(FILLED);
		expireSessionFor('sam');

		clearResume();
		expect(consumeResume('sam')).toBe('none');
		expect(get(demo)).toEqual(DEFAULTS);
	});

	it('discards an envelope from another version rather than half-applying it', () => {
		sessionStorage.setItem(
			'phsar.resume',
			JSON.stringify({ v: 99, owner: 'sam', at: Date.now(), filters: { 'test.resume.demo': FILLED } }),
		);
		expect(consumeResume('sam')).toBe('none');
		expect(get(demo)).toEqual(DEFAULTS);
	});

	it('survives corrupt JSON', () => {
		sessionStorage.setItem('phsar.resume', '{not json');
		expect(consumeResume('sam')).toBe('none');
	});

	// The stash is sessionStorage like any other key, so it gets the same
	// treatment as the live ones: whitelisted on the way back in, never trusted.
	it('sanitizes restored values rather than trusting them', () => {
		sessionStorage.setItem(
			'phsar.resume',
			JSON.stringify({
				v: 1,
				owner: 'sam',
				at: Date.now(),
				filters: { 'test.resume.demo': { view: 'wall', genres: ['ok', 7, null] } },
			}),
		);
		expect(consumeResume('sam')).toBe('restored');
		expect(get(demo)).toEqual({ view: 'grid', genres: ['ok'] });
	});

	it('stamps the owner and a timestamp onto the envelope', () => {
		demo.set(FILLED);
		stashResume('sam');
		expect(envelope()).toMatchObject({ v: 1, owner: 'sam' });
		expect(typeof envelope().at).toBe('number');
	});
});

const ORIGIN = 'https://phsar.test';

describe('captureReturnTarget', () => {
	beforeEach(() => {
		sessionStorage.clear();
		resetAllPersistedFilters();
		token.set(null);
	});

	it('returns the login URL carrying the page, and stashes the token owner', () => {
		token.set(fakeJwt({ sub: 'sam' }));
		demo.set(FILLED);

		const target = captureReturnTarget(new URL(`${ORIGIN}/watchlist?tab=stats`));

		expect(target).toBe(`/login?next=${encodeURIComponent('/watchlist?tab=stats')}`);
		expect(envelope()).toMatchObject({ owner: 'sam' });
	});

	// The guard's no-token branch runs through the same helper.
	it('still returns the route when there is no token to stash against', () => {
		expect(captureReturnTarget(new URL(`${ORIGIN}/ratings`))).toBe('/login?next=%2Fratings');
		expect(sessionStorage.getItem('phsar.resume')).toBeNull();
	});
});

describe('landAfterAuth', () => {
	beforeEach(() => {
		sessionStorage.clear();
		resetAllPersistedFilters();
	});

	it('sends the same user back to their next, filters restored', () => {
		demo.set(FILLED);
		expireSessionFor('sam');

		expect(landAfterAuth(fakeJwt({ sub: 'sam' }), '/watchlist')).toBe('/watchlist');
		expect(get(demo)).toEqual(FILLED);
	});

	// The coupling this function exists to own: a foreign stash invalidates the
	// route captured beside it, not just the filters.
	it('sends a different user home, dropping the next captured for someone else', () => {
		demo.set(FILLED);
		expireSessionFor('sam');

		expect(landAfterAuth(fakeJwt({ sub: 'alex' }), '/watchlist')).toBe('/');
		expect(get(demo)).toEqual(DEFAULTS);
	});

	// Stale keeps the route — this is what lets a shared link work the next day.
	it('keeps the next for the same user past the TTL', () => {
		vi.useFakeTimers();
		expireSessionFor('sam');
		vi.advanceTimersByTime(THREE_HOURS + 1);

		expect(landAfterAuth(fakeJwt({ sub: 'sam' }), '/watchlist')).toBe('/watchlist');
	});

	it('honours a next with no stash at all — the shared-link case', () => {
		expect(landAfterAuth(fakeJwt({ sub: 'sam' }), '/anime?uuid=abc')).toBe('/anime?uuid=abc');
	});

	it.each([
		['no next is offered', null, '/'],
		['an undecodable token arrives', null, '/'],
	])('falls back to home when %s', (_label, next, expected) => {
		expect(landAfterAuth(fakeJwt({ sub: 'sam' }), next)).toBe(expected);
	});

	it('treats an undecodable token as a stranger', () => {
		expireSessionFor('sam');
		expect(landAfterAuth('not-a-jwt', '/watchlist')).toBe('/');
	});
});
