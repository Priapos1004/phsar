<script lang="ts">
	import { ArrowLeft } from 'lucide-svelte';
	import type { DetailOrigin } from '$lib/utils/navigation';
	import { hrefWithFocus } from '$lib/utils/scrollFocus';

	interface Props {
		searchToken: string | null;
		fromParam: DetailOrigin | null;
		/** Job uuid carried with `fromParam === 'job'` (admin came from a sweep
		 * audit) so the back button links to that specific job row. */
		jobUuid?: string | null;
		/** The list item to scroll back to — see `utils/scrollFocus`. */
		focusUuid?: string | null;
	}

	let { searchToken, fromParam, jobUuid = null, focusUuid = null }: Props = $props();

	// Only the targets whose page actually consumes `?focus=` get it — the pages
	// calling `consumeFocus`. Appending it elsewhere leaves a param nothing reads and
	// nothing strips; opting one of the other branches in means wrapping it here too,
	// or the page will consume something it never receives.
	const withFocus = (base: string) => hrefWithFocus(base, focusUuid);

	let target = $derived.by(() => {
		if (fromParam === 'job' && jobUuid) return { href: `/admin/jobs/${jobUuid}`, label: 'Back to job' };
		if (fromParam === 'completion') return { href: '/admin?tab=completion', label: 'Back to completion' };
		if (fromParam === 'curation') return { href: '/admin?tab=curation', label: 'Back to curation' };
		if (fromParam === 'ratings') return { href: withFocus('/ratings'), label: 'Back to ratings' };
		if (fromParam === 'ratings-stats') return { href: '/ratings?tab=stats', label: 'Back to statistics' };
		if (fromParam === 'watchlist') return { href: withFocus('/watchlist'), label: 'Back to watchlist' };
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
