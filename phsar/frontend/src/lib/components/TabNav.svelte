<script lang="ts">
	// Generic `?tab=` section nav shared by the admin, ratings, and watchlist pages
	// (previously three byte-identical copies). The active tab reads from the URL.
	import { page } from '$app/state';

	interface Tab {
		key: string;
		label: string;
	}

	interface Props {
		tabs: Tab[];
		defaultTab: string;
		/** e.g. "/watchlist" — hrefs are `${basePath}?tab=${key}`. */
		basePath: string;
		ariaLabel: string;
	}

	let { tabs, defaultTab, basePath, ariaLabel }: Props = $props();

	let active = $derived.by(() => {
		const raw = page.url.searchParams.get('tab');
		return tabs.some((t) => t.key === raw) ? raw! : defaultTab;
	});
</script>

<nav class="flex flex-wrap gap-1 border-b border-white/10" aria-label={ariaLabel}>
	{#each tabs as tab}
		{@const isActive = active === tab.key}
		<a
			href={`${basePath}?tab=${tab.key}`}
			class="px-4 py-2 -mb-px text-sm font-medium transition border-b-2 {isActive
				? 'text-primary border-primary'
				: 'text-white/60 border-transparent hover:text-white'}"
			aria-current={isActive ? 'page' : undefined}
		>
			{tab.label}
		</a>
	{/each}
</nav>
