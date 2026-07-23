<script lang="ts">
	import WatchlistCard from './WatchlistCard.svelte';
	import { PRIORITY_ACCENT } from '$lib/utils/watchlist';
	import { toPriorityBands, type WatchlistGrain, type WatchlistRow } from '$lib/utils/watchlistStats';

	interface Props {
		rows: WatchlistRow[];
		grain: WatchlistGrain; // labels the per-band count ("N anime" vs "N media")
	}

	let { rows, grain }: Props = $props();

	// Bands always run most-urgent first (High on top); priority is now a filter, not an
	// order toggle (see WatchlistFilterBar).
	let bands = $derived(toPriorityBands(rows, 'desc'));
</script>

<div class="space-y-8">
	{#each bands as band (band.priority)}
		<section>
			<!-- "High priority" is one colored mid-size heading (between the ratings score-number and
			     small-word sizes) so the row isn't three font sizes; min-h-8 keeps it at the ratings
			     band-header height. grain is already the display noun ('anime'/'media', invariant plurals). -->
			<div class="flex items-center gap-3 mb-3 min-h-8">
				<span class="size-4 rounded-full {PRIORITY_ACCENT[band.priority].dot}"></span>
				<h2 class="text-lg font-semibold {PRIORITY_ACCENT[band.priority].text}">{band.label} priority</h2>
				<span class="text-xs text-white/40">{band.rows.length} {grain}</span>
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
