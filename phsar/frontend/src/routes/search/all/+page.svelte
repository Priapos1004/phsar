<script lang="ts">
	// A search past the search page's `SEARCH_LIMIT`: the same token, up to the endpoint's
	// own limit, as poster tiles. A sort change mints a new token and stays here.
	import { getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { api } from '$lib/api';
	import Notice from '$lib/components/Notice.svelte';
	import SeeAllResults from '$lib/components/SeeAllResults.svelte';
	import { ensureRatingCoverage } from '$lib/stores/ratingCoverage';
	import { userSettings } from '$lib/stores/userSettings';
	import type { AnimeSearchResult, MediaSearchResult } from '$lib/types/api';
	import * as cls from '$lib/styles/classes';
	import { buildDetailHref, navigateToSearch } from '$lib/utils/navigation';
	import {
		GUEST_STRIPPED_NOTICE,
		SEARCH_MODE_LABELS,
		SEE_ALL_LIMIT,
		fetchAnimeSearchResults,
		fetchSearchResults,
		filterChips,
		omitKeys,
		stripForGuest,
		type MediaSearchFilters,
		type SortDir,
		type SortKey,
		type ViewType,
	} from '$lib/utils/search';


	const getUserRole = getContext<() => string | null>('userRole');
	let isGuest = $derived(getUserRole?.() === 'restricted_user');
	let defaultView = $derived($userSettings?.default_search_view ?? 'anime');

	// A derived, as on the search page: stripping `?focus=` after a return re-derives the
	// same token, so the load below doesn't run again and collapse the restored list.
	let token = $derived(page.url.searchParams.get('q'));
	let params = $state<MediaSearchFilters | null>(null);
	let rows = $state<(AnimeSearchResult | MediaSearchResult)[] | null>(null);
	let notice = $state('');
	let strippedForGuest = $state(false);
	let grain = $derived<ViewType>(params?.view_type ?? defaultView);
	let query = $derived(params?.query?.trim() ?? '');
	let chips = $derived(params ? filterChips(params, grain) : []);

	let request = 0;
	$effect(() => {
		if (token) void load(token);
		else void goto('/search', { replaceState: true });
	});

	async function load(token: string) {
		const id = ++request;
		rows = null;
		notice = '';
		try {
			const parsed = await api.post<MediaSearchFilters>('/filters/verify-token', { token });
			if (id !== request) return;
			const stripped = isGuest ? stripForGuest(parsed) : { params: parsed, stripped: false };
			strippedForGuest = stripped.stripped;
			params = stripped.params;
			if (grain === 'anime' && !isGuest) void ensureRatingCoverage();
			const results = grain === 'anime'
				? await fetchAnimeSearchResults(params, SEE_ALL_LIMIT)
				: await fetchSearchResults(params, SEE_ALL_LIMIT);
			if (id === request) rows = results;
		} catch (err) {
			if (id === request) notice = err instanceof Error ? err.message : 'An unexpected error occurred';
		}
	}

	function setSort(change: { sort: SortKey; sort_dir?: SortDir }) {
		if (!params) return;
		params = { ...omitKeys(params, ['sort', 'sort_dir']), ...change, view_type: grain };
		void navigateToSearch(params, '/search/all');
	}
</script>

<svelte:head><title>All results — Phsar</title></svelte:head>

<SeeAllResults
	back={{ q: token }}
	title={query ? `All results for “${query}”` : 'All results'}
	{grain}
	{params}
	{rows}
	limit={SEE_ALL_LIMIT}
	{notice}
	{isGuest}
	onSort={setSort}
	tileHref={(uuid) => buildDetailHref(grain, uuid, { from: 'search-all', q: token })}
>
	{#if strippedForGuest}
		<Notice>{GUEST_STRIPPED_NOTICE}</Notice>
	{/if}
	<!-- What the search filters by, to read rather than to change: the chips are /search's
	     own labels without their ×, and changing them is the search page's job (the back
	     link). The mode only means something with a query; the count already names the view. -->
	{#if params && (query || chips.length)}
		<div class="{cls.cardGlass} space-y-2 rounded-xl border border-border px-4 py-3">
			{#if query}
				<p class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
					{SEARCH_MODE_LABELS[params.search_type]} search
				</p>
			{/if}
			{#if chips.length}
				<div class="flex flex-wrap gap-1.5">
					{#each chips as chip (chip.id)}
						<span class="rounded-2xl border border-primary/40 bg-primary/10 px-3 py-0.5 text-sm font-medium text-primary">{#if chip.name}<span class="font-bold text-card-foreground/70">{chip.name}</span>{/if} {chip.value}</span>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</SeeAllResults>
