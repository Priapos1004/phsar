<script lang="ts">
	import { onMount } from 'svelte';
	import { getEcharts } from '$lib/echarts';
	import type { EChartsOption } from 'echarts';

	interface Props {
		option: EChartsOption;
		width?: string;
		height?: string;
		/** Optional click handler — receives the ECharts click event params (e.g.
		 * `seriesType`, `dataIndex`) so callers can map a point back to its datum. */
		onClick?: (params: unknown) => void;
		/** Optional plot-area click — fires when the user clicks anywhere inside the
		 * grid, not only on a data item (which is all `onClick` catches). Receives the
		 * clicked point as `[xValue, yValue]` in the primary grid's DATA coordinates, so
		 * the caller stays in data terms (e.g. snap x to the nearest category) and never
		 * touches zrender / convertFromPixel. Single-grid charts only. */
		onGridClick?: (coord: [number, number]) => void;
		/** Fires once the canvas actually holds its finished pixels. There's no
		 * DOM-observable moment for that — the first setOption waits on an async
		 * ResizeObserver measurement (see below) and then animates — so a consumer needing
		 * painted pixels (the share-card PNG capture) can't just wait a frame. Backed by
		 * ECharts' own `finished` event, so it stays truthful whether the chart animates
		 * or not. */
		onReady?: () => void;
	}

	let { option, width = '100%', height = '200px', onClick, onGridClick, onReady }: Props = $props();

	let container: HTMLDivElement;
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	let chart = $state<any>(null);

	onMount(() => {
		let disposed = false;
		let observer: ResizeObserver | undefined;

		getEcharts().then((echarts) => {
			if (disposed) return;

			const instance = echarts.init(container);

			// Read `onClick` live so a reactive change is honoured without re-init.
			instance.on('click', (params: unknown) => onClick?.(params));
			// `finished` re-fires on every later render; latch so consumers see one signal.
			// Registered here (not in the option $effect) so the callback prop stays out of
			// that effect's dependency set — an inline arrow would otherwise re-trigger a
			// full notMerge setOption on every parent update.
			let notified = false;
			instance.on('finished', () => {
				if (notified) return;
				notified = true;
				onReady?.();
			});
			// Plot-area clicks need zrender (ECharts' own 'click' only fires on data
			// items). Wire it only when a consumer wants it, so other charts don't pay
			// the containPixel/convertFromPixel cost on every click. Hand back DATA
			// coordinates so the ECharts-internals stay inside the wrapper.
			if (onGridClick) {
				instance.getZr().on('click', (event: { offsetX: number; offsetY: number }) => {
					const point = [event.offsetX, event.offsetY];
					if (!instance.containPixel('grid', point)) return;
					onGridClick(instance.convertFromPixel({ gridIndex: 0 }, point) as [number, number]);
				});
			}

			// ResizeObserver fires an initial callback right after observe(). Hold the
			// first setOption (and thus the entrance animation) until then: resize to the
			// real measured size FIRST, then expose `chart` so the $effect applies the
			// option and the grow-in plays at the correct size — uninterrupted by that
			// initial resize (which otherwise snaps a mid-flight animation to its end).
			let measured = false;
			observer = new ResizeObserver(() => {
				instance.resize();
				// Wait for a non-zero box before the first setOption, so a chart mounted
				// inside a hidden container still plays its entrance animation when shown
				// (rather than snapping at 0×0), not just when laid out at mount.
				if (!measured && container.clientWidth > 0) {
					measured = true;
					chart = instance; // → $effect applies the option → entrance animation
				}
			});
			observer.observe(container);
		});

		return () => {
			disposed = true;
			observer?.disconnect();
			chart?.dispose();
			chart = null;
		};
	});

	$effect(() => {
		if (chart) chart.setOption(option, true);
	});
</script>

<div bind:this={container} style="width: {width}; height: {height};"></div>
