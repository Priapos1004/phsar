<script lang="ts">
	/**
	 * Sliding-session driver + idle-timeout warning. Mounted once in the layout
	 * sticky container (only while authenticated, never on /login or /register).
	 *
	 * The JWT `exp` is the authoritative idle clock. A 1s tick re-evaluates it
	 * (see lib/utils/sessionTimeout.ts): an active user gets a silent
	 * POST /auth/refresh before the token lapses, an idle user gets a countdown
	 * banner over the last few minutes, and at the deadline `onExpire` fires
	 * (the layout shows its "Session Expired" dialog). Modeled on
	 * MaintenanceBanner — self-contained timers, onMount/onDestroy cleanup.
	 */
	import { onMount } from 'svelte';
	import { get } from 'svelte/store';
	import { jwtDecode } from 'jwt-decode';
	import { token } from '$lib/stores/auth';
	import { api, ApiError } from '$lib/api';
	import {
		evaluateSession,
		formatCountdown,
		TICK_MS,
	} from '$lib/utils/sessionTimeout';
	import type { TokenResponse } from '$lib/types/api';
	import Notice from './Notice.svelte';

	let { onExpire }: { onExpire: () => void } = $props();

	// Non-reactive timers/guards (don't drive the template).
	let lastActivity = 0;
	let refreshInFlight = false;
	// Latched so `onExpire` fires once per lapse, not on every tick at <=0.
	// Reset when a fresh token arrives (login OR a cross-tab refresh) so this
	// tab resurrects instead of staying stuck on the dialog.
	let expired = false;

	// The only reactive piece: ms left while the warning shows (null = hidden).
	let warningRemainingMs = $state<number | null>(null);

	function latchExpired() {
		if (!expired) {
			expired = true;
			onExpire();
		}
	}

	async function doRefresh() {
		// Capture the token we're refreshing; only adopt the new one if the
		// store still holds it on resolve. Drops a response that lands after a
		// logout, a maintenance-503 null, or another tab's change.
		const sentToken = get(token);
		refreshInFlight = true;
		try {
			const res = await api.post<TokenResponse>('/auth/refresh');
			if (get(token) === sentToken) token.set(res.access_token);
		} catch (err) {
			// 401 = the token died between the tick and the request landing →
			// terminal. Network error → ignore; the next tick retries, and if the
			// token genuinely expires the 'logout' branch catches it.
			if (err instanceof ApiError && err.status === 401) latchExpired();
		} finally {
			refreshInFlight = false;
		}
	}

	function evaluate() {
		// Once a lapse has been reported, stay quiet until a fresh token arrives
		// (the token.subscribe below clears `expired`) — otherwise every tick
		// would keep hitting /auth/refresh behind the "Session Expired" dialog.
		if (expired) return;
		// Hidden by default; only the 'warn' branch below re-shows the banner.
		warningRemainingMs = null;
		const value = get(token);
		if (!value) return;

		// A malformed token decodes to undefined exp → evaluateSession returns
		// 'logout', so the dead-session path is handled by the one branch below.
		let exp: number | undefined;
		try {
			exp = jwtDecode<{ exp?: number }>(value).exp;
		} catch {
			exp = undefined;
		}

		const { action, remainingMs } = evaluateSession({
			exp,
			now: Date.now(),
			lastActivity,
		});

		switch (action) {
			case 'logout':
				latchExpired();
				break;
			case 'refresh':
				if (!refreshInFlight) void doRefresh();
				break;
			case 'warn':
				warningRemainingMs = remainingMs;
				break;
			// 'idle' → nothing to do; the banner is already hidden above.
		}
	}

	onMount(() => {
		lastActivity = Date.now();

		// One non-reactive number write per event — cheap enough to skip a
		// throttle (the tick reads `lastActivity` once a second regardless).
		const onActivity = () => {
			lastActivity = Date.now();
		};
		const events = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'click'];
		events.forEach((e) => window.addEventListener(e, onActivity, { passive: true }));

		// Re-check immediately on resume — setInterval is frozen while the tab
		// is backgrounded / the machine sleeps, so an expired token should be
		// caught the instant the tab is visible again, not on the next 1s edge.
		const onVisibility = () => {
			if (!document.hidden) evaluate();
		};
		document.addEventListener('visibilitychange', onVisibility);

		const tickTimer = setInterval(evaluate, TICK_MS);

		// Fires synchronously with the current token (initial evaluate) and on
		// every later change incl. our own refresh + cross-tab storage sync.
		const unsubToken = token.subscribe((val) => {
			if (val) expired = false;
			evaluate();
		});

		return () => {
			events.forEach((e) => window.removeEventListener(e, onActivity));
			document.removeEventListener('visibilitychange', onVisibility);
			clearInterval(tickTimer);
			unsubToken();
		};
	});
</script>

{#if warningRemainingMs !== null}
	<div class="px-4 pt-3">
		<Notice>
			{`You'll be signed out in ${formatCountdown(warningRemainingMs)} due to inactivity — click your mouse to stay signed in.`}
		</Notice>
	</div>
{/if}
