import type { EChartsOption } from 'echarts';
import { scoreColor } from '$lib/utils/chartColors';
import { formatDecimalDigits } from '$lib/utils/formatString';

/**
 * Shared ECharts tooltip config so chart hovers match the app `Tooltip` component
 * (primary-tinted `--tooltip-surface`, primary/40 border, soft primary glow — see
 * `ui/tooltip/tooltip-content.svelte`). Spread into a chart's `tooltip` alongside its
 * own `trigger`/`formatter`. The ECharts tooltip is a DOM node, so the CSS custom
 * props resolve against the active theme. Includes `confine: true` (every app chart
 * lives in a card, so the popup should never escape the chart box) — override via
 * spread order if a chart ever needs otherwise.
 */
export const chartTooltipStyle = {
	confine: true,
	backgroundColor: 'var(--tooltip-surface)',
	borderColor: 'color-mix(in oklch, var(--primary) 40%, transparent)',
	borderWidth: 1,
	textStyle: { color: 'var(--color-popover-foreground)', fontSize: 12 },
	// border-radius + glow have no dedicated tooltip options, so raw CSS (appended last
	// in ECharts' style string, so it wins). Shadow mirrors tooltip-content.svelte.
	extraCssText:
		'border-radius: 6px; box-shadow: 0 6px 24px -6px color-mix(in oklch, var(--primary) 55%, transparent);',
} as const;

/** Axis floor for a series whose interesting variation is small next to its absolute
 * value — a cumulative total. ECharts anchors a `value` axis at 0, so a one-month
 * window over a 112d→115d running total renders as a flat line pinned to the top of
 * the plot. Returning a floor just under the observed minimum instead spends the whole
 * axis on the span that actually varies. Pass it straight as `yAxis.min` — the
 * `{min, max} → number` shape IS ECharts' axis-extent callback contract.
 *
 * The fallback covers the degenerate window the naive `min - span·0.1` collapses on:
 * nothing watched in the range, so `max === min`, the span is 0 and the floor would
 * equal the value — a zero-height axis. Padding off the absolute value instead still
 * opens a window around the plateau. Clamped at 0 so a duration axis never dips
 * negative, which also covers the empty range (`min === max === 0` → 0). */
export function paddedAxisMin({ min, max }: { min: number; max: number }): number {
	const span = max - min || max * 0.02;
	return Math.max(0, min - span * 0.1);
}

/** Shared score gauge (0–10, color-ramped by value). Used by the anime-page
 * RatingsOverviewStats and the /ratings statistics Overview so the two can't
 * drift in shape. */
export function scoreGaugeOption(value: number): EChartsOption {
	const color = scoreColor(value);
	return {
		series: [
			{
				type: 'gauge',
				emphasis: { disabled: true },
				startAngle: 220,
				endAngle: -40,
				min: 0,
				max: 10,
				radius: '100%',
				center: ['50%', '55%'],
				pointer: { show: false },
				progress: { show: true, width: 10, roundCap: true, itemStyle: { color } },
				axisLine: { lineStyle: { width: 10, color: [[1, 'rgba(0,0,0,0.08)']] } },
				axisTick: { show: false },
				splitLine: { show: false },
				axisLabel: { show: false },
				detail: {
					offsetCenter: [0, '0%'],
					fontSize: 22,
					fontWeight: 'bold',
					color,
					formatter: (val: number) => formatDecimalDigits(val, 2),
				},
				data: [{ value }],
			},
		],
	};
}
