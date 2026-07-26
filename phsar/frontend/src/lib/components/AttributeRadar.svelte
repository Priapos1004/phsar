<script lang="ts">
	import EChart from '$lib/components/EChart.svelte';
	import { RATING_ATTRIBUTE_OPTIONS, getRatingAttr } from '$lib/types/api';
	import { getThemedChartColorPalette } from '$lib/utils/chartColors';
	import { chartTooltipStyle } from '$lib/utils/chartTheme';
	import type { RatingOut, RatingScoreItem } from '$lib/types/api';

	interface Props {
		// Accepts either shape — only the 11 attribute keys are read (via getRatingAttr),
		// which both RatingOut and the /ratings page's RatingScoreItem carry.
		ratings: RatingOut[] | RatingScoreItem[];
		/**
		 * Fires once this component has rendered whatever it is going to render — for the
		 * share-card capture. Passing it also turns the entrance animation OFF: a capture
		 * has no reason to wait out a grow-in it will never show. It also fires when there
		 * is no radar to draw (no quality attribute rated), so "ready" is total and the
		 * caller's timeout stays a pure hang guard instead of a routine wait.
		 */
		onReady?: () => void;
	}

	let { ratings, onReady }: Props = $props();

	// Quality attributes with a clear "bad to good" scale for radar visualization.
	// ending_quality deliberately excludes "not_applicable" — those ratings are
	// skipped by the scoreMap[val] !== undefined check in the averaging loop.
	const ATTR_SCORE_MAP: Record<string, Record<string, number>> = {
		animation_quality: { bad: 1, normal: 2, good: 3, very_good: 4 },
		dialogue_quality: { flat: 1, normal: 2, deep: 3 },
		character_depth: { flat: 1, normal: 2, complex: 3 },
		story_quality: { weak: 1, average: 2, good: 3, outstanding: 4 },
		ending_quality: { unsatisfying: 1, neutral: 2, satisfying: 3, very_satisfying: 4 },
	};

	const RADAR_KEYS = Object.keys(ATTR_SCORE_MAP);
	const RADAR_LABELS = RADAR_KEYS.map((k) => RATING_ATTRIBUTE_OPTIONS[k].label);
	const RADAR_MAXES = RADAR_KEYS.map((k) => Math.max(...Object.values(ATTR_SCORE_MAP[k])));

	let radarData = $derived.by(() => {
		const avgs: number[] = [];
		const closestLabels: (string | null)[] = [];
		let hasData = false;

		for (let i = 0; i < RADAR_KEYS.length; i++) {
			const key = RADAR_KEYS[i];
			const scoreMap = ATTR_SCORE_MAP[key];

			let sum = 0;
			let count = 0;
			for (const r of ratings) {
				const val = getRatingAttr(r, key);
				if (val && scoreMap[val] !== undefined) {
					sum += scoreMap[val];
					count++;
				}
			}

			if (count > 0) {
				const rawAvg = sum / count;
				avgs.push(rawAvg / RADAR_MAXES[i]);
				hasData = true;
				const closest = Object.entries(scoreMap).reduce(
					(best, [k, score]) =>
						Math.abs(score - rawAvg) < Math.abs(best[1] - rawAvg)
							? ([k, score] as [string, number])
							: best,
					Object.entries(scoreMap)[0] as [string, number],
				);
				closestLabels.push(
					RATING_ATTRIBUTE_OPTIONS[key].options.find((o) => o.value === closest[0])?.label ??
						closest[0],
				);
			} else {
				avgs.push(0);
				closestLabels.push(null);
			}
		}

		return { avgs, closestLabels, hasData };
	});

	// Both readiness paths funnel through here so a consumer only ever sees one signal.
	let painted = false;
	function notifyPainted() {
		if (painted) return;
		painted = true;
		onReady?.();
	}

	// Nothing to draw → no EChart mounts → no `finished` event, so report ready here.
	$effect(() => {
		if (!radarData.hasData) notifyPainted();
	});

	let radarOption = $derived.by(() => {
		const primaryColor = getThemedChartColorPalette()[0];
		return {
			animation: !onReady,
			radar: {
				indicator: RADAR_LABELS.map((name) => ({ name, max: 1 })),
				splitNumber: 3,
				shape: 'polygon' as const,
				axisName: {
					color: 'rgba(0,0,0,0.7)',
					fontSize: 12,
				},
				splitArea: {
					areaStyle: { color: ['rgba(0,0,0,0.02)', 'rgba(0,0,0,0.04)'] },
				},
				splitLine: { lineStyle: { color: 'rgba(0,0,0,0.08)' } },
			},
			series: [
				{
					type: 'radar' as const,
					emphasis: { disabled: true },
					data: [
						{
							name: 'Your Profile',
							value: radarData.avgs,
							areaStyle: { color: primaryColor, opacity: 0.2 },
							lineStyle: { color: primaryColor, width: 2 },
							itemStyle: { color: primaryColor },
						},
					],
				},
			],
			tooltip: {
				...chartTooltipStyle,
				trigger: 'item' as const,
				confine: true,
				formatter: () =>
					RADAR_LABELS.map((label, i) => {
						const closestLabel = radarData.closestLabels[i];
						if (!closestLabel) return `${label}: <strong>--</strong>`;
						return `${label}: <strong>${closestLabel}</strong>`;
					}).join('<br/>'),
			},
		};
	});
</script>

{#if radarData.hasData}
	<EChart option={radarOption} height="224px" onReady={notifyPainted} />
{/if}
