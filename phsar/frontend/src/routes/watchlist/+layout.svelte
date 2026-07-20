<script lang="ts">
	import { onDestroy } from 'svelte';
	import { clearWatchlistFilter } from '$lib/stores/watchlistFilter';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	// Reset the list controls when leaving the section (keeps them across the
	// watchlists↔tags tab switch); same pattern as the ratings/admin layouts.
	onDestroy(clearWatchlistFilter);
</script>

{@render children()}
