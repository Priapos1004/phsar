<script lang="ts">
	import { onMount } from 'svelte';
	import { ArrowDown, ArrowUp } from 'lucide-svelte';
	import EChart from '$lib/components/EChart.svelte';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import * as Select from '$lib/components/ui/select';
	import { scoreColor, getThemedChartColorPalette } from '$lib/utils/chartColors';
	import { tagMetrics, type TagDim, type TagMetric } from '$lib/utils/ratingStats';
	import { chartTooltipStyle } from '$lib/utils/chartTheme';
	import { searchByStudio } from '$lib/utils/navigation';
	import { formatDecimalDigits, formatDuration, escapeHtml } from '$lib/utils/formatString';
	import { genreDescriptions, ensureGenresLoaded } from '$lib/stores/genres';
	import type { RatingScoreItem } from '$lib/types/api';

	interface Props {
		items: RatingScoreItem[];
	}

	let { items }: Props = $props();

	const TOP_N = 12;
	// Row geometry shared by the HTML label column and the chart so they line up: the
	// chart's plot area is exactly ROW·n tall with TOP_PAD above and AXIS_PAD below (the
	// latter is the room the x-axis ticks need). The HTML label column uses the same
	// paddings so each label row's center matches its bar's band center. NOTE: AXIS_PAD
	// is a pixel estimate of the x-axis label band at the current 11px font — at extreme
	// browser zoom / font scaling labels and bars can drift a few px (no overlap; `truncate`
	// keeps each label one line). A fully zoom-robust fix would use ECharts' own axis
	// labels via yAxis.triggerEvent instead of this parallel DOM column.
	const ROW = 28;
	const TOP_PAD = 8;
	const AXIS_PAD = 28;

	// The bar length is the chosen metric; for the avg metric the bar COLOR is the
	// score color (reinforces the length). For other metrics that would just be a
	// patternless rainbow, so we use one themed color.
	type MetricKey = 'avg' | 'count' | 'watch' | 'weighted';
	const METRICS: { key: MetricKey; label: string; value: (t: TagMetric) => number; axisMax?: number }[] = [
		{ key: 'avg', label: 'Avg rating', value: (t) => t.avg, axisMax: 10 },
		{ key: 'count', label: 'Rated anime', value: (t) => t.count },
		{ key: 'watch', label: 'Watch time', value: (t) => t.watchSeconds },
		{ key: 'weighted', label: 'Weighted score', value: (t) => t.weighted, axisMax: 1 },
	];

	let dim = $state<TagDim>('genres');
	let sortKey = $state<MetricKey>('avg');
	let dir = $state<'asc' | 'desc'>('desc');

	onMount(ensureGenresLoaded); // genre descriptions for the y-axis label tooltips

	let palette = $derived(getThemedChartColorPalette());
	let activeMetric = $derived(METRICS.find((m) => m.key === sortKey) ?? METRICS[0]);

	let allMetrics = $derived(tagMetrics(items, dim));
	// X-axis max is fixed (avg → 10, weighted → 1) or the GLOBAL max of the metric over
	// every tag — not just the shown 12 — so the scale doesn't recalibrate when the arrow
	// flips between the top 12 and the bottom 12.
	let axisMax = $derived.by(() => {
		if (activeMetric.axisMax != null) return activeMetric.axisMax;
		const m = allMetrics.reduce((mx, t) => Math.max(mx, activeMetric.value(t)), 0);
		return m || undefined; // 0 (no data) → let ECharts auto-scale
	});

	// desc = the 12 HIGHEST by the metric; asc = the 12 LOWEST — so flipping the arrow
	// changes WHICH tags appear, not just their order. `rows` is the chart's bottom-up
	// data (last element renders at the top), so the "best for the chosen direction"
	// lands on top in both cases.
	let rows = $derived.by(() => {
		const sorted = [...allMetrics].sort((a, b) => activeMetric.value(b) - activeMetric.value(a));
		return dir === 'desc' ? sorted.slice(0, TOP_N).reverse() : sorted.slice(-TOP_N);
	});
	// HTML labels render top-down, so they mirror the bottom-up chart data.
	let labels = $derived([...rows].reverse());

	function barColor(t: TagMetric): string {
		return sortKey === 'avg' ? scoreColor(t.avg) : palette[0];
	}


	let chartHeight = $derived(`${rows.length * ROW + TOP_PAD + AXIS_PAD}px`);

	let option = $derived({
		// left/right leave room for the first ("0s") and last x-tick labels, which center
		// on their ticks and would otherwise clip at the plot edges (watch-time labels are wide).
		grid: { left: 14, right: sortKey === 'watch' ? 50 : 24, top: TOP_PAD, bottom: AXIS_PAD, containLabel: false },
		tooltip: {
			...chartTooltipStyle,
			trigger: 'axis' as const,
			axisPointer: { type: 'shadow' as const },
			// Title on its own line, then the three metrics — always all three, whatever
			// the active sort. The genre description lives on the y-axis label instead.
			formatter: (params: unknown) => {
				const idx = (params as { dataIndex: number }[])[0]?.dataIndex ?? 0;
				const t = rows[idx];
				return t
					? `<strong>${escapeHtml(t.tag)}</strong><br/>Avg ${formatDecimalDigits(t.avg, 2)} · ${t.count} anime · ${formatDuration(t.watchSeconds)}`
					: '';
			},
		},
		xAxis: {
			type: 'value' as const,
			min: 0,
			max: axisMax,
			...(sortKey === 'count' ? { minInterval: 1 } : {}),
			axisLabel: {
				color: 'rgba(0,0,0,0.55)',
				fontSize: 11,
				...(sortKey === 'watch' ? { formatter: (v: number) => formatDuration(v) } : {}),
			},
			splitLine: { lineStyle: { color: 'rgba(0,0,0,0.07)' } },
		},
		yAxis: {
			type: 'category' as const,
			data: rows.map((t) => t.tag),
			axisLabel: { show: false }, // rendered as HTML on the left so they can carry tooltips / links
			axisLine: { show: false },
			axisTick: { show: false },
		},
		series: [
			{
				type: 'bar' as const,
				emphasis: { disabled: true },
				barWidth: '60%',
				data: rows.map((t) => ({ value: activeMetric.value(t), itemStyle: { color: barColor(t), borderRadius: [0, 4, 4, 0] } })),
			},
		],
	});
