<script lang="ts">
	import { ArrowLeft } from 'lucide-svelte';
	import type { DetailHrefOptions } from '$lib/utils/navigation';
	import { hrefWithFocus } from '$lib/utils/scrollFocus';

	interface Props {
		/** Where the page was opened from: `detailOrigin(url)` on a detail page, or a
		 * list's own way back. */
		origin: DetailHrefOptions;
	}

	let { origin }: Props = $props();
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
		if (fromParam === 'browse') return { href: withFocus('/browse'), label: 'Back to browse' };
		if (fromParam === 'carousel' && carousel) {
			return { href: withFocus(`/browse/${encodeURIComponent(carousel)}`), label: 'Back to the list' };
		}
		if (fromParam === 'search-all' && searchToken) {
			return { href: withFocus(`/search/all?q=${encodeURIComponent(searchToken)}`), label: 'Back to all results' };
		}
		if (fromParam === 'library') return { href: '/library/add', label: 'Back to library' };
		if (searchToken) return { href: withFocus(`/search?q=${encodeURIComponent(searchToken)}`), label: 'Back to search' };
		return null;
	});
</script>

{#if target}
	<a
		href={target.href}
		class="inline-flex items-center gap-1.5 text-sm text-white/70 hover:text-white transition mb-2"
	>
		<ArrowLeft class="size-4" /> {target.label}
	</a>
{/if}
