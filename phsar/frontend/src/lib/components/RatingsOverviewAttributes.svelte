<script lang="ts">
	import EChart from '$lib/components/EChart.svelte';
	import { RATING_ATTRIBUTE_OPTIONS, getRatingAttr } from '$lib/types/api';
	import { CHART_COLORS, CHART_COLOR_PALETTE } from '$lib/utils/chartColors';
	import type { RatingOut } from '$lib/types/api';

	interface Props {
		ratings: RatingOut[];
	}

	let { ratings }: Props = $props();

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

			if (totalSet < 1) continue;

			const visibleEntries = config.options
				.map((opt) => ({ value: opt.value, label: opt.label, count: counts.get(opt.value) ?? 0 }))
				.filter((e) => e.count > 0);

			result.push({ key, label: config.label, visibleEntries, totalSet });
		}

		return result;
	});

	// Maps ordinal attribute values to numeric scores for the radar chart.
	// Only a subset of attributes are meaningful on a quality axis — these five
	// have a clear "low to high" progression suitable for radar visualization.
	const ATTR_SCORE_MAP: Record<string, Record<string, number>> = {
		animation_quality: { bad: 1, normal: 2, good: 3, outstanding: 4 },
		dialogue_quality: { flat: 1, normal: 2, deep: 3 },
		character_depth: { flat: 1, normal: 2, complex: 3 },
		story_quality: { weak: 1, average: 2, good: 3, outstanding: 4 },
		originality: { conventional: 1, unique: 2, experimental: 3 },
	};

	const RADAR_KEYS = Object.keys(ATTR_SCORE_MAP);

	let radarData = $derived.by(() => {
		const avgs: number[] = [];
		const maxes: number[] = [];
		const labels: string[] = [];
		let hasData = false;

		for (const key of RADAR_KEYS) {
			const config = RATING_ATTRIBUTE_OPTIONS[key];
			const scoreMap = ATTR_SCORE_MAP[key];
			const maxVal = Math.max(...Object.values(scoreMap));
			maxes.push(maxVal);
			labels.push(config.label);

			let sum = 0;
			let count = 0;
			for (const r of ratings) {
				const val = getRatingAttr(r, key);
				if (val && scoreMap[val] !== undefined) {
					sum += scoreMap[val];
					count++;
				}
			}

			if (count > 0) {
				avgs.push(sum / count);
				hasData = true;
			} else {
				avgs.push(0);
			}
		}

		return { avgs, maxes, labels, hasData };
	});

	let radarOption = $derived.by(() => ({
		radar: {
			indicator: radarData.labels.map((name: string, i: number) => ({
				name,
				max: radarData.maxes[i],
			})),
			shape: 'polygon' as const,
			axisName: {
				color: 'rgba(0,0,0,0.5)',
				fontSize: 11,
			},
			splitArea: {
				areaStyle: { color: ['rgba(0,0,0,0.02)', 'rgba(0,0,0,0.04)'] },
			},
			splitLine: { lineStyle: { color: 'rgba(0,0,0,0.08)' } },
		},
		series: [
			{
				type: 'radar' as const,
				emphasis: { disabled: true },
				data: [
					{
						name: 'Your Profile',
						value: radarData.avgs,
						areaStyle: { color: CHART_COLORS.chart1, opacity: 0.2 },
						lineStyle: { color: CHART_COLORS.chart1, width: 2 },
						itemStyle: { color: CHART_COLORS.chart1 },
					},
				],
			},
		],
		tooltip: {
			trigger: 'item' as const,
			formatter: (params: unknown) => {
				const p = params as { value: number[] };
				return radarData.labels.map((label: string, i: number) => {
					const val = p.value[i];
					const max = radarData.maxes[i];
					const optionLabels = ATTR_SCORE_MAP[RADAR_KEYS[i]];
					// Find the closest matching label for the average value
					const closest = Object.entries(optionLabels).reduce((best, [key, score]) =>
						Math.abs(score - val) < Math.abs(best[1] - val) ? [key, score] as [string, number] : best,
						Object.entries(optionLabels)[0] as [string, number],
					);
					const displayLabel = RATING_ATTRIBUTE_OPTIONS[RADAR_KEYS[i]].options
						.find(o => o.value === closest[0])?.label ?? closest[0];
					return `${label}: <strong>${displayLabel}</strong> (${val.toFixed(1)}/${max})`;
				}).join('<br/>');
			},
		},
	}));
</script>

{#if distributions.length > 0}
	<div>
		<h3 class="text-sm font-medium text-muted-foreground mb-2">Attribute Summary</h3>

		{#if radarData.hasData}
			<div class="flex justify-center mb-4">
				<EChart option={radarOption} height="224px" />
			</div>
		{/if}

		<div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-3">
			{#each distributions as dist}
				<div class="space-y-1.5">
					<div class="flex items-center justify-between">
						<span class="text-sm font-medium text-card-foreground">{dist.label}</span>
						<span class="text-sm text-muted-foreground">{dist.totalSet} rated</span>
					</div>
					<div class="flex h-2.5 rounded-full overflow-hidden bg-muted">
						{#each dist.visibleEntries as entry, i}
							{@const widthPercent = (entry.count / dist.totalSet) * 100}
							<div
								class="h-full"
								style="width: {widthPercent}%; background: {CHART_COLOR_PALETTE[i % CHART_COLOR_PALETTE.length]}"
								title="{entry.label}: {entry.count}"
							></div>
						{/each}
					</div>
					<div class="flex flex-wrap gap-1">
						{#each dist.visibleEntries as entry, i}
							<span class="text-xs text-muted-foreground">
								<span
									class="inline-block w-2 h-2 rounded-full mr-0.5"
									style="background: {CHART_COLOR_PALETTE[i % CHART_COLOR_PALETTE.length]}"
								></span>
								{entry.label} ({entry.count})
							</span>
						{/each}
					</div>
				</div>
			{/each}
		</div>
	</div>
{/if}
