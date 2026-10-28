<script lang="ts">
	import { page } from '$app/state';
	import TabNav, { activeTab } from '$lib/components/TabNav.svelte';
	import BrowsePageRows from '$lib/components/BrowsePageRows.svelte';
	import DiscoverTab from '$lib/components/DiscoverTab.svelte';
	import * as cls from '$lib/styles/classes';

	const TABS = [
		{ key: 'news', label: 'News' },
		{ key: 'discover', label: 'Discover' },
	];
	const DEFAULT_TAB = 'news';

	let active = $derived(activeTab(page.url, TABS, DEFAULT_TAB));
	// Discover mounts on its first visit, so opening Browse never loads the wheel unseen.
	let discoverOpened = $state(false);
	$effect(() => {
		if (active === 'discover') discoverOpened = true;
	});
</script>

<svelte:head><title>Browse — Phsar</title></svelte:head>

<div class="{cls.pageWidth} space-y-6">
	<h1 class="text-2xl font-bold text-white">Browse</h1>

	<TabNav tabs={TABS} {active} basePath="/browse" ariaLabel="Browse sections" />

	<!-- Hidden rather than unmounted on another tab, so coming back keeps each row where it
	     was scrolled, with no skeletons while the rows re-observe. -->
	<div hidden={active !== 'news'}>
		<BrowsePageRows page="news" />
	</div>
	{#if discoverOpened}
		<div hidden={active !== 'discover'}>
			<DiscoverTab />
		</div>
	{/if}
</div>
