<script lang="ts">
	import { searchByStudio } from '$lib/utils/navigation';

	interface Props {
		/** Studio names to render as clickable badges. Renders nothing when empty. */
		studios: string[];
	}

	let { studios }: Props = $props();
</script>

{#if studios.length}
	<div class="flex flex-wrap items-center gap-x-2 gap-y-1.5">
		<span class="text-muted-foreground font-medium">Studio</span>
		{#each studios as studio}
			<button
				type="button"
				onclick={() => searchByStudio(studio)}
				class="px-2.5 py-0.5 rounded-md font-medium bg-card-foreground/8 text-card-foreground border border-border hover:bg-card-foreground/15 hover:border-primary/50 transition cursor-pointer"
			>
				{studio}
			</button>
		{/each}
	</div>
{/if}
