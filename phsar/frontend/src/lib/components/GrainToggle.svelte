<script lang="ts">
	// The anime/media grain pill, one component so every grain switch looks the same. A
	// `PillToggle` with its options fixed.
	import PillToggle from '$lib/components/PillToggle.svelte';

	interface Props {
		grain: 'anime' | 'media';
		onSelect: (grain: 'anime' | 'media') => void;
	}

	let { grain, onSelect }: Props = $props();

	const GRAINS = [
		{ value: 'anime' as const, label: 'Anime' },
		{ value: 'media' as const, label: 'Media' },
	];
</script>

<PillToggle options={GRAINS} value={grain} {onSelect} ariaLabel="Anime or media" />
