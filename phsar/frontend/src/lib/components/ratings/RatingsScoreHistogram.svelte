<script lang="ts">
	import EChart from '$lib/components/EChart.svelte';
	import { scoreColor } from '$lib/utils/chartColors';
	import { scoreHistogram, SCORE_HISTOGRAM_WIDTH } from '$lib/utils/ratingStats';
	import { chartTooltipStyle } from '$lib/utils/chartTheme';
	import { formatDecimalDigits } from '$lib/utils/formatString';
	import type { RatingScoreItem } from '$lib/types/api';

	const HALF = SCORE_HISTOGRAM_WIDTH / 2; // each bar spans center ± half-width

	interface Props {
		items: RatingScoreItem[];
	}

	let { items }: Props = $props();

	let buckets = $derived(scoreHistogram(items));

	let option = $derived({
		grid: { left: 36, right: 12, top: 16, bottom: 28 },
		tooltip: {
			...chartTooltipStyle,
			trigger: 'axis' as const,
			// Show the bucket's score range (bars cover a 0.5-wide band, not a point) and
			// break the count into main vs side titles instead of a bare number.
			formatter: (params: unknown) => {
				const idx = (params as { dataIndex: number }[])[0]?.dataIndex ?? 0;
				const b = buckets[idx];
				// Clamp to the 0–10 scale so the edge bars don't read -0.25 / 10.25.
				const lo = Math.max(0, b.center - HALF);
				const hi = Math.min(10, b.center + HALF);
				const range = `${formatDecimalDigits(lo, 2)}–${formatDecimalDigits(hi, 2)}`;
				const parts: string[] = [];
				if (b.main) parts.push(`${b.main} main`);
				if (b.side) parts.push(`${b.side} side`);
				const sub = parts.length ? `<br/>${parts.join(' · ')}` : '';
				return `${range}<br/>${b.count} total${sub}`;
			},
		},
		xAxis: {
			type: 'category' as const,
			// 0.5-wide buckets → 1-decimal labels.
			data: buckets.map((b) => formatDecimalDigits(b.center, 1)),
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
