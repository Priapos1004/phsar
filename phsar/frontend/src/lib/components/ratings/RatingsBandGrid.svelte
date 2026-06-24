<script lang="ts">
	import RatedAnimeCard from './RatedAnimeCard.svelte';
	import { scoreColor } from '$lib/utils/chartColors';
	import { toScoreBands, type AnimeRatingRow } from '$lib/utils/ratingStats';

	interface Props {
		rows: AnimeRatingRow[];
		nameLanguage: 'english' | 'japanese' | 'romaji';
		scoreDecimals: number;
		bandDir: 'asc' | 'desc';
	}

	let { rows, nameLanguage, scoreDecimals, bandDir }: Props = $props();

	// `rows` arrive fixed-sorted (rating desc, title asc). toScoreBands keeps that
	// within-band order; the arrow only flips which band sits on top (10 vs 0).
	let bands = $derived(bandDir === 'asc' ? toScoreBands(rows).reverse() : toScoreBands(rows));
</script>

<div class="space-y-8">
	{#each bands as band (band.band)}
		<section>
			<div class="flex items-baseline gap-3 mb-3">
				<span class="text-2xl font-bold tabular-nums" style="color: {scoreColor(band.band)}">{band.band}</span>
				<h2 class="text-sm font-medium text-white/80">{band.word}</h2>
				<span class="text-xs text-white/40">{band.rows.length} anime</span>
				<div class="flex-grow border-t border-white/10 self-center"></div>
			</div>
			<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
				{#each band.rows as row (row.anime_uuid)}
					<RatedAnimeCard {row} {nameLanguage} {scoreDecimals} />
				{/each}
			</div>
		</section>
	{/each}
</div>
