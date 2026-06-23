<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { page } from '$app/state';
	import { api, ApiError } from '$lib/api';
	import { userSettings } from '$lib/stores/userSettings';
	import type { RatingScoreItem } from '$lib/types/api';
	import type { RatingsTabKey } from '$lib/components/ratings/types';
	import RatingsTabNav from '$lib/components/ratings/RatingsTabNav.svelte';
	import RatingsListTab from '$lib/components/ratings/RatingsListTab.svelte';
	import RatingsStatsTab from '$lib/components/ratings/RatingsStatsTab.svelte';
	import Notice from '$lib/components/Notice.svelte';
	import { Button } from '$lib/components/ui/button';

	const getUserRole = getContext<() => string | null>('userRole');

	const TABS: { key: RatingsTabKey; label: string }[] = [
		{ key: 'ratings', label: 'Ratings' },
		{ key: 'stats', label: 'Statistics' },
	];
	const DEFAULT_TAB: RatingsTabKey = 'ratings';
	const TAB_KEYS = new Set(TABS.map((t) => t.key));

	let active = $derived.by(() => {
		const raw = page.url.searchParams.get('tab');
		return raw && TAB_KEYS.has(raw as RatingsTabKey) ? (raw as RatingsTabKey) : DEFAULT_TAB;
	});

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');
	let ratingStep = $derived(Number($userSettings?.rating_step ?? '0.5'));

	let items = $state<RatingScoreItem[] | null>(null);
	let loading = $state(true);
	let error = $state('');
	let unauthenticated = $state(false);

	// The Statistics tab mounts ~8 ECharts; defer that construction until the
	// user actually opens the tab (the only deviation from the admin page's
	// eager-render-everything). Once visited it stays mounted, so re-switching
	// is instant — the data is already in hand from the single fetch.
	let visitedStats = $state(false);
	$effect(() => {
		if (active === 'stats') visitedStats = true;
	});

	async function load() {
		loading = true;
		error = '';
		unauthenticated = false;
		try {
			items = await api.get<RatingScoreItem[]>('/ratings/scores');
		} catch (e) {
			if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
				unauthenticated = true;
			} else {
				error = e instanceof ApiError ? e.detail : 'Failed to load your ratings.';
			}
		} finally {
			loading = false;
		}
	}

	onMount(load);

	let isEmpty = $derived(items !== null && items.length === 0);
</script>

<svelte:head><title>Ratings — Phsar</title></svelte:head>

<div class="mx-auto max-w-5xl space-y-6">
	<h1 class="text-2xl font-bold text-white">Ratings</h1>

	<RatingsTabNav tabs={TABS} defaultTab={DEFAULT_TAB} />

	{#if loading}
		<div class="text-white/60 py-12 text-center">Loading your ratings…</div>
	{:else if unauthenticated}
		<div class="py-12 text-center space-y-3">
			<p class="text-white/70">Sign in to see and analyse your ratings.</p>
			<Button href="/login">Sign in</Button>
		</div>
	{:else if error}
		<Notice>{error} <button class="underline" onclick={load}>Try again</button></Notice>
	{:else if isEmpty}
		<div class="py-12 text-center space-y-3">
			<p class="text-white/70">You haven't rated anything yet.</p>
			<p class="text-white/50 text-sm">Find a show and rate it to start building your collection.</p>
			<Button href="/search">Browse anime</Button>
		</div>
	{:else if items}
		<!-- Ratings tab eager-renders; Statistics lazy-mounts on first visit. -->
		<div class:hidden={active !== 'ratings'}>
			<RatingsListTab {items} {nameLanguage} {ratingStep} />
		</div>
		{#if visitedStats}
			<div class:hidden={active !== 'stats'}>
				<RatingsStatsTab {items} {ratingStep} />
			</div>
		{/if}
	{/if}
</div>
