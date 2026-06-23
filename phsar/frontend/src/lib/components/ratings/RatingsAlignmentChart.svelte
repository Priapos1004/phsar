<script lang="ts">
	import EChart from '$lib/components/EChart.svelte';
	import { getThemedChartColorPalette } from '$lib/utils/chartColors';
	import { alignmentPoints, weightedLinearFit, spearman } from '$lib/utils/ratingStats';
	import { chartTooltipStyle } from '$lib/utils/chartTheme';
	import { formatDecimalDigits } from '$lib/utils/formatString';
	import type { RatingScoreItem } from '$lib/types/api';

	interface Props {
		items: RatingScoreItem[];
	}

	let { items }: Props = $props();

	const MIN_POINTS = 5;

	let points = $derived(alignmentPoints(items));
	let fit = $derived(weightedLinearFit(points));
	let rank = $derived(spearman(points.map((p) => ({ x: p.x, y: p.y }))));

	// Marker area scales with the confidence weight (log10(scored_by+1)); clamp so a
	// 5-vote title stays visible and a million-vote title doesn't dominate the canvas.
	function markerSize(w: number): number {
		return 6 + Math.min(22, w * 4);
	}

	let fitLine = $derived.by(() => {
		if (!fit.ok) return [] as [number, number][];
		// Draw across the observed MAL-score span.
		const xs = points.map((p) => p.x);
		const lo = Math.min(...xs);
		const hi = Math.max(...xs);
		return [
			[lo, fit.slope * lo + fit.intercept],
			[hi, fit.slope * hi + fit.intercept],
		] as [number, number][];
	});

	let palette = $derived(getThemedChartColorPalette());

	let option = $derived({
		grid: { left: 40, right: 16, top: 16, bottom: 32 },
		tooltip: {
			...chartTooltipStyle,
			trigger: 'item' as const,
			formatter: (params: unknown) => {
				const p = params as { data: number[]; seriesType: string };
				return p.seriesType === 'scatter'
					? `MAL ${formatDecimalDigits(p.data[0], 2)} · You ${formatDecimalDigits(p.data[1], 1)}`
					: '';
			},
		},
		xAxis: {
			type: 'value' as const,
			name: 'MAL',
			nameLocation: 'middle' as const,
			nameGap: 22,
			min: 0,
			max: 10,
			axisLabel: { color: 'rgba(0,0,0,0.6)', fontSize: 11 },
			splitLine: { lineStyle: { color: 'rgba(0,0,0,0.06)' } },
		},
		yAxis: {
			type: 'value' as const,
			name: 'You',
			min: 0,
			max: 10,
			axisLabel: { color: 'rgba(0,0,0,0.6)', fontSize: 11 },
			splitLine: { lineStyle: { color: 'rgba(0,0,0,0.06)' } },
		},
		series: [
			{
				type: 'scatter' as const,
				emphasis: { disabled: true },
				symbolSize: (_data: unknown, params: { dataIndex: number }) => markerSize(points[params.dataIndex]?.w ?? 0),
				itemStyle: { color: palette[0], opacity: 0.55 },
				data: points.map((p) => [p.x, p.y]),
				z: 2,
			},
			...(fit.ok
				? [
						{
							type: 'line' as const,
							emphasis: { disabled: true },
							showSymbol: false,
							lineStyle: { color: palette[3], width: 2 },
							data: fitLine,
							z: 3,
						},
					]
				: []),
		],
	});

	let readout = $derived.by(() => {
		if (points.length < MIN_POINTS || !fit.ok) return null;
		const above = fit.intercept >= 0 ? `+${formatDecimalDigits(fit.intercept, 2)}` : formatDecimalDigits(fit.intercept, 2);
		const agreement =
			rank.ok && rank.rho >= 0.7
				? 'strong agreement on ordering'
				: rank.ok && rank.rho >= 0.4
					? 'moderate agreement on ordering'
					: rank.ok
						? 'weak agreement on ordering'
						: '';
		return { above, agreement };
	});
</script>

{#if points.length < MIN_POINTS}
	<p class="text-sm text-muted-foreground">
		Rate at least {MIN_POINTS} titles that have a MAL score to see how your taste aligns.
	</p>
{:else}
	<EChart {option} height="280px" />
	<div class="mt-2 space-y-1 text-sm">
		{#if fit.ok}
			<p class="text-card-foreground">
				<span class="font-medium">your ≈ {formatDecimalDigits(fit.slope, 2)}·mal {readout?.above}</span>
				<span class="text-muted-foreground"> · R² {formatDecimalDigits(fit.r2, 2)}</span>
				{#if rank.ok}<span class="text-muted-foreground"> · Spearman ρ {formatDecimalDigits(rank.rho, 2)}</span>{/if}
			</p>
			{#if readout}
				<p class="text-muted-foreground">
					{#if fit.slope > 1.05}You spread scores wider than MAL{:else if fit.slope < 0.95}You compress scores tighter than MAL{:else}You track the MAL scale closely{/if}{#if readout.agreement}, with {readout.agreement}{/if}.
				</p>
			{/if}
		{:else}
			<p class="text-muted-foreground">Not enough score variation to fit a line yet.</p>
		{/if}
	</div>
{/if}
