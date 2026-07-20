<script lang="ts">
	import WatchlistCard from './WatchlistCard.svelte';
	import { PRIORITY_ACCENT } from '$lib/utils/watchlist';
	import { toPriorityBands, type WatchlistRow } from '$lib/utils/watchlistStats';

	interface Props {
		rows: WatchlistRow[];
		bandDir: 'asc' | 'desc';
	}

	let { rows, bandDir }: Props = $props();

	let bands = $derived(toPriorityBands(rows, bandDir));
</script>

<div class="space-y-8">
	{#each bands as band (band.priority)}
		<section>
			<div class="flex items-center gap-3 mb-3">
				<span class="size-3 rounded-full {PRIORITY_ACCENT[band.priority].dot}"></span>
				<h2 class="text-sm font-semibold {PRIORITY_ACCENT[band.priority].text}">{band.label} priority</h2>
				<span class="text-xs text-white/40">{band.rows.length}</span>
				<div class="flex-grow border-t border-white/10"></div>
			</div>
			<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
				{#each band.rows as row (row.key)}
					<WatchlistCard {row} />
				{/each}
			</div>
		</section>
	{/each}
</div>
