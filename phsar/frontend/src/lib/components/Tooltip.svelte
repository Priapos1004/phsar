<script lang="ts">
	import * as TooltipPrimitive from '$lib/components/ui/tooltip';
	import { cn } from '$lib/utils';
	import type { Snippet } from 'svelte';

	type Side = 'top' | 'right' | 'bottom' | 'left';

	interface Props {
		/** Tooltip text. */
		text?: string;
		/** Markup in place of `text`, for a tooltip that needs it (a key's terms in bold). */
		content?: Snippet;
		side?: Side;
		/** Extra classes for the default span trigger (children mode only). */
		class?: string;
		/** Extra classes for the tooltip content bubble (e.g. `whitespace-nowrap` for a
		 *  short label that shouldn't wrap when placed near a screen edge). */
		contentClass?: string;
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

	let { text, content, side = 'top', class: className, contentClass, children, trigger }: Props = $props();

	let open = $state(false);

	// Touch never hovers, so a tap on a children-mode trigger toggles the tooltip instead. On
	// pointerup, which a scroll cancels and iOS sends even where it would send no click; `open`
	// there is still the pre-tap state, since bits-ui ignores the focus a tap brings until the
	// pointer lifts. Trigger mode stays hover and focus only (rules/frontend.md, "Tooltips").
	function toggleOnTap(e: PointerEvent) {
		if (e.pointerType !== 'mouse') open = !open;
	}

	// A lifted finger leaves its element, and bits-ui's hover tracking (`SafePolygon`) reads that
	// as the pointer heading away from the bubble, closing it a frame after the tap opened it.
	// Stopped in the capture phase, before that tracking or bits-ui's own leave handler hears it.
	// A pen counts as a finger; a hovering one just keeps the bubble until a tap elsewhere.
	function keepOnLift(e: PointerEvent) {
		if (e.pointerType !== 'mouse') e.stopPropagation();
	}
</script>

<!-- Self-contained Provider so the component works anywhere (incl. isolated
     component tests) without depending on an ancestor Provider.

     Consequence for tests: one that mocks svelte's setContext/getContext has to
     delegate unknown keys to the real implementation, or this Provider's own
     context breaks and every tooltip in the tree fails to mount. See
     tests/media-detail.test.ts. -->
<TooltipPrimitive.Provider delayDuration={500}>
<!-- disableCloseOnTriggerClick hands a children-mode trigger's taps to toggleOnTap alone:
     without it bits-ui closes on the same press that opens. -->
<TooltipPrimitive.Root bind:open disableCloseOnTriggerClick={!trigger}>
	<TooltipPrimitive.Trigger>
		{#snippet child({ props })}
			{#if trigger}
				{@render trigger(props)}
			{:else}
				<!-- Capture phase, so bits-ui's own handlers in `props` stay. No preventDefault:
				     a tooltip inside a link still navigates. -->
				<span
					{...props}
					class={cn('cursor-help', className)}
					onpointerupcapture={toggleOnTap}
					onpointerleavecapture={keepOnLift}
				>{@render children?.()}</span>
			{/if}
		{/snippet}
	</TooltipPrimitive.Trigger>
	<TooltipPrimitive.Content {side} class={contentClass}>{#if content}{@render content()}{:else}{text}{/if}</TooltipPrimitive.Content>
</TooltipPrimitive.Root>
</TooltipPrimitive.Provider>
