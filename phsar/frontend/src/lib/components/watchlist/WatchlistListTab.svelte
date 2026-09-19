<script lang="ts">
	import WatchlistFilterBar from './WatchlistFilterBar.svelte';
	import WatchlistPriorityGrid from './WatchlistPriorityGrid.svelte';
	import WatchlistTable from './WatchlistTable.svelte';
	import { watchlistFilter } from '$lib/stores/watchlistFilter';
	import { buildWatchlistView, type WatchlistSortKey } from '$lib/utils/watchlistStats';
	import type { WatchlistItem } from '$lib/types/api';

	interface Props {
		items: WatchlistItem[];
		nameLanguage: 'english' | 'japanese' | 'romaji';
	}

	let { items, nameLanguage }: Props = $props();

	// One clock for the whole page, captured at mount: the verdict and the media-grain
	// narrowing must agree on what "next season" is, and two `new Date()` calls in one
	// render pass could straddle a boundary. A season boundary crossed mid-session
	// therefore waits for the next load, which is the right trade against a timer nobody
	// would ever see fire.
	const now = new Date();

	let view = $derived(buildWatchlistView(items, $watchlistFilter, nameLanguage, now));

	// date + note lead with the "most" (newest / most-noted) on first click; the rest ascend.
	const defaultDir = (key: WatchlistSortKey): 'asc' | 'desc' => (key === 'date' || key === 'note' ? 'desc' : 'asc');
	function onSort(key: WatchlistSortKey) {
		watchlistFilter.update((f) =>
			f.sort === key
				? { ...f, sortDir: f.sortDir === 'asc' ? 'desc' : 'asc' }
				: { ...f, sort: key, sortDir: defaultDir(key) },
		);
	}
</script>

<WatchlistFilterBar />

{#if view.rows.length === 0}
	<div class="py-12 text-center text-white/50">No watchlist entries match these filters.</div>
{:else if $watchlistFilter.view === 'table'}
	<WatchlistTable rows={view.tableRows} sort={$watchlistFilter.sort} sortDir={$watchlistFilter.sortDir} {onSort} />
{:else}
	<WatchlistPriorityGrid rows={view.rows} grain={$watchlistFilter.grain} />
{/if}
