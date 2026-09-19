import type { LayoutLoad } from './$types';
import { browser } from '$app/environment';
import { redirect } from '@sveltejs/kit';
import { get } from 'svelte/store';
import { token } from '$lib/stores/auth';
import { expFromToken, isSessionLive } from '$lib/utils/sessionTimeout';
import { isAuthPage } from '$lib/utils/returnTo';
import { captureReturnTarget } from '$lib/utils/resumeSession';
// Side-effect import: pulls in every filter store, filling the snapshot registry
// before this load can stash from it. resumeSession can't do it itself — see its
// header. Pinned by layout-guard.test.ts, since an organize-imports that dropped
// this would fail nothing else.
import '$lib/utils/filterLifecycle';

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
 * Local costs nothing in *authority*: the JWT is signed so a client can't forge a
 * later `exp`, and the server re-checks the caller on every actual API call, so
 * nothing is granted that the backend wouldn't grant anyway.
 *
 * What it does cost is *recovery*. A token the server has stopped accepting but
 * whose `exp` is still future — after a `SECRET_KEY` rotation, or for a deleted
 * user — passes this guard, and nothing downstream clears it: `api.ts` installs
 * no global 401 handler by design, and the layout's own user-load swallows the
 * 401. The tab then renders signed-in with empty data until `exp` is reached, or
 * until SessionTimeoutBanner's refresh 401s at the threshold. Bounded by
 * ACCESS_TOKEN_EXPIRE_MINUTES, and the manual escape is Sign out.
 *
 * Expiry DURING a session is not this function's job — `SessionTimeoutBanner`
 * owns the 1s tick, the silent refresh and the countdown. This only catches a
 * token that was already dead on arrival (a tab left closed overnight).
 *
 * Both exits carry the attempted URL as `?next=`, so signing in lands back on
 * it — the path a shared link also takes, since a recipient without a session
 * arrives here first. `utils/returnTo` owns the validation on the way back in.
 */
export const load: LayoutLoad = ({ url }) => {
	if (!browser) return;
	if (isAuthPage(url.pathname)) return;

	const raw = get(token);
	if (!raw) throw redirect(302, captureReturnTarget(url));

	// An unparseable token yields no exp, hence not live — see expFromToken.
	if (!isSessionLive(expFromToken(raw), Date.now())) {
		const target = captureReturnTarget(url);
		token.set(null);
		throw redirect(302, target);
	}
};
