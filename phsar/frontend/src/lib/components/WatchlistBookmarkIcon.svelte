<script lang="ts">
	// Bookmark glyph that renders per the tag colors it's given:
	//   0 colors → muted outline (not on the watchlist)
	//   1 color  → solid fill (the media's tag, or an anime under one tag)
	//   >1 color → a gradient (an anime whose media span multiple tags)
	// The gradient uses a CSS mask of the bookmark silhouette, so there are no SVG
	// gradient-id collisions across the many bookmarks on a page.
	import { Bookmark } from 'lucide-svelte';

	interface Props {
		colors: string[];
		iconClass?: string;
	}

	let { colors, iconClass = 'size-6' }: Props = $props();

	// Bookmark silhouette (lucide path), percent-encoded inside the url() so it's safe
	// unquoted. The shorthand separators OUTSIDE the url() must be literal spaces — a
	// %20 there is the literal chars %,2,0, which invalidates the whole mask declaration.
	const MASK =
		"url(data:image/svg+xml,%3Csvg%20xmlns=%27http://www.w3.org/2000/svg%27%20viewBox=%270%200%2024%2024%27%3E%3Cpath%20d=%27m19%2021-7-4-7%204V5a2%202%200%200%201%202-2h10a2%202%200%200%201%202%202z%27%20fill=%27black%27/%3E%3C/svg%3E) center/contain no-repeat";

	let gradient = $derived(`linear-gradient(135deg, ${colors.join(', ')})`);
</script>

{#if colors.length === 0}
	<Bookmark class="{iconClass} text-muted-foreground shrink-0" fill="none" />
{:else if colors.length === 1}
	<Bookmark class="{iconClass} shrink-0" style="color:{colors[0]}" fill="currentColor" role="img" aria-label="On watchlist" />
{:else}
	<span
		class="{iconClass} inline-block shrink-0"
		style="background:{gradient}; -webkit-mask:{MASK}; mask:{MASK};"
		role="img"
		aria-label="On watchlist (multiple lists)"
	></span>
{/if}
