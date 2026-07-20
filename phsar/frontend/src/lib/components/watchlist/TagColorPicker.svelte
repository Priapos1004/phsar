<script module lang="ts">
	import { buildColorWheel } from '$lib/utils/color';

	// Deterministic + static, so build the wheel once for every picker instance.
	const WHEEL = buildColorWheel();
	// Pointy-top hexagon; rows overlap vertically (-mt) and auto-offset (different counts) to tessellate.
	const HEX_CLIP = 'polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)';
</script>

<script lang="ts">
	import { Check, Plus } from 'lucide-svelte';
	import * as Dialog from '$lib/components/ui/dialog';
	import { Button } from '$lib/components/ui/button';
	import { Input } from '$lib/components/ui/input';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import { normalizeHex, contrastText } from '$lib/utils/color';
	import { RESERVED_DEFAULT_TAG_COLOR } from '$lib/utils/watchlist';

	interface Props {
		value: string;
	}

	let { value = $bindable() }: Props = $props();

	let open = $state(false);
	// The in-dialog draft (may be mid-typing / invalid); committed to `value` only on Apply.
	let draftText = $state(value);
	let norm = $derived(normalizeHex(draftText));
	let reserved = $derived(norm === RESERVED_DEFAULT_TAG_COLOR);

	function openPicker() {
		draftText = value;
		open = true;
	}

	function apply() {
		if (norm && !reserved) {
			value = norm;
			open = false;
		}
	}
</script>

<!-- Trigger: the current color as a circle with a contrast-safe plus, opening the picker.
     On hover it cycles hue through the spectrum (see the style block below). Advanced Tooltip
     mode so the button IS the trigger (no span wrapper): the tooltip anchors above it and the
     hover animation + keyboard focus work directly on the button. -->
<Tooltip text="Choose a color" contentClass="whitespace-nowrap">
	{#snippet trigger(props)}
		<button
			{...props}
			type="button"
			class="color-trigger relative size-8 rounded-full border border-border shadow-sm shrink-0"
			style="background:{value}"
			aria-label="Choose a color"
			onclick={openPicker}
		>
			<span class="color-trigger-fill absolute inset-0 rounded-full"></span>
			<Plus class="absolute inset-0 m-auto size-4 z-10" style="color:{contrastText(value)}" />
		</button>
	{/snippet}
</Tooltip>

<Dialog.Root {open} onOpenChange={(o) => (open = o)}>
	<Dialog.Content class="sm:max-w-xs">
		<Dialog.Header>
			<Dialog.Title>Choose a color</Dialog.Title>
		</Dialog.Header>

		<div class="flex flex-col items-center py-1">
			{#each WHEEL as row, ri (ri)}
				<div class="flex {ri > 0 ? '-mt-2' : ''}">
					{#each row as cell (cell.key)}
						<button
							type="button"
							class="relative flex h-8 w-7 items-center justify-center transition-transform hover:scale-110 hover:z-10 {norm === cell.hex ? 'scale-110 z-10' : ''}"
							style="background:{cell.hex}; clip-path:{HEX_CLIP};"
							aria-label={`Color ${cell.hex}`}
							onclick={() => (draftText = cell.hex)}
						>
							{#if norm === cell.hex}
								<Check class="size-3.5" style="color:{contrastText(cell.hex)}" />
							{/if}
						</button>
					{/each}
				</div>
			{/each}
		</div>

		<div class="flex items-center gap-2">
			<span class="size-8 rounded-full border border-border shrink-0" style="background:{norm ?? 'transparent'}"></span>
			<Input bind:value={draftText} maxlength={7} spellcheck={false} placeholder="#rrggbb" class="font-mono bg-card" />
		</div>
		{#if reserved}
			<p class="text-xs text-destructive">That orange is reserved for the default “Watchlist” list.</p>
		{:else if draftText && !norm}
			<p class="text-xs text-muted-foreground">Enter a hex color like #3b82f6.</p>
		{/if}

		<Dialog.Footer>
			<Button variant="secondary" onclick={() => (open = false)}>Cancel</Button>
			<Button onclick={apply} disabled={!norm || reserved}>Apply</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>

<style>
	/* Hover: a dedicated overlay layer fades in and cycles its gradient hue IN PLACE via an
	   animated custom property — paint-only (no filter / transform / overflow-clip), so nothing
	   re-lays-out. The plus is absolutely centered on its own layer (z-10), fully decoupled from
	   the animation, so it can't shift. Base-color-independent → create + edit animate identically. */
	@property --color-trigger-hue {
		syntax: '<angle>';
		initial-value: 0deg;
		inherits: false;
	}
	.color-trigger-fill {
		background: linear-gradient(
			135deg,
			hsl(var(--color-trigger-hue) 90% 60%),
			hsl(calc(var(--color-trigger-hue) + 140deg) 90% 60%)
		);
		opacity: 0;
		transition: opacity 0.15s ease;
		pointer-events: none;
		will-change: opacity;
	}
	.color-trigger:hover .color-trigger-fill {
		opacity: 1;
		animation: color-trigger-hue 3s linear infinite;
	}
	/* Safari: pin the icon on its own GPU layer so it isn't re-rastered (and subpixel-jittered)
	   together with the animating fill layer. */
	.color-trigger :global(svg) {
		transform: translateZ(0);
	}
	@keyframes color-trigger-hue {
		to {
			--color-trigger-hue: 360deg;
		}
	}
</style>
