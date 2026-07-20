<script lang="ts">
	// Presentational bookmark toggle used on the media + anime hero (and reusable for
	// search cards). Filled + optionally tag-colored when on the watchlist.
	import Tooltip from '$lib/components/Tooltip.svelte';
	import { Bookmark } from 'lucide-svelte';

	interface Props {
		filled: boolean;
		/** Tag color when filled; omit to fill with the theme primary (e.g. anime-level
		 *  aggregate spanning multiple tags). */
		color?: string;
		tooltip: string;
		ariaLabel: string;
		onclick: () => void;
		/** Icon size class (default size-6 for the hero; pass e.g. size-5 for cards). */
		iconClass?: string;
	}

	let { filled, color, tooltip, ariaLabel, onclick, iconClass = 'size-6' }: Props = $props();
</script>

<Tooltip text={tooltip} class="shrink-0">
	{#snippet trigger(props)}
		<button
			{...props}
			class="p-2 rounded-lg hover:bg-primary/10 transition"
			{onclick}
			aria-label={ariaLabel}
		>
			<Bookmark
				class="{iconClass} {filled ? (color ? '' : 'text-primary') : 'text-muted-foreground'}"
				style={filled && color ? `color:${color}` : ''}
				fill={filled ? 'currentColor' : 'none'}
			/>
		</button>
	{/snippet}
</Tooltip>
