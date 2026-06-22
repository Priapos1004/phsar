<script lang="ts">
	import { onMount } from 'svelte';
	import { Badge } from '$lib/components/ui/badge';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import * as cls from '$lib/styles/classes';
	import { genreDescriptions, ensureGenresLoaded } from '$lib/stores/genres';

	interface Props {
		/** Genre names to render. Renders nothing when empty. */
		genres: string[];
	}

	let { genres }: Props = $props();

	onMount(ensureGenresLoaded);

	// Not every genre has a seeded description; those render as plain badges.
	function describe(genre: string): string | undefined {
		return $genreDescriptions.get(genre.toLowerCase());
	}
</script>

{#if genres.length}
	<div class="flex flex-wrap gap-1.5">
		{#each genres as genre}
			{@const description = describe(genre)}
			{#if description}
				<Tooltip text={description}>
					<Badge variant="secondary" class={cls.badgeGenre}>{genre}</Badge>
				</Tooltip>
			{:else}
				<Badge variant="secondary" class={cls.badgeGenre}>{genre}</Badge>
			{/if}
		{/each}
	</div>
{/if}
