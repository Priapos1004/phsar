<script lang="ts">
	import { page } from '$app/state';
	import type { RatingsTabKey } from './types';

	interface Tab {
		key: RatingsTabKey;
		label: string;
	}

	interface Props {
		tabs: Tab[];
		defaultTab: RatingsTabKey;
	}

	let { tabs, defaultTab }: Props = $props();

	let active = $derived.by(() => {
		const raw = page.url.searchParams.get('tab');
		const known = tabs.some((t) => t.key === raw);
		return known ? (raw as RatingsTabKey) : defaultTab;
	});

	function tabHref(key: RatingsTabKey): string {
		return `/ratings?tab=${key}`;
	}
</script>

<nav class="flex flex-wrap gap-1 border-b border-white/10" aria-label="Ratings sections">
	{#each tabs as tab}
		{@const isActive = active === tab.key}
		<a
			href={tabHref(tab.key)}
			class="px-4 py-2 -mb-px text-sm font-medium transition border-b-2 {isActive
				? 'text-primary border-primary'
				: 'text-white/60 border-transparent hover:text-white'}"
			aria-current={isActive ? 'page' : undefined}
		>
			{tab.label}
		</a>
	{/each}
</nav>
