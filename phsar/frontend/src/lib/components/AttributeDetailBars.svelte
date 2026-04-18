<script lang="ts">
	import { RATING_ATTRIBUTE_OPTIONS, getRatingAttr } from '$lib/types/api';
	import { getThemedChartColorPalette } from '$lib/utils/chartColors';
	import type { RatingOut } from '$lib/types/api';

	interface Props {
		ratings: RatingOut[];
	}

	let { ratings }: Props = $props();

	let palette = $derived(getThemedChartColorPalette());

	interface AttrDistribution {
		key: string;
		label: string;
		visibleEntries: { value: string; label: string; count: number }[];
		totalSet: number;
	}

	let distributions = $derived.by<AttrDistribution[]>(() => {
		const result: AttrDistribution[] = [];

		for (const [key, config] of Object.entries(RATING_ATTRIBUTE_OPTIONS)) {
			const counts = new Map<string, number>();
			let totalSet = 0;

			for (const r of ratings) {
				const val = getRatingAttr(r, key);
				if (val) {
					counts.set(val, (counts.get(val) ?? 0) + 1);
					totalSet++;
				}
			}

			const visibleEntries = config.options
				.map((opt) => ({ value: opt.value, label: opt.label, count: counts.get(opt.value) ?? 0 }))
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
			<div class="flex h-2.5 rounded-full overflow-hidden bg-muted">
				{#each dist.visibleEntries as entry, i}
					{@const widthPercent = (entry.count / dist.totalSet) * 100}
					<div
						class="h-full"
						style="width: {widthPercent}%; background: {palette[i % palette.length]}"
						title="{entry.label}: {entry.count}"
					></div>
				{/each}
			</div>
			{#if dist.visibleEntries.length > 0}
				<div class="flex flex-wrap gap-1">
					{#each dist.visibleEntries as entry, i}
						<span class="text-xs text-muted-foreground">
							<span
								class="inline-block w-2 h-2 rounded-full mr-0.5"
								style="background: {palette[i % palette.length]}"
							></span>
							{entry.label} ({entry.count})
						</span>
					{/each}
				</div>
			{/if}
		</div>
	{/each}
</div>
