<script lang="ts">
	// Interactive bookmark toggle used on the media + anime hero. Renders via the shared
	// WatchlistBookmarkIcon (solid / gradient / outline by the tag colors passed in).
	import Tooltip from '$lib/components/Tooltip.svelte';
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

<Tooltip text={tooltip} class="shrink-0">
	{#snippet trigger(props)}
		<button
			{...props}
			class="p-2 rounded-lg transition {disabled ? 'opacity-50 cursor-not-allowed' : 'hover:bg-primary/10'}"
			onclick={disabled ? undefined : onclick}
			{disabled}
			aria-label={ariaLabel}
		>
			<WatchlistBookmarkIcon {colors} {iconClass} />
		</button>
	{/snippet}
</Tooltip>
