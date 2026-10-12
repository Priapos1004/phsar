<script lang="ts">
	// A browse page's rows, top to bottom, as the backend lays them out (docs/features/browse.md).
	import { getContext, onMount } from 'svelte';
	import { page as route } from '$app/state';
	import { ApiError } from '$lib/api';
	import BrowseCarousel from '$lib/components/BrowseCarousel.svelte';
	import { browsePage } from '$lib/stores/browseRows';
	import { ensureRatingCoverage } from '$lib/stores/ratingCoverage';
	import type { BrowseCarousel as Carousel, BrowsePageKey } from '$lib/types/api';
	import { consumeFocus, splitCarouselFocus } from '$lib/utils/scrollFocus';

	let { page }: { page: BrowsePageKey } = $props();

	const getUserRole = getContext<() => string | null>('userRole');
	let isGuest = $derived(getUserRole?.() === 'restricted_user');

	let carousels = $state<Carousel[] | null>(null);
	let error = $state('');
	// The row, and the tile in it, a back link returned to — read once (`consumeFocus`
	// strips it), before the rows mount.
	let focus = $state<{ key: string; uuid: string | null } | null>(null);

	onMount(async () => {
		const raw = consumeFocus(route.url);
		focus = raw ? splitCarouselFocus(raw) : null;
		// Unawaited: the tiers decorate tiles, so they must not hold the rows back.
		if (!isGuest) void ensureRatingCoverage();
		try {
			carousels = await browsePage(page);
		} catch (e) {
			error = e instanceof ApiError ? e.detail : 'Failed to load these rows.';
		}
	});
</script>

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
