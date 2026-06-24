<script lang="ts">
	import EChart from '$lib/components/EChart.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { getThemedChartColorPalette } from '$lib/utils/chartColors';
	import { ratingSequence, movingAverage, cumulativeWatchTime } from '$lib/utils/ratingStats';
	import { chartTooltipStyle } from '$lib/utils/chartTheme';
	import { formatDuration, formatDurationCompact, formatDecimalDigits, resolveTitle } from '$lib/utils/formatString';
	import { userSettings } from '$lib/stores/userSettings';
	import type { RatingScoreItem } from '$lib/types/api';

	interface Props {
		items: RatingScoreItem[];
	}

	let { items }: Props = $props();

	let palette = $derived(getThemedChartColorPalette());
	let nameLanguage = $derived($userSettings?.name_language ?? 'english');

	// ── (f) Rating trend: equidistant sequence + trailing moving average ──────
	let seq = $derived(ratingSequence(items));
	const MA_WINDOWS = [5, 10, 20, 40];
	let windowOptions = $derived(MA_WINDOWS.filter((w) => w <= seq.length));
	let maWindow = $state(10);
	// Keep the selected window valid as the dataset/options change.
	let effectiveWindow = $derived(
		windowOptions.length ? (windowOptions.includes(maWindow) ? maWindow : windowOptions[windowOptions.length - 1]) : Math.max(2, seq.length),
	);
	let ma = $derived(movingAverage(seq.map((p) => p.score), effectiveWindow));

	let trendOption = $derived({
		// bottom:44 gives the "rating #" axis name room below the tick labels instead of
		// jamming it against the chart edge (where it crowded the caption below).
		grid: { left: 32, right: 12, top: 12, bottom: 44 },
		tooltip: {
			...chartTooltipStyle,
			trigger: 'axis' as const,
			// Prepend the title (in the user's name language); keep the default colored
			// dot + series rows (Score / moving average) below it.
			formatter: (params: unknown) => {
				const arr = params as { dataIndex: number; seriesType: string; marker: string; seriesName: string; value: [number, number] }[];
				const p = seq[arr[0]?.dataIndex ?? 0];
				const head = p ? `<strong>${resolveTitle(p.title, p.nameEng, p.nameJap, nameLanguage)}</strong><br/>` : '';
				const rows = arr
					.map((a) => `${a.marker} ${a.seriesName} ${formatDecimalDigits(Number(a.value[1]), a.seriesType === 'scatter' ? 1 : 2)}`)
					.join('<br/>');
				return head + rows;
			},
		},
		xAxis: {
			type: 'value' as const,
			name: 'rating #',
			nameLocation: 'middle' as const,
			nameGap: 20,
			min: 1,
			max: Math.max(1, seq.length),
			axisLabel: { color: 'rgba(0,0,0,0.55)', fontSize: 11 },
			splitLine: { show: false },
		},
		yAxis: {
			type: 'value' as const,
			min: 0,
			max: 10,
			axisLabel: { color: 'rgba(0,0,0,0.55)', fontSize: 11 },
			splitLine: { lineStyle: { color: 'rgba(0,0,0,0.07)' } },
		},
		series: [
			{
				name: 'Score',
				type: 'scatter' as const,
				emphasis: { disabled: true },
				symbolSize: 5,
				itemStyle: { color: palette[0], opacity: 0.3 },
				data: seq.map((p) => [p.index, p.score]),
				z: 2,
			},
			{
				name: `${effectiveWindow}-rating average`,
				type: 'line' as const,
				emphasis: { disabled: true },
				showSymbol: false,
				smooth: true,
				lineStyle: { color: palette[3], width: 2.5 },
				data: ma.map((v, i) => [i + 1, Number(v.toFixed(2))]),
				z: 3,
			},
		],
	});

	// ── (g) Cumulative watch time over when you rated ─────────────────────────
	const RANGES = [
		{ key: '1m', label: '1 month' },
		{ key: '3m', label: '3 months' },
		{ key: 'all', label: 'All' },
	] as const;
	let range = $state<'all' | '3m' | '1m'>('1m');

	function cutoffISO(r: 'all' | '3m' | '1m'): string | undefined {
		if (r === 'all') return undefined;
		const d = new Date();
		d.setMonth(d.getMonth() - (r === '3m' ? 3 : 1));
		return d.toISOString();
	}

	let cumulative = $derived(cumulativeWatchTime(items, cutoffISO(range)));
	let cumOption = $derived({
		grid: { left: 48, right: 12, top: 12, bottom: 28 },
		tooltip: {
			...chartTooltipStyle,
			trigger: 'axis' as const,
			valueFormatter: (v: unknown) => formatDuration(Number(v)),
		},
		xAxis: {
			type: 'time' as const,
			axisLabel: { color: 'rgba(0,0,0,0.55)', fontSize: 10 },
			axisLine: { lineStyle: { color: 'rgba(0,0,0,0.15)' } },
		},
		yAxis: {
			type: 'value' as const,
			// Compact d/h/m label so the ticks fit (full duration is in the tooltip).
			axisLabel: { color: 'rgba(0,0,0,0.55)', fontSize: 11, formatter: (v: number) => formatDurationCompact(v) },
			splitLine: { lineStyle: { color: 'rgba(0,0,0,0.07)' } },
		},
		series: [
			{
				type: 'line' as const,
				emphasis: { disabled: true },
				showSymbol: false,
				step: 'end' as const,
				lineStyle: { color: palette[1], width: 2 },
				areaStyle: { color: palette[1], opacity: 0.12 },
				data: cumulative.map((p) => [new Date(p.date).getTime(), p.seconds]),
			},
		],
	});
</script>

<div class="space-y-6">
	<!-- (f) Rating trend -->
	<div>
		<div class="flex items-center justify-between mb-1">
			<p class="text-sm font-medium text-card-foreground">Score trend (in rating order)</p>
			{#if windowOptions.length > 1}
				<SegmentedControl
					ariaLabel="Moving-average window"
					options={windowOptions.map((w) => ({ value: w, label: String(w) }))}
					value={effectiveWindow}
					onSelect={(v) => (maWindow = v)}
				/>
			{/if}
		</div>
		{#if seq.length >= 2}
			<EChart option={trendOption} height="240px" />
			<p class="text-[11px] text-muted-foreground mt-3">
				Each point is one of your ratings, oldest to newest; the line is a {effectiveWindow}-rating moving average — a downward slope means you've been rating things lower lately.
			</p>
		{:else}
			<p class="text-sm text-muted-foreground">Rate a few more titles to see your trend.</p>
		{/if}
	</div>

	<!-- (g) Cumulative watch time -->
	<div>
		<div class="flex items-center justify-between mb-1">
			<p class="text-sm font-medium text-card-foreground">Cumulative watch time</p>
			<SegmentedControl
				ariaLabel="Time range"
				options={RANGES.map((r) => ({ value: r.key, label: r.label }))}
				value={range}
				onSelect={(v) => (range = v)}
			/>
		</div>
		{#if cumulative.length}
			<EChart option={cumOption} height="220px" />
		{:else}
			<p class="text-sm text-muted-foreground">No completed titles with known episode counts in this range.</p>
		{/if}
	</div>
</div>
