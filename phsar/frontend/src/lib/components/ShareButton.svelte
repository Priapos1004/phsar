<script lang="ts">
	// Share action on the media + anime hero — the glyph half of HeroIconButton, mirroring
	// WatchlistBookmarkButton beside it.
	import HeroIconButton from '$lib/components/HeroIconButton.svelte';
	import { Share2 } from 'lucide-svelte';

	interface Props {
		tooltip: string;
		ariaLabel: string;
		onclick: () => void;
	}

	let { tooltip, ariaLabel, onclick }: Props = $props();
</script>

<HeroIconButton {tooltip} {ariaLabel} {onclick}>
	{#snippet icon()}
		<Share2 class="size-6 text-primary" />
	{/snippet}
</HeroIconButton>
