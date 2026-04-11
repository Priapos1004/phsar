<script lang="ts">
	import EChart from '$lib/components/EChart.svelte';
	import { formatSeason, formatDecimalDigits, decimalPlaces, formatRelationType, formatMediaType } from '$lib/utils/formatString';
	import { RELATION_TYPE_COLORS, RELATION_TYPE_ORDER, CHART_COLORS } from '$lib/utils/chartColors';
	import type { AnimeMediaItem, RatingOut } from '$lib/types/api';

	interface MediaWithRating {
		media: AnimeMediaItem;
		rating: RatingOut | null;
	}

	interface Props {
		mediaWithRatings: MediaWithRating[];
		minScoreDecimals: number;
	}

	let { mediaWithRatings, minScoreDecimals }: Props = $props();

	const DIMMED_COLOR = 'rgba(0,0,0,0.10)';
	const UNRATED_OPACITY = 0.2;

	const orderIndex = (t: string) => {
		const i = (RELATION_TYPE_ORDER as readonly string[]).indexOf(t);
		return i === -1 ? RELATION_TYPE_ORDER.length : i;
	};

	let activeRelationTypes = $derived(
		[...new Set(mediaWithRatings.map((mr) => mr.media.relation_type))]
			.sort((a, b) => orderIndex(a) - orderIndex(b)),
	);

	/** Types currently deselected — empty set means all are shown. */
	let deselected = $state(new Set<string>());
	let allSelected = $derived(deselected.size === 0);

	// Reset filter when navigating to a different anime
	$effect(() => {
		mediaWithRatings;
		deselected = new Set();
	});

	function toggleType(type: string) {
		const next = new Set(deselected);
		if (next.has(type)) {
			next.delete(type);
		} else {
			next.add(type);
			// If everything is now deselected, reset to show all
			if (next.size === activeRelationTypes.length) {
				deselected = new Set();
				return;
			}
		}
		deselected = next;
	}

	let chartOption = $derived({
		tooltip: {
			trigger: 'item' as const,
			confine: true,
			formatter: (params: unknown) => {
				const p = params as { dataIndex: number };
				const mr = mediaWithRatings[p.dataIndex];
				const title = mr.media.name_eng ?? mr.media.title;
				const relation = formatRelationType(mr.media.relation_type);
				const season = formatSeason(mr.media.anime_season_name, mr.media.anime_season_year) ?? '';
				if (mr.rating) {
					const dropped = mr.rating.dropped ? ' <span style="color:#ef4444">(Dropped)</span>' : '';
					return `<strong>${title}</strong>${dropped}<br/>${formatMediaType(mr.media.media_type)} · ${relation} · ${season}<br/>Your score: <strong>${formatDecimalDigits(mr.rating.rating, Math.max(minScoreDecimals, decimalPlaces(mr.rating.rating)))}</strong>`;
				}
				return `<strong>${title}</strong><br/>${formatMediaType(mr.media.media_type)} · ${relation} · ${season}<br/><span style="opacity:0.6">Not rated</span>`;
			},
		},
		grid: {
			left: 35,
			right: 10,
			top: 10,
			bottom: 30,
		},
		xAxis: {
			type: 'category' as const,
			data: mediaWithRatings.map((_, i) => String(i + 1)),
			axisLabel: {
				color: 'rgba(0,0,0,0.4)',
				fontSize: 11,
			},
			axisLine: { lineStyle: { color: DIMMED_COLOR } },
			axisTick: { show: false },
		},
		yAxis: {
			type: 'value' as const,
			min: 0,
			max: 10,
			interval: 2,
			axisLabel: {
				color: 'rgba(0,0,0,0.4)',
				fontSize: 11,
			},
			splitLine: { lineStyle: { color: 'rgba(0,0,0,0.06)' } },
		},
		series: [
			{
				type: 'bar' as const,
				data: mediaWithRatings.map((mr) => {
					const typeColor = RELATION_TYPE_COLORS[mr.media.relation_type] ?? CHART_COLORS.chart4;
					const highlighted = allSelected || !deselected.has(mr.media.relation_type);
					const value = mr.rating ? mr.rating.rating : 0.3;
					const opacity = !mr.rating ? UNRATED_OPACITY : mr.rating.dropped ? 0.5 : 1;
					return {
						value,
						itemStyle: {
							color: highlighted ? typeColor : DIMMED_COLOR,
							borderRadius: [3, 3, 0, 0],
							opacity,
						},
					};
				}),
				barMaxWidth: 28,
				emphasis: { disabled: true },
			},
		],
	});
</script>

<div>
	<h3 class="text-sm font-medium text-muted-foreground mb-2">Rating Timeline</h3>
	<EChart option={chartOption} height="176px" />
	<div class="flex justify-center gap-3 mt-1">
		{#each activeRelationTypes as type}
			<button
				class="text-xs flex items-center gap-1 transition-opacity cursor-pointer"
				class:opacity-40={!allSelected && deselected.has(type)}
				aria-pressed={allSelected || !deselected.has(type)}
				onclick={() => toggleType(type)}
			>
				<span
					class="inline-block w-2 h-2 rounded-full"
					style="background: {RELATION_TYPE_COLORS[type] ?? CHART_COLORS.chart4}"
				></span>
				<span class="text-muted-foreground">{formatRelationType(type)}</span>
			</button>
		{/each}
	</div>
	<p class="text-sm text-muted-foreground text-center mt-1">
		Media in release order (1 = earliest)
	</p>
</div>
