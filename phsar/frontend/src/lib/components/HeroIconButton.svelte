<script lang="ts">
	// The icon-action chrome on the anime + media heroes (watchlist bookmark, share).
	// Extracted so the padding, hover tint and disabled-not-hidden wiring live in one
	// place — the hero row's actions have to stay visually aligned, and a tap-target or
	// hover change applied to only one of them is exactly how they drift apart.
	import type { Snippet } from 'svelte';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import * as cls from '$lib/styles/classes';

	interface Props {
		tooltip: string;
		ariaLabel: string;
		onclick: () => void;
		/** Visible-but-inert: the affordance shows, clicking does nothing. */
		disabled?: boolean;
		/** The glyph. Receives `disabled` so an icon can dim itself. */
		icon: Snippet<[boolean]>;
	}

	let { tooltip, ariaLabel, onclick, disabled = false, icon }: Props = $props();
</script>

<Tooltip text={tooltip} class="shrink-0">
	{#snippet trigger(props)}
		<button
			{...props}
			class="{cls.heroIconButton} {disabled ? cls.heroIconButtonDisabled : cls.heroIconButtonEnabled}"
			onclick={disabled ? undefined : onclick}
			{disabled}
			aria-label={ariaLabel}
		>
			{@render icon(disabled)}
		</button>
	{/snippet}
</Tooltip>
