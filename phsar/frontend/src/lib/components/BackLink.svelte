<script lang="ts">
	import { ArrowLeft } from 'lucide-svelte';

	interface Props {
		searchToken: string | null;
		fromParam: 'library' | null;
	}

	let { searchToken, fromParam }: Props = $props();

	let target = $derived.by(() => {
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
