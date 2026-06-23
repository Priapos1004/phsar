<script lang="ts">
	import EChart from '$lib/components/EChart.svelte';
	import { scoreColor, STATUS_COLORS } from '$lib/utils/chartColors';
	import { tagAvg, tagStatusBreakdown, type TagDim } from '$lib/utils/ratingStats';
	import type { RatingScoreItem } from '$lib/types/api';

	interface Props {
		items: RatingScoreItem[];
	}

	let { items }: Props = $props();

	const TOP_N = 12;
	let dim = $state<TagDim>('genres');

	// Category axis renders bottom-up, so reverse() puts the top entry at the top.
	let avg = $derived(tagAvg(items, dim).slice(0, TOP_N).reverse());
	let status = $derived(tagStatusBreakdown(items, dim).slice(0, TOP_N).reverse());

	const baseGrid = { left: 4, right: 20, top: 8, bottom: 8, containLabel: true };
	const catAxis = (data: string[]) => ({
		type: 'category' as const,
		data,
		axisLabel: { color: 'rgba(0,0,0,0.75)', fontSize: 11 },
		axisLine: { lineStyle: { color: 'rgba(0,0,0,0.15)' } },
		axisTick: { show: false },
	});
	const valAxis = (extra: Record<string, unknown> = {}) => ({
		type: 'value' as const,
		axisLabel: { color: 'rgba(0,0,0,0.55)', fontSize: 11 },
		splitLine: { lineStyle: { color: 'rgba(0,0,0,0.07)' } },
		...extra,
	});

	let avgOption = $derived({
		grid: baseGrid,
		tooltip: { trigger: 'axis' as const, axisPointer: { type: 'shadow' as const } },
		xAxis: valAxis({ min: 0, max: 10 }),
		yAxis: catAxis(avg.map((t) => t.tag)),
		series: [
			{
				type: 'bar' as const,
				emphasis: { disabled: true },
				barWidth: '62%',
				data: avg.map((t) => ({
					value: Number(t.avg.toFixed(2)),
					itemStyle: { color: scoreColor(t.avg), borderRadius: [0, 4, 4, 0] },
				})),
			},
		],
	});

	// Stacked counts: completed / on-hold / dropped. A small drop count reads as a
	// thin red cap on a long bar instead of a lonely stamp on a near-empty rate axis.
	let statusOption = $derived({
		grid: baseGrid,
		legend: { data: ['Completed', 'On hold', 'Dropped'], top: 0, right: 0, textStyle: { color: 'rgba(0,0,0,0.6)' }, itemWidth: 10, itemHeight: 10 },
		tooltip: { trigger: 'axis' as const, axisPointer: { type: 'shadow' as const } },
		xAxis: valAxis({ minInterval: 1 }),
		yAxis: catAxis(status.map((t) => t.tag)),
		series: [
			{ name: 'Completed', type: 'bar' as const, stack: 's', emphasis: { disabled: true }, itemStyle: { color: STATUS_COLORS.completed }, data: status.map((t) => t.completed) },
			{ name: 'On hold', type: 'bar' as const, stack: 's', emphasis: { disabled: true }, itemStyle: { color: STATUS_COLORS.on_hold }, data: status.map((t) => t.onHold) },
			{ name: 'Dropped', type: 'bar' as const, stack: 's', emphasis: { disabled: true }, itemStyle: { color: STATUS_COLORS.dropped, borderRadius: [0, 4, 4, 0] }, data: status.map((t) => t.dropped) },
		],
	});

	// Chart height grows with the number of bars so labels stay legible.
	const barH = (n: number) => `${Math.max(120, n * 26 + 48)}px`;
</script>

<div class="space-y-5">
	<div class="flex items-center justify-between">
		<h3 class="text-sm font-semibold text-card-foreground">Breakdown by {dim === 'genres' ? 'genre' : 'studio'}</h3>
		<div class="flex gap-1.5">
			{#each [{ key: 'genres', label: 'Genres' }, { key: 'studios', label: 'Studios' }] as opt (opt.key)}
				<button
					onclick={() => (dim = opt.key as TagDim)}
					class="px-3 py-1 rounded-full text-xs border transition-colors {dim === opt.key
						? 'border-primary bg-primary/15 text-primary'
						: 'border-border text-muted-foreground hover:bg-muted/40'}"
				>{opt.label}</button>
			{/each}
		</div>
	</div>

	<div>
		<p class="text-xs text-muted-foreground mb-1">Average score</p>
		{#if avg.length}<EChart option={avgOption} height={barH(avg.length)} />{:else}<p class="text-sm text-muted-foreground">No data.</p>{/if}
	</div>

	<div>
		<p class="text-xs text-muted-foreground mb-1">How much you watch &amp; finish</p>
		{#if status.length}<EChart option={statusOption} height={barH(status.length)} />{:else}<p class="text-sm text-muted-foreground">No data.</p>{/if}
	</div>
</div>
