<script lang="ts">
	// A sideways row with paging arrows. A mouse wheel without a trackpad cannot scroll a row
	// sideways, so every one carries arrows; a touch screen swipes instead (`pointer-coarse`).
	//
	// `class` styles the track — the flex row holding the tiles, gap and padding included.
	//
	// A tile's ring, outline or hover scale draws outside it and the scroller clips every side,
	// so the track pads it and the scroller cancels that sideways (`-mx-1`, `scroll-px-1` for snapping).
	import type { Snippet } from 'svelte';
	import { ChevronLeft, ChevronRight } from 'lucide-svelte';
	import { cn } from '$lib/utils';

	const ARROW =
		'absolute top-[40%] -translate-y-1/2 z-10 flex size-9 items-center justify-center rounded-full bg-black/60 text-white backdrop-blur hover:bg-black/80 transition pointer-coarse:hidden';

	interface Props {
		class?: string;
		/** The scrolling element, for a caller that positions the row itself. */
		scroller?: HTMLDivElement;
		children: Snippet;
	}

	let { class: trackClass = '', scroller = $bindable(), children }: Props = $props();

	let track = $state<HTMLDivElement>();
	let atStart = $state(true);
	let atEnd = $state(true);

	function updateArrows() {
		if (!scroller) return;
		atStart = scroller.scrollLeft <= 1;
		atEnd = scroller.scrollLeft + scroller.clientWidth >= scroller.scrollWidth - 1;
	}

	// The scroller resizes with the page, the track with its tiles — content arriving or
	// changing never touches the scroller's own box. A ResizeObserver reports as it starts
	// observing, which is the first measurement.
	$effect(() => {
		if (!scroller || !track || typeof ResizeObserver === 'undefined') return;
		const observer = new ResizeObserver(updateArrows);
		observer.observe(scroller);
		observer.observe(track);
		return () => observer.disconnect();
	});

	function page(direction: 1 | -1) {
		scroller?.scrollBy({ left: direction * scroller.clientWidth * 0.9, behavior: 'smooth' });
	}
</script>

<div class="relative">
	<div bind:this={scroller} onscroll={updateArrows} class="-mx-1 overflow-x-auto snap-x snap-mandatory scroll-px-1 no-scrollbar">
		<div bind:this={track} class={cn('flex w-max px-1 pt-1 pb-2', trackClass)}>
			{@render children()}
		</div>
	</div>
	{#if !atStart}
		<button type="button" aria-label="Scroll left" class="{ARROW} left-1" onclick={() => page(-1)}>
			<ChevronLeft class="size-5" />
		</button>
	{/if}
	{#if !atEnd}
		<button type="button" aria-label="Scroll right" class="{ARROW} right-1" onclick={() => page(1)}>
			<ChevronRight class="size-5" />
		</button>
	{/if}
</div>
