/**
 * Chart color constants mirroring --color-chart-* from app.css.
 * ECharts requires raw color strings (not CSS var() references),
 * so these are maintained as JS constants alongside the CSS definitions.
 */
import { getActiveTheme } from '$lib/themes';

export const CHART_COLORS = {
	chart1: 'oklch(0.558 0.288 302.321)', // primary purple
	chart2: 'oklch(0.696 0.17 162.48)',    // green
	chart3: 'oklch(0.769 0.188 70.08)',    // yellow
	chart4: 'oklch(0.627 0.265 303.9)',    // light purple
	chart5: 'oklch(0.645 0.246 16.439)',   // red
	teal: 'oklch(0.65 0.17 195)',          // red-theme replacement for chart5
} as const;

/** Maps a 0–10 score to a chart color. */
export function scoreColor(score: number): string {
	if (score < 4) return CHART_COLORS.chart5;
	if (score < 6) return CHART_COLORS.chart3;
	if (score < 8) return CHART_COLORS.chart2;
	return CHART_COLORS.chart1;
}

/** Canonical display order for relation types. */
export const RELATION_TYPE_ORDER = ['main', 'side_story', 'summary', 'crossover'] as const;

/** Maps relation types to chart colors for visual grouping. */
export const RELATION_TYPE_COLORS: Record<string, string> = {
	main: CHART_COLORS.chart1,
	side_story: CHART_COLORS.chart5,
	summary: CHART_COLORS.chart2,
	crossover: CHART_COLORS.chart3,
};

/** User-friendly display labels for relation types. */
export const RELATION_TYPE_LABELS: Record<string, string> = {
	main: 'Main Story',
	side_story: 'Side Story',
	summary: 'Summary',
	crossover: 'Crossover',
};

/**
 * Theme-aware chart colors: reads --color-chart-1 and --color-chart-4 from
 * CSS custom properties so they follow the active theme. Falls back to
 * static constants for SSR or pre-hydration.
 *
 * Per-theme palettes swap out static colors that would clash with the
 * theme's primary hue (e.g. red theme replaces the static red with teal).
 */
function cssVar(name: string, fallback: string): string {
	if (typeof document === 'undefined') return fallback;
	const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
	return value || fallback;
}

/**
 * Returns 5 visually distinct colors ordered so that the two same-hue
 * theme colors (primary at 0, ring at 4) are as far apart as possible.
 * Most attributes have ≤4 options, so they never hit both.
 */
export function getThemedChartColorPalette(): string[] {
	const c1 = cssVar('--color-chart-1', CHART_COLORS.chart1);
	const c4 = cssVar('--color-chart-4', CHART_COLORS.chart4);

	switch (getActiveTheme()) {
		case 'red':
			return [c1, CHART_COLORS.chart2, CHART_COLORS.chart3, CHART_COLORS.teal, c4];
		case 'green':
			// Swap static green (chart2) → default purple to avoid clash
			return [c1, CHART_COLORS.chart1, CHART_COLORS.chart3, CHART_COLORS.chart5, c4];
		default: // blue + default have no clashes with the static palette
			return [c1, CHART_COLORS.chart2, CHART_COLORS.chart3, CHART_COLORS.chart5, c4];
	}
}
