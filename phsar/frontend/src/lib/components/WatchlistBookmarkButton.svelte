<script lang="ts">
	// Interactive bookmark toggle used on the media + anime hero. Renders via the shared
	// WatchlistBookmarkIcon (solid / gradient / outline by the tag colors passed in).
	import HeroIconButton from '$lib/components/HeroIconButton.svelte';
	import WatchlistBookmarkIcon from '$lib/components/WatchlistBookmarkIcon.svelte';

	interface Props {
		/** Tag colors: [] = not on the list; one = solid; several = gradient. */
		colors: string[];
		tooltip: string;
		ariaLabel: string;
		onclick: () => void;
		iconClass?: string;
		/** Render visible-but-inert (restricted/guest users): the affordance shows so
		 *  they "see what's available", but clicking does nothing. */
		disabled?: boolean;
	}

	let { colors, tooltip, ariaLabel, onclick, iconClass = 'size-6', disabled = false }: Props = $props();
</script>

<HeroIconButton {tooltip} {ariaLabel} {onclick} {disabled}>
	{#snippet icon()}
		<WatchlistBookmarkIcon {colors} {iconClass} />
	{/snippet}
</HeroIconButton>
