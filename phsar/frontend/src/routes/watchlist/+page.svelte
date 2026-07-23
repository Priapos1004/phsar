<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { page } from '$app/state';
	import { api, ApiError } from '$lib/api';
	import { userSettings } from '$lib/stores/userSettings';
	import { refreshTags } from '$lib/stores/tags';
	import type { WatchlistItem } from '$lib/types/api';
	import type { WatchlistTabKey } from '$lib/stores/watchlistFilter';
	import TabNav from '$lib/components/TabNav.svelte';
	import WatchlistListTab from '$lib/components/watchlist/WatchlistListTab.svelte';
	import WatchlistTagsTab from '$lib/components/watchlist/WatchlistTagsTab.svelte';
	import WatchlistStatsTab from '$lib/components/watchlist/WatchlistStatsTab.svelte';
	import Notice from '$lib/components/Notice.svelte';
	import { Button } from '$lib/components/ui/button';

	const TABS: { key: WatchlistTabKey; label: string }[] = [
		{ key: 'watchlists', label: 'Watchlists' },
		{ key: 'stats', label: 'Statistics' },
		{ key: 'tags', label: 'Lists' },
	];
	const DEFAULT_TAB: WatchlistTabKey = 'watchlists';
	const TAB_KEYS = new Set(TABS.map((t) => t.key));

	let active = $derived.by(() => {
		const raw = page.url.searchParams.get('tab');
		return raw && TAB_KEYS.has(raw as WatchlistTabKey) ? (raw as WatchlistTabKey) : DEFAULT_TAB;
	});

	const getUserRole = getContext<() => string | null>('userRole');
	let isRestricted = $derived(getUserRole() === 'restricted_user');
	let nameLanguage = $derived($userSettings?.name_language ?? 'english');

	let items = $state<WatchlistItem[] | null>(null);
	let loading = $state(true);
	let error = $state('');
	let unauthenticated = $state(false);

	async function load() {
		loading = true;
		error = '';
		unauthenticated = false;
		try {
			// Refresh tags too so the Lists tab + the filter chips reflect current counts.
			const [fetched] = await Promise.all([api.get<WatchlistItem[]>('/watchlist/items'), refreshTags()]);
			items = fetched;
		} catch (e) {
			if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
				unauthenticated = true;
			} else {
				error = e instanceof ApiError ? e.detail : 'Failed to load your watchlist.';
			}
		} finally {
			loading = false;
		}
	}

	onMount(() => {
		if (!isRestricted) load();
		else loading = false;
	});

	let isEmpty = $derived(items !== null && items.length === 0);
</script>

<svelte:head><title>Watchlist — Phsar</title></svelte:head>

<div class="mx-auto max-w-5xl space-y-6">
	<h1 class="text-2xl font-bold text-white">Watchlist</h1>

	<!-- Subtabs stay visible for guests too (like the ratings page) so they see what their
	     own account would offer; the writes are gated server-side, so each tab explains that
	     rather than the page dead-ending on a single "not available" notice. -->
	<TabNav tabs={TABS} defaultTab={DEFAULT_TAB} basePath="/watchlist" ariaLabel="Watchlist sections" />

	{#if isRestricted}
		<!-- Soft muted empty-state (not the yellow Notice) — matches the watchlist/ratings
		     empty states; a guest browsing isn't an error condition. -->
		{#if active === 'tags'}
			<div class="py-12 text-center space-y-3">
				<p class="text-white/70">Guest accounts can't create lists.</p>
				<p class="text-white/50 text-sm">Sign in with your own account to organize your watchlists.</p>
			</div>
		{:else if active === 'stats'}
			<div class="py-12 text-center space-y-3">
				<p class="text-white/70">Guest accounts don't have watchlist statistics.</p>
				<p class="text-white/50 text-sm">Sign in with your own account to track your watchlist.</p>
			</div>
		{:else}
			<div class="py-12 text-center space-y-3">
				<p class="text-white/70">Guest accounts can't save to a watchlist.</p>
				<p class="text-white/50 text-sm">Sign in with your own account to bookmark anime and plan what to watch next.</p>
				<Button href="/search">Browse anime</Button>
			</div>
		{/if}
	{:else}
		<!-- Watchlists (list) tab stays mounted to preserve scroll; Lists (tags) mounts on
		     demand. -->
		<div class:hidden={active !== 'watchlists'}>
			{#if loading}
				<div class="text-white/60 py-12 text-center">Loading your watchlist…</div>
			{:else if unauthenticated}
				<div class="py-12 text-center space-y-3">
					<p class="text-white/70">Sign in to see your watchlist.</p>
					<Button href="/login">Sign in</Button>
				</div>
			{:else if error}
				<Notice>{error} <button class="underline" onclick={load}>Try again</button></Notice>
			{:else if isEmpty}
				<div class="py-12 text-center space-y-3">
					<p class="text-white/70">Your watchlist is empty.</p>
					<p class="text-white/50 text-sm">Bookmark anime and media to plan what to watch next.</p>
					<Button href="/search">Browse anime</Button>
				</div>
			{:else if items}
				<WatchlistListTab {items} {nameLanguage} />
			{/if}
		</div>

		{#if active === 'tags'}
			<WatchlistTagsTab onEntriesChanged={load} />
		{/if}

		<!-- Statistics mounts on demand (like the ratings stats tab) so its lazy
		     /ratings/scores fetch only fires when opened. -->
		{#if active === 'stats'}
			{#if loading}
				<div class="text-white/60 py-12 text-center">Loading your watchlist…</div>
			{:else if error}
				<Notice>{error} <button class="underline" onclick={load}>Try again</button></Notice>
			{:else if items}
				<WatchlistStatsTab {items} />
			{/if}
		{/if}
	{/if}
</div>
