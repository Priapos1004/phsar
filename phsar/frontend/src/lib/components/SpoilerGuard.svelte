<script lang="ts">
	import { userSettings } from '$lib/stores/userSettings';
	import type { Snippet } from 'svelte';

	interface Props {
		/** Whether this media is within the spoiler frontier (visible). */
		visible: boolean;
		/** Controls blur intensity: 'image' uses stronger blur, 'text' uses lighter blur. */
		mode?: 'image' | 'text';
		children: Snippet;
	}

	let { visible, mode = 'image', children }: Props = $props();
	let revealed = $state(false);

	let spoilerLevel = $derived($userSettings?.spoiler_level ?? 'off');
	// Blur when: spoiler is on, media is not visible, and user hasn't clicked to reveal.
	// "hide" mode on detail pages falls back to blur (consumer still renders the component).
	let shouldBlur = $derived(
		spoilerLevel !== 'off' && !visible && !revealed
	);

	function reveal(e: MouseEvent | KeyboardEvent) {
		if (shouldBlur) {
			// Prevent parent links from navigating when revealing
			e.preventDefault();
			e.stopPropagation();
			// Remove focus from the reveal button before Svelte swaps the DOM,
			// otherwise the browser may transfer a selection highlight to the
			// newly rendered children.
			if (e.currentTarget instanceof HTMLElement) e.currentTarget.blur();
			window.getSelection()?.removeAllRanges();
			revealed = true;
		}
	}
</script>

{#if shouldBlur}
	<div
		class="relative cursor-pointer select-none outline-none"
		onclick={reveal}
		onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') reveal(e); }}
		role="button"
		tabindex={0}
		aria-label="Click to reveal spoiler"
	>
		<div class="{mode === 'image' ? 'blur-lg' : 'blur-sm'}">
			{@render children()}
		</div>
		<div class="absolute inset-0 flex items-center justify-center rounded-lg pointer-events-none">
			<span class="text-white/90 text-xs font-medium bg-black/50 rounded px-2 py-1">
				Click to reveal
			</span>
		</div>
	</div>
{:else}
	{@render children()}
{/if}
