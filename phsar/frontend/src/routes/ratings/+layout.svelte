<script lang="ts">
	import { onDestroy } from 'svelte';
	import { clearRatingsFilter } from '$lib/stores/ratingsFilter';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	// Cascades over the /ratings route; clearing here means the view/sort/filter
	// controls survive the ratings↔stats tab switch but reset when leaving the
	// section (or on a hard refresh). Same pattern as the admin layout.
	onDestroy(clearRatingsFilter);
</script>

{@render children()}
