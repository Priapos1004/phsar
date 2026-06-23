<script lang="ts">
	import { goto } from '$app/navigation';
	import EChart from '$lib/components/EChart.svelte';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import { getThemedChartColorPalette, STATUS_COLORS } from '$lib/utils/chartColors';
	import { alignmentPoints, weightedLinearFit, spearman } from '$lib/utils/ratingStats';
	import { chartTooltipStyle } from '$lib/utils/chartTheme';
	import { buildDetailHref } from '$lib/utils/navigation';
	import { formatDecimalDigits, resolveTitle } from '$lib/utils/formatString';
	import { userSettings } from '$lib/stores/userSettings';
	import type { RatingScoreItem } from '$lib/types/api';

	interface Props {
		items: RatingScoreItem[];
	}

	let { items }: Props = $props();

	const MIN_POINTS = 5;
	// Above the trend line = you rate it higher than your own MAL pattern predicts.
	// Reuse the shared sentiment pair (completed=green=over, dropped=rose=under).
	const OVER_COLOR = STATUS_COLORS.completed;
	const UNDER_COLOR = STATUS_COLORS.dropped;

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');

	let points = $derived(alignmentPoints(items));
	let fit = $derived(weightedLinearFit(points));
	let rank = $derived(spearman(points.map((p) => ({ x: p.x, y: p.y }))));

	// Click a point → its media detail page, with a back link to the Statistics tab.
	function handlePointClick(params: unknown) {
		const p = params as { seriesType: string; dataIndex: number };
		if (p.seriesType !== 'scatter') return;
		const pt = points[p.dataIndex];
		if (pt) goto(buildDetailHref('media', pt.mediaUuid, { from: 'ratings-stats' }));
	}

	// Marker area scales with the confidence weight (log10(scored_by+1)); kept small so
	// 100+ overlapping titles read as graduated density, not one merged blob. Low opacity
	// does the rest. (Clamp so a 5-vote and a million-vote title both stay reasonable.)
	function markerSize(w: number): number {
		return 4 + Math.min(7, w * 1.2);
	}

	// Single pass for the MAL-score span — feeds both the fit line and the x-axis zoom.
	let xExtent = $derived.by(() => {
		let lo = Infinity;
		let hi = -Infinity;
		for (const p of points) {
			if (p.x < lo) lo = p.x;
			if (p.x > hi) hi = p.x;
		}
		return { lo, hi };
	});

	// MAL scores for watched anime almost never dip below ~6, so a 0–10 x-axis wastes
	// most of the width. Zoom to the data (padded, clamped to the 0–10 scale). y stays
	// 0–10 — it's the user's own scale, and seeing how much of it they use is the point.
	let xBounds = $derived(
		points.length
			? { min: Math.max(0, Math.floor(xExtent.lo - 0.5)), max: Math.min(10, Math.ceil(xExtent.hi + 0.5)) }
			: { min: 0, max: 10 },
	);

	let fitLine = $derived.by(() => {
		if (!fit.ok) return [] as [number, number][];
		const { lo, hi } = xExtent;
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
				const p = params as { seriesType: string; dataIndex: number };
				if (p.seriesType !== 'scatter') return '';
				const pt = points[p.dataIndex];
				if (!pt) return '';
				const title = resolveTitle(pt.title, pt.nameEng, pt.nameJap, nameLanguage);
				return `<strong>${title}</strong><br/>MAL ${formatDecimalDigits(pt.x, 2)} · You ${formatDecimalDigits(pt.y, 1)}`;
			},
		},
		xAxis: {
			type: 'value' as const,
			name: 'MAL',
			nameLocation: 'middle' as const,
			nameGap: 22,
			min: xBounds.min,
			max: xBounds.max,
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
				// Per-point color = above/below the trend (falls back to palette before a fit).
				itemStyle: { opacity: 0.4 },
				cursor: 'pointer', // points link to the media detail page
				data: points.map((p) => ({
					value: [p.x, p.y],
					// Above the fit line → over-rated vs your trend (caller already knows fit.ok).
					itemStyle: { color: fit.ok ? (p.y - (fit.slope * p.x + fit.intercept) >= 0 ? OVER_COLOR : UNDER_COLOR) : palette[0] },
				})),
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
	<EChart {option} height="280px" onClick={handlePointClick} />
	<div class="mt-2 space-y-1 text-sm">
		{#if fit.ok}
			<p class="text-card-foreground flex flex-wrap items-center gap-x-1.5">
				<span class="font-medium">your ≈ {formatDecimalDigits(fit.slope, 2)}·mal {readout?.above}</span>
				<span class="text-muted-foreground">·</span>
				<Tooltip text="R² — how much of your scores the MAL score explains. 0 = no link; 1 = your score is fully predictable from MAL.">
					<span class="text-muted-foreground">R² {formatDecimalDigits(fit.r2, 2)}</span>
				</Tooltip>
				{#if rank.ok}
					<span class="text-muted-foreground">·</span>
					<Tooltip text="Spearman ρ — how closely your ranking order matches MAL's. −1 = exact opposite; 0 = unrelated; 1 = identical order.">
						<span class="text-muted-foreground">Spearman ρ {formatDecimalDigits(rank.rho, 2)}</span>
					</Tooltip>
				{/if}
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
