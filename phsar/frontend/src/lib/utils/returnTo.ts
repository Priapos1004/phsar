/**
 * Where a login should send the user back to.
 *
 * The route travels as a `next` query param on the /login URL; the list filters,
 * which cannot fit in one, travel separately in `utils/resumeSession`. Why the
 * round-trip needs both carriers is in `docs/features/navigation.md`.
 *
 * Everything a detail page needs is already in its URL (`uuid`, the search
 * token `q`, the `from` origin marker, `tab`), so restoring the path restores
 * the back button and the active tab with it.
 *
 * `next` is attacker-controlled — it arrives in a URL anyone can hand a user —
 * so it is untrusted input on the way in, however it was produced.
 */

/** The pages that ASK for credentials, as opposed to the ones that need them. */
const AUTH_PAGES = ['/login', '/register'];

export function isAuthPage(pathname: string): boolean {
	return AUTH_PAGES.includes(pathname);
}

/**
 * Never a return target. The auth pages would loop (they are the thing being
 * returned from) and `/health` is the container liveness endpoint, not a page.
 */
const NEVER_RETURN_TO = [...AUTH_PAGES, '/health'];

/**
 * Cap on a return path. The longest legitimate one is a search deep link —
 * `/search?q=` plus the backend's `MAX_TOKEN_LENGTH` of 1400 — so this clears
 * it with room to spare while staying inside the ~2000 chars that are safe in a
 * URL across browsers.
 */
const MAX_RETURN_PATH_LENGTH = 1800;

/**
 * Validate a raw `next` into a same-origin path, or null.
 *
 * Resolving against `origin` and comparing the result's origin IS the check: it
 * rejects `https://evil.com`, protocol-relative `//evil.com` and the backslash
 * form `/\evil.com` in one step. The last is why a hand-rolled "starts with `/`
 * but not `//`" test is not enough — for special schemes the URL parser
 * normalises `\` to `/` in the authority position, so `/\evil.com` navigates
 * off-site while passing that test.
 *
 * Whether the path names a real route is deliberately NOT checked. The boundary
 * that matters is the origin — a same-origin path can do nothing the user could
 * not do by typing it, and the worst case is the 404 they would have got anyway.
 * An allowlist of known routes would instead be a second copy of the route table
 * whose failure mode is silent: every route added later stops round-tripping
 * until someone remembers this file, and `/admin/jobs/[uuid]` needs patterns
 * before it can be expressed at all.
 */
export function safeReturnPath(raw: string | null | undefined, origin: string): string | null {
	if (!raw || raw.length > MAX_RETURN_PATH_LENGTH) return null;
	try {
		const resolved = new URL(raw, origin);
		if (resolved.origin !== origin) return null;
		if (NEVER_RETURN_TO.includes(resolved.pathname)) return null;
		// The hash is dropped rather than carried: no route reads one, and
		// preserving it would hand back a fragment nothing here validated.
		return `${resolved.pathname}${resolved.search}`;
	} catch {
		return null;
	}
}

/**
 * The /login URL that returns to `url` — or a bare `/login` when `url` is not a
 * place worth coming back to.
 *
 * Runs its own URL through the same validator as an incoming `next`, so the
 * loop cases are excluded once rather than at each site that leaves for /login.
 *
 * The home page is dropped here rather than in the validator, because it is not
 * a safety question: `?next=%2F` is simply where a bare /login already goes, and
 * emitting it buys a noisier URL and a hint line stating the default.
 */
export function loginUrlReturningTo(url: URL): string {
	const target = safeReturnPath(`${url.pathname}${url.search}`, url.origin);
	return urlWithNext('/login', target === '/' ? null : target);
}

/**
 * `base` carrying `next`, or `base` alone.
 *
 * The param's name and its encoding are spelled here and nowhere else — the
 * cross-links between /login and /register need the same URL with the other
 * base, and hand-rolling it in markup puts the spelling in three places.
 */
export function urlWithNext(base: string, next: string | null): string {
	return next ? `${base}?next=${encodeURIComponent(next)}` : base;
}

/**
 * How the login page names where it will send the user.
 *
 * Derived from the pathname alone so the unauthenticated login page needs no
 * fetch — it cannot resolve an anime title behind `?uuid=`, and asking would
 * 401 anyway. Naming the destination is the point: a `next` can outlive the
 * user's memory of clicking the link that set it.
 *
 * This IS the route-table copy `safeReturnPath` above refuses to keep, and the
 * difference is the failure mode. A route missing from a validation allowlist
 * silently stops working; a route missing from here reads "the page you opened",
 * which is true, just less specific. A copy is affordable exactly when being
 * out of date degrades instead of breaking.
 */
const RETURN_LABELS: Record<string, string> = {
	// Never produced by loginUrlReturningTo, but a hand-written `next` reaches it.
	'/': 'the home page',
	'/anime': 'the anime page',
	'/media': 'the media page',
	'/search': 'your search',
	'/ratings': 'your ratings',
	'/watchlist': 'your watchlist',
	'/settings': 'your settings',
	'/library/add': 'the add-to-library page',
	'/admin': 'the admin panel',
};

export function describeReturn(path: string): string {
	return RETURN_LABELS[path.split('?')[0]] ?? 'the page you opened';
}
