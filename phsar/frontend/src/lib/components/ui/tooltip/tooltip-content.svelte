<script lang="ts">
	import { Tooltip as TooltipPrimitive } from "bits-ui";
	import { cn } from "$lib/utils.js";
	import TooltipPortal from "./tooltip-portal.svelte";
	import type { ComponentProps } from "svelte";
	import type { WithoutChildrenOrChild } from "$lib/utils.js";

	let {
		ref = $bindable(null),
		class: className,
		sideOffset = 0,
		side = "top",
		children,
		arrowClasses,
		portalProps,
		...restProps
	}: TooltipPrimitive.ContentProps & {
		arrowClasses?: string;
		portalProps?: WithoutChildrenOrChild<ComponentProps<typeof TooltipPortal>>;
	} = $props();
</script>

<TooltipPortal {...portalProps}>
	<!--
		The shadow's color-mix uses `in oklch` safely here: the second operand is
		`transparent`, not white/grey, so there is no hue-0 neutral to drag the
		primary toward red (the bug the `--tooltip-surface` token fixed by moving to
		oklab in app.css). If this ever mixes toward a light tint instead of
		transparent, switch it to `in oklab` too.
	-->
	<TooltipPrimitive.Content
		bind:ref
		data-slot="tooltip-content"
		{sideOffset}
		{side}
		class={cn(
			"data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-[state=delayed-open]:animate-in data-[state=delayed-open]:fade-in-0 data-[state=delayed-open]:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs has-data-[slot=kbd]:pr-1.5 **:data-[slot=kbd]:relative **:data-[slot=kbd]:isolate **:data-[slot=kbd]:z-50 **:data-[slot=kbd]:rounded-sm bg-[var(--tooltip-surface)] text-popover-foreground border border-primary/40 shadow-[0_6px_24px_-6px_color-mix(in_oklch,var(--primary)_55%,transparent)] z-50 w-fit max-w-xs origin-(--bits-tooltip-content-transform-origin)",
			className
		)}
		{...restProps}
	>
		{@render children?.()}
		<TooltipPrimitive.Arrow>
			{#snippet child({ props })}
				<div
					class={cn(
						"size-2.5 translate-y-[calc(-50%-2px)] rotate-45 rounded-[2px] bg-[var(--tooltip-surface)] fill-[var(--tooltip-surface)] border-r border-b border-primary/40 z-50",
						"data-[side=top]:translate-x-1/2 data-[side=top]:translate-y-[calc(-50%+2px)]",
						"data-[side=bottom]:-translate-x-1/2 data-[side=bottom]:-translate-y-[calc(-50%+1px)]",
						"data-[side=right]:translate-x-[calc(50%+2px)] data-[side=right]:translate-y-1/2",
						"data-[side=left]:-translate-y-[calc(50%-3px)]",
						arrowClasses
					)}
					{...props}
				></div>
			{/snippet}
		</TooltipPrimitive.Arrow>
	</TooltipPrimitive.Content>
</TooltipPortal>
