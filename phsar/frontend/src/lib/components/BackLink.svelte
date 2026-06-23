<script lang="ts">
	import { ArrowLeft } from 'lucide-svelte';
	import type { DetailOrigin } from '$lib/utils/navigation';

	interface Props {
		searchToken: string | null;
		fromParam: DetailOrigin | null;
		/** Job uuid carried with `fromParam === 'job'` (admin came from a sweep
		 * audit) so the back button links to that specific job row. */
		jobUuid?: string | null;
	}

	let { searchToken, fromParam, jobUuid = null }: Props = $props();

	let target = $derived.by(() => {
		if (fromParam === 'job' && jobUuid) return { href: `/admin/jobs/${jobUuid}`, label: 'Back to job' };
		if (fromParam === 'completion') return { href: '/admin?tab=completion', label: 'Back to completion' };
		if (fromParam === 'curation') return { href: '/admin?tab=curation', label: 'Back to curation' };
		if (fromParam === 'ratings') return { href: '/ratings', label: 'Back to ratings' };
		if (fromParam === 'library') return { href: '/library/add', label: 'Back to library' };
		if (searchToken) return { href: `/search?q=${encodeURIComponent(searchToken)}`, label: 'Back to search' };
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
