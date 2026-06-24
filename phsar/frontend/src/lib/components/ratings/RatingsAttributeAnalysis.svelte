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

	// |ρ| per quality scale (importance); the sign is conveyed by bar color, not the axis.
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
			// Importance = |ρ| on 0..1 (these scales are directional, so ρ is ~always
			// positive — a -1..1 axis would waste half the width); sign is kept via color.
			type: 'value' as const,
			min: 0,
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
					value: Number(Math.abs(c.rho).toFixed(2)),
					itemStyle: { color: c.rho >= 0 ? STATUS_COLORS.completed : STATUS_COLORS.dropped, borderRadius: [0, 3, 3, 0] },
				})),
			},
		],
	});

	function effectOption(categories: { value: string; mean: number; count: number }[], key: string, overallMean: number) {
		const rev = [...categories].reverse();
		return {
			// top:24 leaves room for the "your avg" markLine label (was clipped at top:8).
			grid: { left: 4, right: 16, top: 24, bottom: 24, containLabel: true },
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
						label: { formatter: `your avg ${formatDecimalDigits(overallMean, 1)}`, color: 'rgba(0,0,0,0.5)', fontSize: 10 },
						data: [{ xAxis: Number(overallMean.toFixed(2)) }],
					},
					data: rev.map((c) => ({ value: Number(c.mean.toFixed(2)), itemStyle: { color: scoreColor(c.mean), borderRadius: [0, 4, 4, 0] } })),
				},
			],
		};
	}

	const barH = (n: number) => `${Math.max(110, n * 30 + 36)}px`;
	// Per-choice charts carry the markLine label, so they need more vertical chrome.
	const effectH = (n: number) => `${Math.max(130, n * 32 + 60)}px`;
	// eta → plain-language strength of a categorical attribute's pull on the score.
	const etaWord = (eta: number) => (eta >= 0.45 ? 'Strong' : eta >= 0.25 ? 'Moderate' : 'Weak');
</script>

{#if corr.length === 0 && effects.length === 0}
	<p class="text-sm text-muted-foreground">
		Rate the optional attributes (pace, animation, story…) on a few titles to see which ones move your scores.
	</p>
{:else}
	<div class="space-y-8">
		{#if corr.length}
			<section class="space-y-2">
				<div>
					<p class="text-sm font-medium text-card-foreground">Quality scales — what drives your scores most</p>
					<p class="text-xs text-muted-foreground">
						How strongly each low→high quality scale tracks your rating (Spearman ρ): 0 = no link, 1 = a higher level
						always means a higher score. Green is that usual direction; red would be the rare
						inverse (you score higher-quality titles lower). Needs ≥5 rated titles.
					</p>
				</div>
				<EChart option={corrOption} height={barH(corr.length)} />
			</section>
		{/if}

		{#if effects.length}
			<section class="space-y-3">
				<div>
					<p class="text-sm font-medium text-card-foreground">Categorical choices — your average score per option</p>
					<p class="text-xs text-muted-foreground">
						These options have no quality direction, so instead of a correlation we show your average score for
						each option against the dashed “your avg” line. That line is your average across only the titles where
						you rated this attribute — a subset — so it can differ slightly between charts. The percentage is how much
						of your score spread that choice explains — higher means it matters more to your scores.
					</p>
				</div>
				{#each effects as eff (eff.key)}
					<div>
						<p class="text-sm font-medium text-card-foreground">{label(eff.key)}</p>
						<p class="text-xs text-muted-foreground mb-1">
							{etaWord(eff.eta)} effect — explains ~{Math.round(eff.eta * eff.eta * 100)}% of your score spread.
						</p>
						<EChart option={effectOption(eff.categories, eff.key, eff.overallMean)} height={effectH(eff.categories.length)} />
					</div>
				{/each}
			</section>
		{/if}
	</div>
{/if}
