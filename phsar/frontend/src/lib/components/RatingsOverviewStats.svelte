<script lang="ts">
	import EChart from '$lib/components/EChart.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { scoreColor } from '$lib/utils/chartColors';
	import { formatDecimalDigits } from '$lib/utils/formatString';

	interface Props {
		avgScore: number;
		ratedCount: number;
		totalCount: number;
		droppedCount: number;
		totalEpisodesWatched: number;
		totalEpisodesAvailable: number;
	}

	let {
		avgScore,
		ratedCount,
		totalCount,
		droppedCount,
		totalEpisodesWatched,
		totalEpisodesAvailable,
	}: Props = $props();

	let ratedPercent = $derived(totalCount > 0 ? Math.round((ratedCount / totalCount) * 100) : 0);
	let episodePercent = $derived(
		totalEpisodesAvailable > 0
			? Math.round((totalEpisodesWatched / totalEpisodesAvailable) * 100)
			: 0,
	);

	let gaugeOption = $derived({
		series: [
			{
				type: 'gauge' as const,
				emphasis: { disabled: true },
				startAngle: 220,
				endAngle: -40,
				min: 0,
				max: 10,
				radius: '100%',
				center: ['50%', '55%'],
				pointer: { show: false },
				progress: {
					show: true,
					width: 10,
					roundCap: true,
					itemStyle: { color: scoreColor(avgScore) },
				},
				axisLine: {
					lineStyle: {
						width: 10,
						color: [[1, 'rgba(0,0,0,0.08)']] as [number, string][],
					},
				},
				axisTick: { show: false },
				splitLine: { show: false },
				axisLabel: { show: false },
				detail: {
					offsetCenter: [0, '0%'],
					fontSize: 22,
					fontWeight: 'bold' as const,
					color: scoreColor(avgScore),
					formatter: (val: number) => formatDecimalDigits(val, 2),
				},
				data: [{ value: avgScore }],
			},
		],
	});
</script>

<div class="grid grid-cols-2 md:grid-cols-4 gap-4">
	<div class="flex flex-col items-center">
		<EChart option={gaugeOption} width="96px" height="96px" />
		<span class="text-sm text-muted-foreground -mt-2">Your Average</span>
	</div>

	<div class="flex flex-col items-center justify-center gap-2">
		<div class="text-center">
			<span class="text-2xl font-bold text-card-foreground">{ratedCount}</span>
			<span class="text-muted-foreground">/ {totalCount}</span>
		</div>
		<div class="w-full max-w-[120px] h-2 rounded-full bg-muted overflow-hidden">
			<div
				class="h-full rounded-full bg-primary transition-all duration-500"
				style="width: {ratedPercent}%"
			></div>
		</div>
		<span class="text-sm text-muted-foreground">Media Rated</span>
	</div>

	<div class="flex flex-col items-center justify-center gap-2">
		<div class="text-center">
			<span class="text-2xl font-bold text-card-foreground">{totalEpisodesWatched}</span>
			{#if totalEpisodesAvailable > 0}
				<span class="text-muted-foreground">/ {totalEpisodesAvailable}</span>
			{/if}
		</div>
		{#if totalEpisodesAvailable > 0}
			<div class="w-full max-w-[120px] h-2 rounded-full bg-muted overflow-hidden">
				<div
					class="h-full rounded-full bg-chart-2 transition-all duration-500"
					style="width: {episodePercent}%"
				></div>
			</div>
		{/if}
		<span class="text-sm text-muted-foreground">Episodes Watched</span>
	</div>

	<div class="flex flex-col items-center justify-center gap-2">
		<span class="text-2xl font-bold text-card-foreground">{droppedCount}</span>
		{#if droppedCount > 0}
			<Badge variant="destructive">Dropped</Badge>
		{:else}
			<span class="text-sm text-muted-foreground">Dropped</span>
		{/if}
	</div>
</div>
