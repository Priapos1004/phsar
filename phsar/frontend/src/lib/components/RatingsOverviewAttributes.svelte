<script lang="ts">
	import { ChevronDown, ChevronUp } from 'lucide-svelte';
	import type { RatingOut } from '$lib/types/api';
	import AttributeRadar from '$lib/components/AttributeRadar.svelte';
	import AttributeBadges from '$lib/components/AttributeBadges.svelte';
	import AttributeDetailBars from '$lib/components/AttributeDetailBars.svelte';

	interface Props {
		ratings: RatingOut[];
	}

	let { ratings }: Props = $props();

	let detailsExpanded = $state(false);
</script>

<!-- Parent (RatingsOverview) gates on hasAttributes — this component only mounts when attributes exist -->
<div>
	<h3 class="text-sm font-medium text-muted-foreground mb-2">Attribute Summary</h3>

	<div class="flex flex-col md:flex-row md:items-start gap-4 md:gap-6">
		<div class="md:w-1/2 flex justify-center">
			<AttributeRadar {ratings} />
		</div>
		<div class="md:w-1/2 flex justify-center items-center">
			<AttributeBadges {ratings} />
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
