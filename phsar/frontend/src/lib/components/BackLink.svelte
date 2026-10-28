<script lang="ts">
	import { ArrowLeft } from 'lucide-svelte';
	import * as cls from '$lib/styles/classes';
	import type { Snippet } from 'svelte';
	import { searchHref, type DetailHrefOptions } from '$lib/utils/navigation';
	import { hrefWithFocus } from '$lib/utils/scrollFocus';

	interface Props {
		/** Where the page was opened from: `detailOrigin(url)` on a detail page, or a
		 * list's own way back. */
		origin: DetailHrefOptions;
		/** A link sharing the row, at its right end ("To anime", "Open in search"). */
		children?: Snippet;
	}

	let { origin, children }: Props = $props();
	let { q: searchToken, from: fromParam, job: jobUuid, carousel, focus } = $derived(origin);

	// Only the targets whose page actually consumes `?focus=` get it — the pages
	// calling `consumeFocus`. Appending it elsewhere leaves a param nothing reads and
	// nothing strips; opting one of the other branches in means wrapping it here too,
	// or the page will consume something it never receives.
	const withFocus = (base: string) => hrefWithFocus(base, focus);

	let target = $derived.by(() => {
		if (fromParam === 'job' && jobUuid) return { href: `/admin/jobs/${jobUuid}`, label: 'Back to job' };
		if (fromParam === 'completion') return { href: '/admin?tab=completion', label: 'Back to completion' };
		if (fromParam === 'curation') return { href: '/admin?tab=curation', label: 'Back to curation' };
		if (fromParam === 'ratings') return { href: withFocus('/ratings'), label: 'Back to ratings' };
		if (fromParam === 'ratings-stats') return { href: '/ratings?tab=stats', label: 'Back to statistics' };
		if (fromParam === 'watchlist') return { href: withFocus('/watchlist'), label: 'Back to watchlist' };
		if (fromParam === 'home') return { href: withFocus('/'), label: 'Back to home' };
		if (fromParam === 'browse') return { href: withFocus('/browse'), label: 'Back to browse' };
		if (fromParam === 'discover') return { href: withFocus('/browse?tab=discover'), label: 'Back to discover' };
		if (fromParam === 'carousel' && carousel) {
			return { href: withFocus(`/browse/${encodeURIComponent(carousel)}`), label: 'Back to the list' };
		}
		if (fromParam === 'search-all') return { href: withFocus(searchHref('/search/all', searchToken)), label: 'Back to all results' };
		if (fromParam === 'library') return { href: '/library/add', label: 'Back to library' };
		if (searchToken || fromParam === 'search') return { href: withFocus(searchHref('/search', searchToken)), label: 'Back to search' };
		return null;
	});
</script>

<!-- The row owns the gap below a page's navigation links: its own mb-2 beats a parent's
     space-y (a zero-specificity :where()), so every page gets the same gap. -->
{#if target || children}
	<div class="flex items-center mb-2">
		{#if target}
			<a href={target.href} class={cls.pageNavLink}>
				<ArrowLeft class="size-4" /> {target.label}
			</a>
		{/if}
		{#if children}
			<div class="ml-auto">{@render children()}</div>
		{/if}
	</div>
{/if}
