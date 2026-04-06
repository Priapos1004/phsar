<script lang="ts">
	import EChart from '$lib/components/EChart.svelte';
	import { formatSeason } from '$lib/utils/formatString';
	import { scoreColor } from '$lib/utils/chartColors';
	import type { AnimeMediaItem, RatingOut } from '$lib/types/api';

	interface MediaWithRating {
		media: AnimeMediaItem;
		rating: RatingOut | null;
	}

	interface Props {
		mediaWithRatings: MediaWithRating[];
	}

	let { mediaWithRatings }: Props = $props();

	let chartOption = $derived({
		tooltip: {
			trigger: 'item' as const,
			formatter: (params: unknown) => {
				const p = params as { dataIndex: number };
				const mr = mediaWithRatings[p.dataIndex];
				const title = mr.media.name_eng ?? mr.media.title;
				const season = formatSeason(mr.media.anime_season_name, mr.media.anime_season_year) ?? '';
				if (mr.rating) {
					const dropped = mr.rating.dropped ? ' <span style="color:#ef4444">(Dropped)</span>' : '';
					return `<strong>${title}</strong>${dropped}<br/>${mr.media.media_type} · ${season}<br/>Your score: <strong>${mr.rating.rating.toFixed(1)}</strong>`;
				}
				return `<strong>${title}</strong><br/>${mr.media.media_type} · ${season}<br/><span style="opacity:0.6">Not rated</span>`;
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
			axisLine: { lineStyle: { color: 'rgba(0,0,0,0.1)' } },
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
					if (mr.rating) {
						return {
							value: mr.rating.rating,
							itemStyle: {
								color: scoreColor(mr.rating.rating),
								borderRadius: [3, 3, 0, 0],
								opacity: mr.rating.dropped ? 0.5 : 1,
							},
						};
					}
					return {
						value: 0.3,
						itemStyle: {
							color: 'rgba(0,0,0,0.08)',
							borderRadius: [3, 3, 0, 0],
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
	<p class="text-sm text-muted-foreground text-center mt-1">
		Media in release order (1 = earliest)
	</p>
</div>
