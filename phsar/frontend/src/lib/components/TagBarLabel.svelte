<script lang="ts">
	// Shared genre/studio bar-label used by the ratings tag chart + the watchlist stats
	// bars (was a byte-identical block in both). Studio → click-to-search link; genre →
	// its description tooltip (falls back to a plain label when none). Presentational:
	// the parent is responsible for calling `ensureGenresLoaded()` so descriptions exist.
	import Tooltip from '$lib/components/Tooltip.svelte';
	import { genreDescriptions } from '$lib/stores/genres';
	import { searchByStudio } from '$lib/utils/navigation';

	interface Props {
		name: string;
		kind: 'genre' | 'studio';
	}

	let { name, kind }: Props = $props();
</script>

{#if kind === 'studio'}
	<button
		onclick={() => searchByStudio(name)}
		class="truncate min-w-0 text-card-foreground hover:text-primary hover:underline transition-colors"
		title={name}
	>{name}</button>
{:else if $genreDescriptions.get(name.toLowerCase())}
	<Tooltip text={$genreDescriptions.get(name.toLowerCase()) ?? ''} class="truncate min-w-0 text-card-foreground">{name}</Tooltip>
{:else}
	<span class="truncate min-w-0 text-card-foreground" title={name}>{name}</span>
{/if}
