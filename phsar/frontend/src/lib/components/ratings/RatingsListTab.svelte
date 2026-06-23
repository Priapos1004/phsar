<script lang="ts">
	import RatingsFilterBar from './RatingsFilterBar.svelte';
	import RatingsBandGrid from './RatingsBandGrid.svelte';
	import RatingsTable from './RatingsTable.svelte';
	import { ratingsFilter } from '$lib/stores/ratingsFilter';
	import { decimalPlaces } from '$lib/utils/formatString';
	import { filterItems, groupByAnime, sortAnimeRows, type SortKey } from '$lib/utils/ratingStats';
	import type { RatingScoreItem } from '$lib/types/api';

	interface Props {
		items: RatingScoreItem[];
		nameLanguage: 'english' | 'japanese' | 'romaji';
		ratingStep: number;
	}

	let { items, nameLanguage, ratingStep }: Props = $props();

	// Genre universe = union of genres present in the user's ratings (no extra fetch).
	let genreOptions = $derived([...new Set(items.flatMap((i) => i.genres))].sort());
	let scoreDecimals = $derived(Math.max(1, decimalPlaces(ratingStep)));

	let rows = $derived(
		sortAnimeRows(
			groupByAnime(
				filterItems(items, {
					genres: $ratingsFilter.genres,
					genreMode: $ratingsFilter.genreMode,
					statuses: $ratingsFilter.statuses,
					scoreMin: $ratingsFilter.scoreMin,
					scoreMax: $ratingsFilter.scoreMax,
				}),
			),
			$ratingsFilter.sort,
			$ratingsFilter.sortDir,
			nameLanguage,
		),
	);

	// Clicking a table header sets that sort key; clicking the active key flips direction.
	function onSort(key: SortKey) {
		ratingsFilter.update((f) =>
			f.sort === key ? { ...f, sortDir: f.sortDir === 'asc' ? 'desc' : 'asc' } : { ...f, sort: key, sortDir: key === 'title' ? 'asc' : 'desc' },
		);
	}
</script>

<RatingsFilterBar {genreOptions} step={ratingStep} />

{#if rows.length === 0}
	<div class="py-12 text-center text-white/50">No ratings match these filters.</div>
{:else if $ratingsFilter.view === 'table'}
	<RatingsTable {rows} {nameLanguage} {scoreDecimals} sort={$ratingsFilter.sort} sortDir={$ratingsFilter.sortDir} {onSort} />
{:else}
	<RatingsBandGrid {rows} {nameLanguage} {scoreDecimals} />
{/if}
