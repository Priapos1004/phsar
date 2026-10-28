<script lang="ts">
	import { ChevronDown, ChevronUp } from 'lucide-svelte';
	import type { AnimeMediaItem, RatingOut } from '$lib/types/api';
	import AttributeRadar from '$lib/components/AttributeRadar.svelte';
	import AttributeBadges from '$lib/components/AttributeBadges.svelte';
	import AttributeDetailBars from '$lib/components/AttributeDetailBars.svelte';

	interface Props {
		ratings: RatingOut[];
		/** Only the pills need it — the radar and the detail bars treat every rating
		 *  alike. Required, not optional: without it every pill degrades to reading
		 *  every rating in fetch order. */
		media: AnimeMediaItem[];
	}

	let { ratings, media }: Props = $props();

	let detailsExpanded = $state(false);
</script>

<!-- Parent (RatingsOverview) gates on hasAttributes — this only mounts when attributes
     exist, and the radar always draws, so the pills never appear on their own. -->
<div>
	<h3 class="text-sm font-medium text-muted-foreground mb-2">Attribute Summary</h3>

	<!-- Side by side from lg: as halves of a 768 card (~314px) the radar's labels and the
	     pill orbit both overflow. -->
	<div class="flex flex-col lg:flex-row lg:items-start gap-4 lg:gap-6">
		<div class="lg:w-1/2 flex justify-center">
			<AttributeRadar {ratings} />
		</div>
		<div class="lg:w-1/2 flex justify-center items-center">
			<AttributeBadges {ratings} {media} />
		</div>
	</div>

	<button
		class="flex items-center gap-1.5 text-primary text-sm mt-4 group"
		onclick={() => (detailsExpanded = !detailsExpanded)}
	>
		{#if detailsExpanded}
			<ChevronUp class="size-4" />
			<span class="group-hover:underline">Hide attribute details</span>
		{:else}
			<ChevronDown class="size-4" />
			<span class="group-hover:underline">Show attribute details</span>
		{/if}
	</button>

	{#if detailsExpanded}
		<div class="mt-3">
			<AttributeDetailBars {ratings} />
		</div>
	{/if}
</div>
