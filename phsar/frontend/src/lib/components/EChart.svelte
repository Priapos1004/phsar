<script lang="ts">
	import { onMount } from 'svelte';
	import { getEcharts } from '$lib/echarts';
	import type { EChartsOption } from 'echarts';

	interface Props {
		option: EChartsOption;
		width?: string;
		height?: string;
	}

	let { option, width = '100%', height = '200px' }: Props = $props();

	let container: HTMLDivElement;
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	let chart = $state<any>(null);

	onMount(() => {
		let disposed = false;
		let observer: ResizeObserver | undefined;

		getEcharts().then((echarts) => {
			if (disposed) return;

			const instance = echarts.init(container);

			observer = new ResizeObserver(() => instance.resize());
			observer.observe(container);

			// Triggers $effect which applies the initial option
			chart = instance;
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
