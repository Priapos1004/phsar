<script lang="ts">
	import { RATING_ATTRIBUTE_OPTIONS } from '$lib/types/api';
	import { QUALITY_COLORS } from '$lib/utils/chartColors';
	import { tally } from '$lib/utils/ratingAttributes';
	import type { RatingOut, RatingScoreItem } from '$lib/types/api';

	interface Props {
		// Accepts either shape — only the 11 attribute keys are read (via getRatingAttr),
		// which both RatingOut and the /ratings page's RatingScoreItem carry.
		ratings: RatingOut[] | RatingScoreItem[];
	}

	let { ratings }: Props = $props();

	interface AttrDistribution {
		key: string;
		label: string;
		visibleEntries: { value: string; label: string; count: number; color: string }[];
		totalSet: number;
	}

	let distributions = $derived.by<AttrDistribution[]>(() => {
		const result: AttrDistribution[] = [];

		for (const [key, config] of Object.entries(RATING_ATTRIBUTE_OPTIONS)) {
			const { counts, n: totalSet } = tally(ratings, key);

			// A value's colour is its place in the full option list, never its place among the
			// values present — counted that way, "Rare" would change colour depending on
			// whether None or Heavy is rated. Keyed to the list, each value keeps one colour,
			// and the same step (the low end of every scale, say) shares it across attributes.
			const visibleEntries = config.options
				.map((opt, slot) => ({
					value: opt.value,
					label: opt.label,
					count: counts.get(opt.value) ?? 0,
					color: QUALITY_COLORS[slot % QUALITY_COLORS.length],
				}))
				.filter((e) => e.count > 0);

			result.push({ key, label: config.label, visibleEntries, totalSet });
		}

		return result;
	});
</script>

<div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-3">
	{#each distributions as dist}
		<div class="space-y-1.5 {dist.totalSet < 1 ? 'opacity-40' : ''}">
			<div class="flex items-center justify-between">
				<span class="text-sm font-medium text-card-foreground">{dist.label}</span>
				<span class="text-sm text-muted-foreground">
					{dist.totalSet > 0 ? `${dist.totalSet} rated` : 'No data'}
				</span>
			</div>
			<!-- gap-0.5: the 2px between segments, so neighbours stay apart without colour alone. -->
			<div class="flex gap-0.5 h-2.5 rounded-full overflow-hidden bg-muted">
				{#each dist.visibleEntries as entry}
					{@const widthPercent = (entry.count / dist.totalSet) * 100}
					<div
						class="h-full"
						style="width: {widthPercent}%; background: {entry.color}"
					></div>
				{/each}
			</div>
			{#if dist.visibleEntries.length > 0}
				<div class="flex flex-wrap gap-1">
					{#each dist.visibleEntries as entry}
						<span class="text-xs text-muted-foreground">
							<span
								class="inline-block w-2 h-2 rounded-full mr-0.5"
								style="background: {entry.color}"
							></span>
							{entry.label} ({entry.count})
						</span>
					{/each}
				</div>
			{/if}
		</div>
	{/each}
</div>
