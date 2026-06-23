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
	}

	let { option, width = '100%', height = '200px', onClick }: Props = $props();

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
