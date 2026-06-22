<script lang="ts">
	import { navigateToSearch } from '$lib/utils/navigation';

	interface Props {
		/** Studio names to render as clickable badges. Renders nothing when empty. */
		studios: string[];
	}

	let { studios }: Props = $props();

	// Clicking a studio opens an anime-view search filtered to that studio, so a
	// user can jump from a title to "other anime from this studio". The empty
	// query + title search_type means the studio filter alone drives the results.
	function searchStudio(studio: string) {
		void navigateToSearch({
			query: '',
			search_type: 'title',
			view_type: 'anime',
			studio_name: [studio],
		});
	}
</script>

{#if studios.length}
	<div class="flex flex-wrap items-center gap-x-2 gap-y-1.5">
		<span class="text-muted-foreground font-medium">Studio</span>
		{#each studios as studio}
			<button
				type="button"
				onclick={() => searchStudio(studio)}
				class="px-2.5 py-0.5 rounded-md font-medium bg-card-foreground/8 text-card-foreground border border-border hover:bg-card-foreground/15 hover:border-primary/50 transition cursor-pointer"
			>
				{studio}
			</button>
		{/each}
	</div>
{/if}
