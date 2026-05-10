<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { AlertTriangle } from 'lucide-svelte';
	import { API_URL } from '$lib/config';
	import type { MaintenanceStatus } from '$lib/types/api';

	const POLL_MS = 60_000;
	// Don't bother showing the user a "starts in 31 minutes" notice — by the
	// time they've registered the warning, the window is closer than that
	// anyway. 30 min matches the schedule cron's 20-min default + small buffer.
	const VISIBLE_LEAD_MINUTES = 30;

	let active = $state(false);
	let minutesUntil = $state<number | null>(null);
	let pollTimer: ReturnType<typeof setInterval> | null = null;

	// Bypass api.ts on purpose: a 503 with `{maintenance: true}` would otherwise
	// trigger the global redirect to /login?maintenance=1, defeating the
	// pre-warning point of the banner. The status endpoint is allowlisted in
	// the backend's maintenance gate so it returns truthful info during a
	// window too. No auth header — endpoint is public.
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
		minutesUntil !== null && minutesUntil > 0 && minutesUntil <= VISIBLE_LEAD_MINUTES,
	);
	// "Starts in N min" wins over "in progress" when both are true: if the
	// schedule wasn't cleared yet but the worker already flipped active,
	// the more-actionable message is still the countdown.
	let visible = $derived(showCountdown || active);

	onMount(() => {
		void fetchStatus();
		pollTimer = setInterval(fetchStatus, POLL_MS);
	});

	onDestroy(() => {
		if (pollTimer !== null) clearInterval(pollTimer);
	});
</script>

{#if visible}
	<div
		role="status"
		class="flex items-center justify-center gap-2 px-4 py-2 text-sm border-b border-yellow-500/40 bg-yellow-500/10 text-yellow-900 dark:text-yellow-100"
	>
		<AlertTriangle class="w-4 h-4 shrink-0" />
		{#if showCountdown}
			<span>{`Scheduled maintenance starts in ${minutesUntil} ${minutesUntil === 1 ? 'minute' : 'minutes'} — please save your work.`}</span>
		{:else}
			<span>Maintenance in progress. Some pages may be unavailable.</span>
		{/if}
	</div>
{/if}
