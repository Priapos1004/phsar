<script lang="ts">
	// Share action on the media + anime hero — the glyph half of HeroIconButton, mirroring
	// WatchlistBookmarkButton beside it.
	import HeroIconButton from '$lib/components/HeroIconButton.svelte';
	import { Share2 } from 'lucide-svelte';

	interface Props {
		tooltip: string;
		ariaLabel: string;
		onclick: () => void;
		disabled?: boolean;
	}

	let { tooltip, ariaLabel, onclick, disabled = false }: Props = $props();
</script>

<HeroIconButton {tooltip} {ariaLabel} {onclick} {disabled}>
	{#snippet icon(isDisabled)}
		<Share2 class="size-6 {isDisabled ? 'text-muted-foreground' : 'text-primary'}" />
	{/snippet}
</HeroIconButton>
