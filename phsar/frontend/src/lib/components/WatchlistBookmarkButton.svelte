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
	}

	let { colors, tooltip, ariaLabel, onclick, iconClass = 'size-6' }: Props = $props();
</script>

<Tooltip text={tooltip} class="shrink-0">
	{#snippet trigger(props)}
		<button
			{...props}
			class="p-2 rounded-lg hover:bg-primary/10 transition"
			{onclick}
			aria-label={ariaLabel}
		>
			<WatchlistBookmarkIcon {colors} {iconClass} />
		</button>
	{/snippet}
</Tooltip>
