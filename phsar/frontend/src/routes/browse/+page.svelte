<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { page } from '$app/state';
	import { ApiError } from '$lib/api';
	import TabNav, { activeTab } from '$lib/components/TabNav.svelte';
	import BrowseCarousel from '$lib/components/BrowseCarousel.svelte';
	import { browsePage } from '$lib/stores/browseRows';
	import { ensureRatingCoverage } from '$lib/stores/ratingCoverage';
	import type { BrowseCarousel as Carousel } from '$lib/types/api';
	import { consumeFocus, splitCarouselFocus } from '$lib/utils/scrollFocus';

	const TABS = [
		{ key: 'news', label: 'News' },
		{ key: 'discover', label: 'Discover' },
	];
	const DEFAULT_TAB = 'news';

	let active = $derived(activeTab(page.url, TABS, DEFAULT_TAB));

	const getUserRole = getContext<() => string | null>('userRole');
	let isGuest = $derived(getUserRole?.() === 'restricted_user');

	let carousels = $state<Carousel[] | null>(null);
	let error = $state('');
	// The row, and the tile in it, a back link returned to — read once (`consumeFocus`
	// strips it), before the rows mount.
	let focus = $state<{ key: string; uuid: string | null } | null>(null);

	onMount(async () => {
		const raw = consumeFocus(page.url);
		focus = raw ? splitCarouselFocus(raw) : null;
		// Unawaited: the tiers decorate tiles, so they must not hold the rows back.
		if (!isGuest) void ensureRatingCoverage();
		try {
			carousels = await browsePage('news');
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Failed to load browse.';
		}
	});
</script>

<svelte:head><title>Browse — Phsar</title></svelte:head>

<div class="mx-auto max-w-5xl space-y-6">
	<h1 class="text-2xl font-bold text-white">Browse</h1>

	<TabNav tabs={TABS} {active} basePath="/browse" ariaLabel="Browse sections" />

	{#if active === 'discover'}
		<div class="py-12 text-center text-white/60">Will come soon :-)</div>
	{/if}
	<!-- Hidden rather than unmounted on another tab, so coming back keeps each row where it
	     was scrolled, with no skeletons while the rows re-observe. -->
	<div hidden={active !== 'news'}>
		{#if error}
			<div class="py-12 text-center text-white/60">{error}</div>
		{:else if carousels}
			<div class="space-y-8">
				{#each carousels as carousel (carousel.key)}
					<BrowseCarousel {carousel} {isGuest} focus={focus?.key === carousel.key ? focus : null} />
				{/each}
			</div>
		{:else}
			<div class="py-12 text-center text-white/60">Loading…</div>
		{/if}
	</div>
</div>