</script>

<div class="space-y-4">
	<div class="flex flex-wrap items-center justify-between gap-3">
		<h3 class="flex items-baseline gap-2 text-sm font-semibold text-card-foreground">
			<span>Breakdown by {dim === 'genres' ? 'genre' : 'studio'}</span>
			{#if allMetrics.length > rows.length}<span class="font-normal text-muted-foreground">Top {rows.length} of {allMetrics.length}</span>{/if}
		</h3>
		<SegmentedControl
			size="md"
			ariaLabel="Breakdown dimension"
			options={[{ value: 'genres', label: 'Genres' }, { value: 'studios', label: 'Studios' }]}
			value={dim}
			onSelect={(v) => (dim = v)}
		/>
	</div>

	<div class="flex flex-wrap items-center gap-2">
		<span class="text-muted-foreground text-xs uppercase tracking-wide">Sort by</span>
		<Select.Root type="single" value={sortKey} onValueChange={(v) => { if (v) sortKey = v as MetricKey; }}>
			<Select.Trigger class="w-44 bg-card/80 backdrop-blur border-input text-card-foreground">{activeMetric.label}</Select.Trigger>
			<Select.Content>
				{#each METRICS as m (m.key)}
					<Select.Item value={m.key}>{m.label}</Select.Item>
				{/each}
			</Select.Content>
		</Select.Root>
		<Tooltip text={dir === 'desc' ? 'Highest first (click for lowest)' : 'Lowest first (click for highest)'}>
			{#snippet trigger(props)}
				<button
					{...props}
					class="size-9 rounded-md border border-input bg-card/80 flex items-center justify-center text-card-foreground hover:bg-muted transition-colors"
					aria-label="Toggle sort direction"
					onclick={() => (dir = dir === 'desc' ? 'asc' : 'desc')}
				>
					{#if dir === 'desc'}<ArrowDown class="size-4" />{:else}<ArrowUp class="size-4" />{/if}
				</button>
			{/snippet}
		</Tooltip>
	</div>

	{#if rows.length}
		<!-- HTML y-axis labels (left) aligned row-for-row with the chart's bars (right).
		     gap-2 + grid.left keep the labels off the bars. -->
		<div class="flex gap-2">
			<div class="shrink-0 w-36" style="padding-top:{TOP_PAD}px;padding-bottom:{AXIS_PAD}px">
				{#each labels as t (t.tag)}
					<div class="flex items-center justify-end min-w-0 text-xs" style="height:{ROW}px">
						{#if dim === 'studios'}
							<button
								onclick={() => searchByStudio(t.tag)}
								class="truncate min-w-0 text-card-foreground hover:text-primary hover:underline transition-colors"
								title={t.tag}
							>{t.tag}</button>
						{:else if $genreDescriptions.get(t.tag.toLowerCase())}
							<Tooltip text={$genreDescriptions.get(t.tag.toLowerCase()) ?? ''} class="truncate min-w-0 text-card-foreground">{t.tag}</Tooltip>
						{:else}
							<span class="truncate min-w-0 text-card-foreground" title={t.tag}>{t.tag}</span>
						{/if}
					</div>
				{/each}
			</div>
			<div class="flex-1 min-w-0">
				<EChart {option} height={chartHeight} />
			</div>
		</div>
	{:else}
		<p class="text-sm text-muted-foreground">No data.</p>
	{/if}
</div>
