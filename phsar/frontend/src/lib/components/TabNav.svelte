<script lang="ts" module>
	/** The `?tab=` the URL names, or `fallback` for a missing or unknown one — so a stale
	 *  bookmark or a retired key never lands on a blank page. */
	export function activeTab<K extends string>(url: URL, tabs: readonly { key: K }[], fallback: K): K {
		const raw = url.searchParams.get('tab');
		return tabs.find((t) => t.key === raw)?.key ?? fallback;
	}
</script>

<script lang="ts">
	// Generic `?tab=` section nav. The page passes the tab it shows (`activeTab`), so the
	// highlighted tab and the panel shown never disagree.
	interface Tab {
		key: string;
		label: string;
	}

	interface Props {
		tabs: Tab[];
		active: string;
		/** e.g. "/watchlist" — hrefs are `${basePath}?tab=${key}`. */
		basePath: string;
		ariaLabel: string;
	}

	let { tabs, active, basePath, ariaLabel }: Props = $props();
</script>

<!-- Tabs pad tighter below 360px, so a wrapping tab row (the admin's) takes no more lines at
     320 than at 360. -->
<nav class="flex flex-wrap gap-1 border-b border-white/10" aria-label={ariaLabel}>
	{#each tabs as tab}
		{@const isActive = active === tab.key}
		<a
			href={`${basePath}?tab=${tab.key}`}
			class="px-4 max-xs:px-3 py-2 -mb-px text-sm font-medium transition border-b-2 {isActive
				? 'text-primary border-primary'
				: 'text-white/60 border-transparent hover:text-white'}"
			aria-current={isActive ? 'page' : undefined}
		>
			{tab.label}
		</a>
	{/each}
</nav>
