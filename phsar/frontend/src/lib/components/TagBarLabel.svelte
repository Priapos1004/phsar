<script lang="ts">
	// Shared bar-label used by the ratings breakdown chart + the watchlist stats bars.
	// Purely presentational — every destination is caller-owned via `onClick`, so this
	// component knows nothing about search, the ratings filter, or which dimensions
	// have a drill-down.
	//
	// `describeGenre` is the one non-behavioural knob: the label text is a genre name, so
	// look its description up for a hover tooltip. It's a separate prop rather than a
	// `kind` union because "is this clickable" and "does this have a description" are
	// independent questions — conflating them forced non-genre dimensions to claim
	// `kind: 'genre'` just to avoid the studio branch, which would have had a season or
	// age label silently pick up a same-named genre's description.
	//
	// The parent is responsible for calling `ensureGenresLoaded()` so descriptions exist.
	import Tooltip from '$lib/components/Tooltip.svelte';
	import { genreDescriptions } from '$lib/stores/genres';

	interface Props {
		name: string;
		/** Look up `name` in the genre-description store for a hover tooltip. */
		describeGenre?: boolean;
		/** Makes the label a button running this. */
		onClick?: () => void;
	}

	let { name, describeGenre = false, onClick }: Props = $props();

	const description = $derived(describeGenre ? $genreDescriptions.get(name.toLowerCase()) : undefined);
</script>

{#if onClick}
	<button
		onclick={onClick}
		class="truncate min-w-0 text-card-foreground hover:text-primary hover:underline transition-colors"
		title={name}
	>{name}</button>
{:else if description}
	<Tooltip text={description} class="truncate min-w-0 text-card-foreground">{name}</Tooltip>
{:else}
	<span class="truncate min-w-0 text-card-foreground" title={name}>{name}</span>
{/if}
