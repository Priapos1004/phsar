<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { API_URL } from '$lib/config';
	import { token } from '$lib/stores/auth';
	import { maintenanceRefresh } from '$lib/stores/maintenance';
	import { onBump } from '$lib/stores/jobs';
	import Notice from './Notice.svelte';
	import type { MaintenanceStatus } from '$lib/types/api';

	// 30s instead of 60s: short maintenance windows (the seasonal sweep
	// can be just a few seconds) would otherwise slip between two polls
	// and the user would never see the banner. 30s halves the worst-case
	// detection lag while keeping the request load trivial. The 503-on-
	// API-call path still triggers an instant refresh via api.ts +
	// `bumpMaintenanceRefresh`, but that only fires when the user is
	// actively making requests — the poll covers idle sessions.
	const POLL_MS = 30_000;
	// Don't bother showing the user a "starts in 31 minutes" notice — by the
	// time they've registered the warning, the window is closer than that
	// anyway. 30 min matches the schedule cron's 20-min default + small buffer.
	const VISIBLE_LEAD_MINUTES = 30;

	let active = $state(false);
	let minutesUntil = $state<number | null>(null);
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	// Bypass api.ts on purpose: a 503 with `{maintenance: true}` would otherwise
	// trigger the global redirect to /login, defeating the pre-warning point
	// of the banner. The status endpoint is allowlisted in the backend's
	// maintenance gate so it returns truthful info during a window too. No
	// auth header — endpoint is public.
	async function fetchStatus() {
		try {
			const res = await fetch(`${API_URL}/maintenance/status`);
			if (!res.ok) return;
			const body: MaintenanceStatus = await res.json();
			const newMinutesUntil = body.scheduled_at
				? Math.round((new Date(body.scheduled_at).getTime() - Date.now()) / 60_000)
				: null;
			// Change guards — Svelte 5 $state setters notify subscribers even
			// when the value is unchanged, which would cascade through the
			// $derived chain on every poll for nothing.
			if (active !== body.active) active = body.active;
			if (minutesUntil !== newMinutesUntil) minutesUntil = newMinutesUntil;
		} catch {
			// Network blip — keep last-known state. The next poll will heal.
		}
	}

	let showCountdown = $derived(
		!active &&
			minutesUntil !== null &&
			minutesUntil > 0 &&
			minutesUntil <= VISIBLE_LEAD_MINUTES,
	);
	// "In progress" wins over the countdown when both are true. A cron retry
	// mid-sweep can legitimately set _scheduled_at to a *future* timestamp
	// for the next window while the current sweep is still active, so the
	// countdown alone would otherwise read "starts in N min" while the API
	// is already 503'ing — a contradictory message.
	let visible = $derived(active || showCountdown);

	let unsubAuth: (() => void) | null = null;
	let unsubRefresh: (() => void) | null = null;

	onMount(() => {
		pollTimer = setInterval(fetchStatus, POLL_MS);
		// Re-fetch on every auth transition (mount, login, logout). Stores
		// fire their subscriber once with the current value, so this also
		// covers the initial fetch-on-mount.
		unsubAuth = token.subscribe(() => {
			void fetchStatus();
		});
		// Explicit refresh signal — api.ts bumps on any 503-with-maintenance
		// response so the banner reacts in ms even when the user's token
		// state didn't change (e.g. submitting login while already
		// token-less). onBump skips the synchronous initial call since
		// the auth subscribe above already drove the first fetch.
		unsubRefresh = onBump(maintenanceRefresh, () => {
			void fetchStatus();
		});
	});

	onDestroy(() => {
		if (pollTimer !== null) clearInterval(pollTimer);
		if (unsubAuth !== null) unsubAuth();
		if (unsubRefresh !== null) unsubRefresh();
	});
</script>

{#if visible}
	<div class="px-4 pt-3">
		<Notice>
			{#if showCountdown}
				{`Scheduled maintenance starts in ~${minutesUntil} ${minutesUntil === 1 ? 'minute' : 'minutes'} — pause your current episode.`}
			{:else}
				Maintenance in progress. Some pages may be unavailable.
			{/if}
		</Notice>
	</div>
{/if}
