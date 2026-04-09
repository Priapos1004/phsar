/**
 * Shared ECharts instance — uses the pre-built bundle to avoid
 * tslib ESM resolution issues with Vite's browser condition.
 * Lazily imported in onMount (browser-only) to prevent SSR crashes.
 */

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let instance: any = null;

export async function getEcharts() {
	if (instance) return instance;
	// @ts-expect-error — pre-built dist bundle has no .d.ts, but works at runtime
	instance = await import('echarts/dist/echarts.esm.js');
	return instance;
}
