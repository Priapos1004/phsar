<script lang="ts">
	import EChart from '$lib/components/EChart.svelte';
	import { scoreColor, STATUS_COLORS } from '$lib/utils/chartColors';
	import { formatDecimalDigits } from '$lib/utils/formatString';
	import { attributeCorrelations, attributeCategoryEffects } from '$lib/utils/ratingStats';
	import { chartTooltipStyle } from '$lib/utils/chartTheme';
	import { RATING_ATTRIBUTE_OPTIONS, type RatingScoreItem } from '$lib/types/api';

	interface Props {
		items: RatingScoreItem[];
	}

	let { items }: Props = $props();

	let corr = $derived(attributeCorrelations(items));
	// Category axis renders bottom-up, so reverse() once puts the strongest at the top.
	let revCorr = $derived([...corr].reverse());
	let effects = $derived(attributeCategoryEffects(items));

	const label = (key: string) => RATING_ATTRIBUTE_OPTIONS[key]?.label ?? key;
	const valueLabel = (key: string, value: string) =>
		RATING_ATTRIBUTE_OPTIONS[key]?.options.find((o) => o.value === value)?.label ?? value;

	// Signed Spearman ρ per ordinal attribute. Positive = higher level → higher score.
	let corrOption = $derived({
		grid: { left: 4, right: 16, top: 8, bottom: 24, containLabel: true },
		tooltip: {
			...chartTooltipStyle,
			trigger: 'axis' as const,
			axisPointer: { type: 'shadow' as const },
			formatter: (params: unknown) => {
				const arr = params as { dataIndex: number }[];
				const c = revCorr[arr[0].dataIndex];
				return c ? `${label(c.key)}<br/>ρ = ${formatDecimalDigits(c.rho, 2)} · n=${c.n}` : '';
			},
		},
		xAxis: {
			type: 'value' as const,
			min: -1,
			max: 1,
			axisLabel: { color: 'rgba(0,0,0,0.55)', fontSize: 11 },
			splitLine: { lineStyle: { color: 'rgba(0,0,0,0.07)' } },
		},
		yAxis: {
			type: 'category' as const,
			data: revCorr.map((c) => label(c.key)),
			axisLabel: { color: 'rgba(0,0,0,0.75)', fontSize: 11 },
			axisLine: { lineStyle: { color: 'rgba(0,0,0,0.15)' } },
			axisTick: { show: false },
		},
		series: [
			{
				type: 'bar' as const,
				emphasis: { disabled: true },
				barWidth: '62%',
				data: revCorr.map((c) => ({
					value: Number(c.rho.toFixed(2)),
					itemStyle: { color: c.rho >= 0 ? STATUS_COLORS.completed : STATUS_COLORS.dropped, borderRadius: 3 },
				})),
			},
		],
	});

	function effectOption(categories: { value: string; mean: number; count: number }[], key: string, overallMean: number) {
		const rev = [...categories].reverse();
		return {
			grid: { left: 4, right: 16, top: 8, bottom: 24, containLabel: true },
			tooltip: {
				...chartTooltipStyle,
				trigger: 'axis' as const,
				axisPointer: { type: 'shadow' as const },
				formatter: (params: unknown) => {
					const arr = params as { dataIndex: number }[];
					const c = rev[arr[0].dataIndex];
					return c ? `${valueLabel(key, c.value)}<br/>avg ${formatDecimalDigits(c.mean, 2)} · n=${c.count}` : '';
				},
			},
			xAxis: {
				type: 'value' as const,
				min: 0,
				max: 10,
				axisLabel: { color: 'rgba(0,0,0,0.55)', fontSize: 11 },
				splitLine: { lineStyle: { color: 'rgba(0,0,0,0.07)' } },
			},
			yAxis: {
				type: 'category' as const,
				data: rev.map((c) => valueLabel(key, c.value)),
				axisLabel: { color: 'rgba(0,0,0,0.75)', fontSize: 11 },
				axisLine: { lineStyle: { color: 'rgba(0,0,0,0.15)' } },
				axisTick: { show: false },
			},
			series: [
				{
					type: 'bar' as const,
					emphasis: { disabled: true },
					barWidth: '55%',
					markLine: {
						symbol: 'none',
						lineStyle: { color: 'rgba(0,0,0,0.45)', type: 'dashed' as const },
						label: { formatter: 'your avg', color: 'rgba(0,0,0,0.5)', fontSize: 10 },
						data: [{ xAxis: Number(overallMean.toFixed(2)) }],
					},
					data: rev.map((c) => ({ value: Number(c.mean.toFixed(2)), itemStyle: { color: scoreColor(c.mean), borderRadius: [0, 4, 4, 0] } })),
				},
			],
		};
	}

	const barH = (n: number) => `${Math.max(110, n * 30 + 36)}px`;
	// eta → plain-language strength of a nominal attribute's pull on the score.
	const etaWord = (eta: number) => (eta >= 0.45 ? 'strong' : eta >= 0.25 ? 'moderate' : 'weak');
</script>

{#if corr.length === 0 && effects.length === 0}
	<p class="text-sm text-muted-foreground">
		Rate the optional attributes (pace, animation, story…) on a few titles to see which ones move your scores.
	</p>
{:else}
	<div class="space-y-6">
		{#if corr.length}
			<div>
				<p class="text-sm font-medium text-card-foreground">What raises or lowers your scores</p>
				<p class="text-xs text-muted-foreground mb-1">
					Rank correlation of each quality scale with your rating — right (green) means higher = you score it higher.
				</p>
				<EChart option={corrOption} height={barH(corr.length)} />
			</div>
		{/if}

		{#each effects as eff (eff.key)}
			<div>
				<p class="text-sm font-medium text-card-foreground">{label(eff.key)}</p>
				<p class="text-xs text-muted-foreground mb-1">
					Average score per choice ({etaWord(eff.eta)} effect — explains ~{Math.round(eff.eta * eff.eta * 100)}% of your score spread).
				</p>
				<EChart option={effectOption(eff.categories, eff.key, eff.overallMean)} height={barH(eff.categories.length)} />
			</div>
		{/each}
	</div>
{/if}
