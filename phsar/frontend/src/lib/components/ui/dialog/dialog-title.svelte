<script lang="ts">
	import { Dialog as DialogPrimitive } from "bits-ui";
	import { cn } from "$lib/utils.js";

	let {
		ref = $bindable(null),
		class: className,
		...restProps
	}: DialogPrimitive.TitleProps = $props();
</script>

<DialogPrimitive.Title
	bind:ref
	data-slot="dialog-title"
	// Local edit, not upstream shadcn: leading-snug and pe-6. A title that wraps (a long list
	// name) needs line spacing, and its first line would otherwise run under the ✕, which the
	// content positions over the top-right corner.
	class={cn("text-base leading-snug font-medium pe-6", className)}
	{...restProps}
/>
