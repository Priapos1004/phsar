<script lang="ts">
	import EChart from '$lib/components/EChart.svelte';
	import { scoreColor } from '$lib/utils/chartColors';
	import { scoreHistogram } from '$lib/utils/ratingStats';
	import { formatDecimalDigits } from '$lib/utils/formatString';
	import type { RatingScoreItem } from '$lib/types/api';

	interface Props {
		items: RatingScoreItem[];
		step: number;
	}

	let { items, step }: Props = $props();

	let buckets = $derived(scoreHistogram(items, step));

	let option = $derived({
		grid: { left: 36, right: 12, top: 16, bottom: 28 },
		tooltip: { trigger: 'axis' as const },
		xAxis: {
			type: 'category' as const,
			data: buckets.map((b) => formatDecimalDigits(b.center, step < 1 ? 1 : 0)),
			axisLabel: { color: 'rgba(0,0,0,0.7)', fontSize: 11 },
			axisLine: { lineStyle: { color: 'rgba(0,0,0,0.15)' } },
		},
		yAxis: {
			type: 'value' as const,
			minInterval: 1,
			axisLabel: { color: 'rgba(0,0,0,0.6)', fontSize: 11 },
			splitLine: { lineStyle: { color: 'rgba(0,0,0,0.08)' } },
		},
		series: [
			{
				type: 'bar' as const,
				emphasis: { disabled: true },
				data: buckets.map((b) => ({ value: b.count, itemStyle: { color: scoreColor(b.center), borderRadius: [3, 3, 0, 0] } })),
			},
		],
	});
</script>

{#if buckets.length}
	<EChart {option} height="220px" />
{:else}
	<p class="text-sm text-muted-foreground">No scores to chart yet.</p>
{/if}
