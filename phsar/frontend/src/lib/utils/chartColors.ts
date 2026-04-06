/**
 * Chart color constants mirroring --color-chart-* from app.css.
 * ECharts requires raw color strings (not CSS var() references),
 * so these are maintained as JS constants alongside the CSS definitions.
 */

export const CHART_COLORS = {
	chart1: 'oklch(0.558 0.288 302.321)', // primary purple
	chart2: 'oklch(0.696 0.17 162.48)',    // green
	chart3: 'oklch(0.769 0.188 70.08)',    // yellow
	chart4: 'oklch(0.627 0.265 303.9)',    // light purple
	chart5: 'oklch(0.645 0.246 16.439)',   // red
} as const;

/** Ordered palette for cycling through chart series. */
export const CHART_COLOR_PALETTE = [
	CHART_COLORS.chart1,
	CHART_COLORS.chart2,
	CHART_COLORS.chart3,
	CHART_COLORS.chart4,
	CHART_COLORS.chart5,
];

/** Maps a 0–10 score to a chart color. */
export function scoreColor(score: number): string {
	if (score < 4) return CHART_COLORS.chart5;
	if (score < 6) return CHART_COLORS.chart3;
	if (score < 8) return CHART_COLORS.chart2;
	return CHART_COLORS.chart1;
}
