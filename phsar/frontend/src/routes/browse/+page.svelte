<script lang="ts">
	import { page } from '$app/state';
	import TabNav, { activeTab } from '$lib/components/TabNav.svelte';
	import BrowsePageRows from '$lib/components/BrowsePageRows.svelte';

	const TABS = [
		{ key: 'news', label: 'News' },
		{ key: 'discover', label: 'Discover' },
	];
	const DEFAULT_TAB = 'news';

	let active = $derived(activeTab(page.url, TABS, DEFAULT_TAB));
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
		<BrowsePageRows page="news" />
	</div>
</div>
