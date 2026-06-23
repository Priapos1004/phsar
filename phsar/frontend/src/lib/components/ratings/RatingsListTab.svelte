<script lang="ts">
	import RatingsFilterBar from './RatingsFilterBar.svelte';
	import RatingsBandGrid from './RatingsBandGrid.svelte';
	import RatingsTable from './RatingsTable.svelte';
	import { ratingsFilter } from '$lib/stores/ratingsFilter';
	import { decimalPlaces } from '$lib/utils/formatString';
	import { filterItems, groupByAnime, sortAnimeRows, seasonLabel, type SortKey } from '$lib/utils/ratingStats';
	import type { RatingScoreItem } from '$lib/types/api';

	interface Props {
		items: RatingScoreItem[];
		nameLanguage: 'english' | 'japanese' | 'romaji';
		ratingStep: number;
	}

	let { items, nameLanguage, ratingStep }: Props = $props();

	// Filter universes = the values present in the user's ratings (no extra fetch).
	let genreOptions = $derived([...new Set(items.flatMap((i) => i.genres))].sort());
	let ageOptions = $derived(
		[...new Set(items.map((i) => i.age_rating_numeric).filter((a): a is number => a != null))].sort((a, b) => a - b),
	);
	const SEASON_ORDER: Record<string, number> = { Winter: 0, Spring: 1, Summer: 2, Fall: 3 };
	let seasonOptions = $derived.by(() => {
		const seen = new Map<string, { year: number; idx: number }>();
		for (const it of items) {
			const label = seasonLabel(it);
			if (label && it.anime_season_year != null && !seen.has(label)) {
				seen.set(label, { year: it.anime_season_year, idx: SEASON_ORDER[it.anime_season_name ?? ''] ?? 0 });
			}
		}
		// Newest first (year desc, then later-in-year season first).
		return [...seen.entries()].sort((a, b) => b[1].year - a[1].year || b[1].idx - a[1].idx).map(([label]) => label);
	});

	let scoreDecimals = $derived(Math.max(1, decimalPlaces(ratingStep)));

	let grouped = $derived(
		groupByAnime(
			filterItems(items, {
				genres: $ratingsFilter.genres,
				genreMode: $ratingsFilter.genreMode,
				ageRatings: $ratingsFilter.ageRatings,
				seasons: $ratingsFilter.seasons,
			}),
		),
	);
	// The table sorts by the active column; the grid's within-band order is fixed
	// (rating desc, then title asc — the stable tiebreak in sortAnimeRows), and the
	// band-direction arrow only flips the section order (see RatingsBandGrid). Only the
	// visible view's ordering is derived.
	let rows = $derived(
		$ratingsFilter.view === 'table'
			? sortAnimeRows(grouped, $ratingsFilter.sort, $ratingsFilter.sortDir, nameLanguage)
			: sortAnimeRows(grouped, 'score', 'desc', nameLanguage),
	);

	const defaultDir = (key: SortKey): 'asc' | 'desc' => (key === 'title' ? 'asc' : 'desc');
	function onSort(key: SortKey) {
		ratingsFilter.update((f) =>
			f.sort === key ? { ...f, sortDir: f.sortDir === 'asc' ? 'desc' : 'asc' } : { ...f, sort: key, sortDir: defaultDir(key) },
		);
	}
</script>

<RatingsFilterBar {genreOptions} {ageOptions} {seasonOptions} />

{#if grouped.length === 0}
	<div class="py-12 text-center text-white/50">No ratings match these filters.</div>
{:else if $ratingsFilter.view === 'table'}
	<RatingsTable {rows} {nameLanguage} {scoreDecimals} sort={$ratingsFilter.sort} sortDir={$ratingsFilter.sortDir} {onSort} />
{:else}
	<RatingsBandGrid {rows} {nameLanguage} {scoreDecimals} bandDir={$ratingsFilter.bandDir} />
{/if}
