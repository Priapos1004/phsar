<script lang="ts">
	// Shared anime/media grain pill for the ratings + watchlist filter bars (was two
	// byte-identical inline copies). Presentational: the caller owns the source of truth
	// via `grain` + `onSelect`. Lives on the DARK page surface (border-fill pills), so it's
	// deliberately NOT the on-card SegmentedControl — same reasoning as the grid/table
	// view pills next to it.
	interface Props {
		grain: 'anime' | 'media';
		onSelect: (grain: 'anime' | 'media') => void;
	}

	let { grain, onSelect }: Props = $props();

	const ON = 'bg-primary/15 text-primary font-medium';
	const OFF = 'text-white/60 hover:text-white';
</script>

<div class="inline-flex rounded-full border border-white/15 overflow-hidden">
	<button class="px-3 py-1.5 text-sm transition-colors {grain === 'anime' ? ON : OFF}" onclick={() => onSelect('anime')}>
		Anime
	</button>
	<button class="px-3 py-1.5 text-sm transition-colors border-l border-white/15 {grain === 'media' ? ON : OFF}" onclick={() => onSelect('media')}>
		Media
	</button>
</div>
