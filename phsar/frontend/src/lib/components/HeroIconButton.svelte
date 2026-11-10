<script lang="ts">
	// The icon-action chrome on the anime + media heroes (watchlist bookmark, share).
	// Extracted so the padding, hover tint and inert-not-hidden wiring live in one
	// place — the hero row's actions have to stay visually aligned, and a tap-target or
	// hover change applied to only one of them is exactly how they drift apart.
	import type { Snippet } from 'svelte';
	import Tooltip from '$lib/components/Tooltip.svelte';

	interface Props {
		tooltip: string;
		ariaLabel: string;
		onclick: () => void;
		/** Visible-but-inert: the affordance shows, clicking does nothing, and its tooltip still
		 *  opens to say why (rules/frontend.md, "Tooltips"). */
		disabled?: boolean;
		icon: Snippet;
	}

	let { tooltip, ariaLabel, onclick, disabled = false, icon }: Props = $props();
</script>

<Tooltip text={tooltip} class="shrink-0">
	{#snippet trigger(props)}
		<button
			{...props}
			class="p-2 rounded-lg transition hover:bg-primary/10"
			onclick={disabled ? undefined : onclick}
			aria-disabled={disabled}
			aria-label={ariaLabel}
		>
			{@render icon()}
		</button>
	{/snippet}
</Tooltip>
