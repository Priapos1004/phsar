<script lang="ts">
	import * as TooltipPrimitive from '$lib/components/ui/tooltip';
	import { cn } from '$lib/utils';
	import type { Snippet } from 'svelte';

	type Side = 'top' | 'right' | 'bottom' | 'left';

	interface Props {
		/** Tooltip text. */
		text: string;
		side?: Side;
		/** Extra classes for the default span trigger (children mode only). */
		class?: string;
		/**
		 * Simple mode — wraps this content in a `cursor-help` span trigger.
		 * Use for non-interactive labels (status dots, table cells, icons, text).
		 */
		children?: Snippet;
		/**
		 * Advanced mode — render your own trigger element and spread `props` onto
		 * it (e.g. a Button). Preferred for interactive triggers so keyboard focus
		 * (not just hover) reveals the tooltip and no element gets double-wrapped.
		 */
		trigger?: Snippet<[Record<string, unknown>]>;
	}

	let { text, side = 'top', class: className, children, trigger }: Props = $props();
</script>

<!-- Self-contained Provider so the component works anywhere (incl. isolated
     component tests) without depending on an ancestor Provider. -->
<TooltipPrimitive.Provider delayDuration={500}>
<TooltipPrimitive.Root>
	<TooltipPrimitive.Trigger>
		{#snippet child({ props })}
			{#if trigger}
				{@render trigger(props)}
			{:else}
				<span {...props} class={cn('cursor-help', className)}>{@render children?.()}</span>
			{/if}
		{/snippet}
	</TooltipPrimitive.Trigger>
	<TooltipPrimitive.Content {side}>{text}</TooltipPrimitive.Content>
</TooltipPrimitive.Root>
</TooltipPrimitive.Provider>
