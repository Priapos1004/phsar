<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { consumeFocus, revealFocused } from '$lib/utils/scrollFocus';
	import { ApiError } from '$lib/api';
	import { ensureRatingScores } from '$lib/stores/ratingScores';
	import { userSettings } from '$lib/stores/userSettings';
	import type { RatingScoreItem } from '$lib/types/api';
	import type { RatingsTabKey } from '$lib/components/ratings/types';
	import TabNav from '$lib/components/TabNav.svelte';
	import RatingsListTab from '$lib/components/ratings/RatingsListTab.svelte';
	import RatingsStatsTab from '$lib/components/ratings/RatingsStatsTab.svelte';
	import Notice from '$lib/components/Notice.svelte';
	import { loginUrlReturningTo } from '$lib/utils/returnTo';
	import { Button } from '$lib/components/ui/button';

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

	async function load() {
		loading = true;
		error = '';
		unauthenticated = false;
		try {
			items = await ensureRatingScores();
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

	// Centre the row a back link came from, once the list has rendered — every row
	// renders, so there is nothing to expand first. Plain flag, not $state: it fires
	// once and must not fight the user's own scrolling.
	let revealed = false;
	$effect(() => {
		if (revealed || loading || !items) return;
		revealed = true;
		revealFocused(consumeFocus(page.url));
	});
</script>

<svelte:head><title>Ratings — Phsar</title></svelte:head>

<div class="mx-auto max-w-5xl space-y-6">
	<h1 class="text-2xl font-bold text-white">Ratings</h1>

	<TabNav tabs={TABS} defaultTab={DEFAULT_TAB} basePath="/ratings" ariaLabel="Ratings sections" />

	{#if loading}
		<div class="text-white/60 py-12 text-center">Loading your ratings…</div>
	{:else if unauthenticated}
		<div class="py-12 text-center space-y-3">
			<p class="text-white/70">Sign in to see and analyse your ratings.</p>
			<!-- Carries the route, not the filters: this is a link rendered when the
			     page's own fetch 401s, and by the time it is followed the filter
			     lifecycle has cleared them anyway. -->
			<Button href={loginUrlReturningTo(page.url)}>Sign in</Button>
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
		<!-- Ratings tab stays mounted (preserves list scroll/state); Statistics mounts only
		     while active, so its charts replay their build-up animation on every entry. -->
		<div class:hidden={active !== 'ratings'}>
			<RatingsListTab {items} {nameLanguage} {ratingStep} />
		</div>
		{#if active === 'stats'}
			<RatingsStatsTab {items} {ratingStep} />
		{/if}
	{/if}
</div>
