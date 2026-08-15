/**
 * Root-layout navigation guard (`routes/+layout.ts`).
 *
 * Worth its own tests now that the decision is LOCAL: it used to delegate to
 * GET /auth/validate, where the server was the thing being tested. Deciding off
 * the JWT's `exp` means this logic is ours, and it is the only thing standing
 * between a stale tab and an authenticated page.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { get } from 'svelte/store';
import { token } from '$lib/stores/auth';
import { load } from '../routes/+layout';
import { fakeJwt, nowSeconds } from './fixtures/jwt';

const tokenWithExp = (expSeconds: number) =>
	fakeJwt({ sub: 'someone', role: 'user', exp: expSeconds });

/** Run the guard and report whether it redirected, and to where. */
async function runGuard(pathname: string) {
	try {
		await (load as (arg: unknown) => unknown)({ url: new URL(`http://test${pathname}`) });
		return { redirected: false, location: null as string | null };
	} catch (e) {
		// SvelteKit's redirect() throws a { status, location } object.
		const r = e as { status?: number; location?: string };
		if (r?.status && r?.location) return { redirected: true, location: r.location };
		throw e;
	}
}

describe('root layout navigation guard', () => {
	beforeEach(() => {
		localStorage.clear();
		token.set(null);
	});

	it('redirects to /login with no token', async () => {
		expect(await runGuard('/ratings')).toEqual({
			redirected: true,
			location: '/login?next=%2Fratings',
		});
	});

	it('allows a live token through', async () => {
		token.set(tokenWithExp(nowSeconds() + 600));
		expect((await runGuard('/ratings')).redirected).toBe(false);
	});

	it('redirects AND clears an expired token', async () => {
		token.set(tokenWithExp(nowSeconds() - 1));
		expect(await runGuard('/ratings')).toEqual({
			redirected: true,
			location: '/login?next=%2Fratings',
		});
		// Clearing matters: leaving the dead token in localStorage would have every
		// later API call 401 instead of the user simply being asked to log in.
		expect(get(token)).toBeNull();
	});

	it('treats an unparseable token as expired rather than trusting it', async () => {
		token.set('not-a-jwt');
		expect(await runGuard('/ratings')).toEqual({
			redirected: true,
			location: '/login?next=%2Fratings',
		});
		expect(get(token)).toBeNull();
	});

	// The query string IS the state on every route that has any: `uuid` names the
	// title, `q` carries the whole search, `from` draws the back button. Capturing
	// only the pathname would return the user to a detail page with no subject.
	it('carries the query string into next, not just the pathname', async () => {
		expect((await runGuard('/anime?uuid=abc&from=watchlist')).location).toBe(
			`/login?next=${encodeURIComponent('/anime?uuid=abc&from=watchlist')}`,
		);
	});

	it('stashes the expiring user so their filters can be restored', async () => {
		sessionStorage.clear();
		token.set(tokenWithExp(nowSeconds() - 1));
		await runGuard('/watchlist');
		expect(JSON.parse(sessionStorage.getItem('phsar.resume')!).owner).toBe('someone');
	});

	// Pins `+layout.ts`'s side-effect `import '$lib/utils/filterLifecycle'`, whose
	// only job is to evaluate the filter stores so they are registered by the time
	// this load stashes. Nothing else in this file imports them, so dropping that
	// import — an organize-imports would, it binds no symbol — empties the stash
	// here and nowhere else. The real failure it stands in for is silent: filters
	// quietly returning at defaults after a re-login.
	it('stashes real filter state, not an empty registry', async () => {
		sessionStorage.clear();
		token.set(tokenWithExp(nowSeconds() - 1));
		await runGuard('/watchlist');
		expect(Object.keys(JSON.parse(sessionStorage.getItem('phsar.resume')!).filters)).toEqual(
			expect.arrayContaining(['phsar.filter.ratings', 'phsar.filter.watchlist']),
		);
	});

	// Nobody's filters to keep, and nobody to bind them to. The route still travels.
	it('stashes nothing when there was no token at all', async () => {
		sessionStorage.clear();
		expect((await runGuard('/watchlist')).redirected).toBe(true);
		expect(sessionStorage.getItem('phsar.resume')).toBeNull();
	});

	// The home page is already where a bare /login lands, so capturing it would
	// only add a param and a hint line both restating the default.
	it('does not add a next when the home page is what was blocked', async () => {
		expect(await runGuard('/')).toEqual({ redirected: true, location: '/login' });
	});

	it('treats a token with no exp claim as expired', async () => {
		token.set(fakeJwt({ sub: 'someone' }));
		expect((await runGuard('/ratings')).redirected).toBe(true);
	});

	// The auth pages must short-circuit BEFORE the token is inspected — otherwise
	// an expired token sitting on /login redirects to /login forever.
	it.each([
		['/login', 'no token', null],
		['/login', 'an expired token', tokenWithExp(nowSeconds() - 1)],
		['/register', 'no token', null],
		['/register', 'an expired token', tokenWithExp(nowSeconds() - 1)],
	])('never redirects away from %s with %s', async (pathname, _label, tok) => {
		token.set(tok);
		expect((await runGuard(pathname)).redirected).toBe(false);
	});
});
