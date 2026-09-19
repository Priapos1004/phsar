/**
 * `utils/returnTo` — the validation standing between a `?next=` anyone can craft
 * and a post-login navigation.
 *
 * The open-redirect cases are the reason this file exists: a phishing link to
 * `/login?next=<attacker>` that survived validation would send a user who just
 * typed their password to a page of someone else's choosing, from a URL that
 * looks like the real site right up to the redirect.
 */
import { describe, it, expect } from 'vitest';
import { describeReturn, loginUrlReturningTo, safeReturnPath } from '$lib/utils/returnTo';

const ORIGIN = 'https://phsar.test';

describe('safeReturnPath', () => {
	it('accepts a same-origin path and keeps its query string', () => {
		expect(safeReturnPath('/anime?uuid=abc&from=watchlist', ORIGIN)).toBe(
			'/anime?uuid=abc&from=watchlist',
		);
	});

	it('accepts an absolute URL that is genuinely same-origin', () => {
		expect(safeReturnPath(`${ORIGIN}/ratings?tab=stats`, ORIGIN)).toBe('/ratings?tab=stats');
	});

	it.each([
		['an absolute off-origin URL', 'https://evil.example/steal'],
		['a protocol-relative URL', '//evil.example/steal'],
		// The URL parser normalises `\` to `/` in the authority position for special
		// schemes, so this is `//evil.example` — and the case a "starts with / but
		// not //" check waves straight through.
		['a backslash-authority URL', '/\\evil.example/steal'],
		['a different scheme on the same host', 'http://phsar.test/ratings'],
		['a javascript: URL', 'javascript:alert(1)'],
	])('rejects %s', (_label, raw) => {
		expect(safeReturnPath(raw, ORIGIN)).toBeNull();
	});

	it.each(['/login', '/register', '/health'])('rejects %s, which would loop', (path) => {
		expect(safeReturnPath(path, ORIGIN)).toBeNull();
	});

	it('rejects an absurdly long path rather than building an unusable URL', () => {
		expect(safeReturnPath(`/search?q=${'a'.repeat(2000)}`, ORIGIN)).toBeNull();
	});

	// A real search token is the longest legitimate input, and must fit.
	it('accepts a search deep link at the backend token cap', () => {
		const path = `/search?q=${'a'.repeat(1400)}`;
		expect(safeReturnPath(path, ORIGIN)).toBe(path);
	});

	it.each([null, undefined, ''])('returns null for %s', (raw) => {
		expect(safeReturnPath(raw, ORIGIN)).toBeNull();
	});

	it('drops a fragment rather than handing back something it never checked', () => {
		expect(safeReturnPath('/ratings#secret', ORIGIN)).toBe('/ratings');
	});

	// Deliberately no allowlist of known routes: the boundary is the origin, and a
	// route list here would be a silent second copy of the route table — every
	// route added later would stop round-tripping until someone remembered it.
	it.each([
		['an unknown path', '/quark', '/quark'],
		['a bare relative segment', 'quark', '/quark'],
		['a dynamic route no list could enumerate', '/admin/jobs/abc-123', '/admin/jobs/abc-123'],
	])('honours %s', (_label, raw, expected) => {
		expect(safeReturnPath(raw, ORIGIN)).toBe(expected);
	});
});

describe('loginUrlReturningTo', () => {
	it('encodes the path and query into next', () => {
		expect(loginUrlReturningTo(new URL(`${ORIGIN}/anime?uuid=abc`))).toBe(
			`/login?next=${encodeURIComponent('/anime?uuid=abc')}`,
		);
	});

	// Otherwise signing out on /login, or a second maintenance bounce, builds
	// /login?next=/login and the user never leaves the form.
	it.each(['/login', '/register'])('produces a bare /login from %s', (path) => {
		expect(loginUrlReturningTo(new URL(`${ORIGIN}${path}`))).toBe('/login');
	});

	// ?next=%2F is where a bare /login already goes, so emitting it buys only a
	// noisier URL and a hint line announcing the default.
	it('produces a bare /login from the home page', () => {
		expect(loginUrlReturningTo(new URL(`${ORIGIN}/`))).toBe('/login');
	});

	it('round-trips through safeReturnPath', () => {
		const url = new URL(`${ORIGIN}/watchlist?tab=stats`);
		const next = new URL(loginUrlReturningTo(url), ORIGIN).searchParams.get('next');
		expect(safeReturnPath(next, ORIGIN)).toBe('/watchlist?tab=stats');
	});
});

describe('describeReturn', () => {
	it.each([
		['/anime?uuid=abc', 'the anime page'],
		['/media?uuid=abc', 'the media page'],
		['/watchlist?tab=stats', 'your watchlist'],
		['/search?q=tok', 'your search'],
	])('names %s as "%s"', (path, expected) => {
		expect(describeReturn(path)).toBe(expected);
	});

	it('falls back for a route it does not name', () => {
		expect(describeReturn('/admin/jobs/abc')).toBe('the page you opened');
	});
});
