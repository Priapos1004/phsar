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

/** A syntactically valid unsigned JWT whose payload carries `exp` (seconds).
 *  Only the payload segment is ever read — jwtDecode does not verify. */
function tokenWithExp(expSeconds: number): string {
	const payload = btoa(JSON.stringify({ sub: 'someone', role: 'user', exp: expSeconds }))
		.replace(/=+$/, '');
	return `header.${payload}.signature`;
}

const nowSeconds = () => Math.floor(Date.now() / 1000);

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
		expect(await runGuard('/ratings')).toEqual({ redirected: true, location: '/login' });
	});

	it('allows a live token through', async () => {
		token.set(tokenWithExp(nowSeconds() + 600));
		expect((await runGuard('/ratings')).redirected).toBe(false);
	});

	it('redirects AND clears an expired token', async () => {
		token.set(tokenWithExp(nowSeconds() - 1));
		expect(await runGuard('/ratings')).toEqual({ redirected: true, location: '/login' });
		// Clearing matters: leaving the dead token in localStorage would have every
		// later API call 401 instead of the user simply being asked to log in.
		expect(get(token)).toBeNull();
	});

	it('treats an unparseable token as expired rather than trusting it', async () => {
		token.set('not-a-jwt');
		expect(await runGuard('/ratings')).toEqual({ redirected: true, location: '/login' });
		expect(get(token)).toBeNull();
	});

	it('treats a token with no exp claim as expired', async () => {
		const payload = btoa(JSON.stringify({ sub: 'someone' })).replace(/=+$/, '');
		token.set(`header.${payload}.sig`);
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
