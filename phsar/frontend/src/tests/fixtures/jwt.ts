/**
 * Unsigned JWTs for tests.
 *
 * `jwtDecode` does not verify, so only the payload segment matters — which is
 * what lets a test assert on `sub`, `role` or `exp` without a signing key. Every
 * fake token is built here so that tests reading different claims — the
 * navigation guard's `exp`, the login page's `sub`, the resume stash's owner —
 * cannot disagree about the shape one carries.
 */
export function fakeJwt(claims: { sub?: string; role?: string; exp?: number } = {}): string {
	const payload = btoa(JSON.stringify(claims)).replace(/=+$/, '');
	return `header.${payload}.signature`;
}

/** Seconds-since-epoch, the unit of the `exp` claim. */
export const nowSeconds = () => Math.floor(Date.now() / 1000);
