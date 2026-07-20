<script lang="ts">
	import WatchlistFilterBar from './WatchlistFilterBar.svelte';
	import WatchlistPriorityGrid from './WatchlistPriorityGrid.svelte';
	import WatchlistTable from './WatchlistTable.svelte';
	import { watchlistFilter } from '$lib/stores/watchlistFilter';
	import { filterByTags, sortRows, toAnimeRows, toMediaRows, type WatchlistSortKey } from '$lib/utils/watchlistStats';
	import type { WatchlistItem } from '$lib/types/api';

	interface Props {
		items: WatchlistItem[];
		nameLanguage: 'english' | 'japanese' | 'romaji';
	}

	let { items, nameLanguage }: Props = $props();

	// Filter (union of selected lists) first, then normalize to rows at the chosen grain.
	let filtered = $derived(filterByTags(items, $watchlistFilter.tagUuids));
	let rows = $derived(
		$watchlistFilter.grain === 'anime'
			? toAnimeRows(filtered, nameLanguage)
			: toMediaRows(filtered, nameLanguage),
	);
	let tableRows = $derived(sortRows(rows, $watchlistFilter.sort, $watchlistFilter.sortDir));

	const defaultDir = (key: WatchlistSortKey): 'asc' | 'desc' => (key === 'date' ? 'desc' : 'asc');
	function onSort(key: WatchlistSortKey) {
		watchlistFilter.update((f) =>
			f.sort === key
				? { ...f, sortDir: f.sortDir === 'asc' ? 'desc' : 'asc' }
				: { ...f, sort: key, sortDir: defaultDir(key) },
		);
	}
</script>

<WatchlistFilterBar />

{#if rows.length === 0}
	<div class="py-12 text-center text-white/50">No watchlist entries match these filters.</div>
{:else if $watchlistFilter.view === 'table'}
	<WatchlistTable rows={tableRows} sort={$watchlistFilter.sort} sortDir={$watchlistFilter.sortDir} {onSort} />
{:else}
	<WatchlistPriorityGrid {rows} bandDir={$watchlistFilter.bandDir} />
{/if}
