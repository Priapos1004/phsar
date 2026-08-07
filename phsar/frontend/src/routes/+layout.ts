import type { LayoutLoad } from './$types';
import { browser } from '$app/environment';
import { redirect } from '@sveltejs/kit';
import { get } from 'svelte/store';
import { token } from '$lib/stores/auth';
import { expFromToken, isSessionLive } from '$lib/utils/sessionTimeout';

/**
 * Navigation guard: bounce an unauthenticated or expired visitor to /login.
 *
 * Decides LOCALLY off the JWT's `exp`, and must stay synchronous and
 * request-free. Kit re-runs this load far more often than "per page": it touches
 * `url.pathname`, a tracked URL property, so ANY url change invalidates it —
 * query-param-only ones like ?tab=ratings -> ?tab=stats included — and
 * `data-sveltekit-preload-data="hover"` runs universal loads on hover, so a call
 * here would front every navigation AND every link hover.
 *
 * Local costs nothing in authority: the server rejects a bad token on every
 * actual API call this page makes, and the JWT is signed so a client can't forge
 * a later `exp`. The worst case a local check admits is a still-unexpired token
 * belonging to a since-deleted user, whose first real request 401s anyway.
 *
 * Expiry DURING a session is not this function's job — `SessionTimeoutBanner`
 * owns the 1s tick, the silent refresh and the countdown. This only catches a
 * token that was already dead on arrival (a tab left closed overnight).
 */
export const load: LayoutLoad = ({ url }) => {
	if (!browser) return;
	if (url.pathname === '/login' || url.pathname === '/register') return;

	const raw = get(token);
	if (!raw) throw redirect(302, '/login');

	// An unparseable token yields no exp, hence not live — see expFromToken.
	if (!isSessionLive(expFromToken(raw), Date.now())) {
		token.set(null);
		throw redirect(302, '/login');
	}
};
