<script lang="ts">
	// A carousel's see-all (docs/features/browse.md).
	import { getContext } from 'svelte';
	import { page } from '$app/state';
	import { ChevronRight } from 'lucide-svelte';
	import { ApiError } from '$lib/api';
	import PillToggle from '$lib/components/PillToggle.svelte';
	import SeeAllResults from '$lib/components/SeeAllResults.svelte';
	import {
		browseRefinements,
		filterSetGroups,
		GROUP_HEADINGS,
		isSetActive,
		NO_REFINEMENT,
		refinedSearch,
		selectInGroup,
		type Refinement,
	} from '$lib/stores/browseRefinements';
	import { browseCarousel, browseRow } from '$lib/stores/browseRows';
	import { ensureRatingCoverage } from '$lib/stores/ratingCoverage';
	import type { AnimeSearchResult, BrowseCarousel, BrowseFilterSet } from '$lib/types/api';
	import { buildDetailHref, carouselOrigin, navigateToSearch } from '$lib/utils/navigation';
	import { pinnedSeason, readsOwnData, type SortDir, type SortKey } from '$lib/utils/search';

	const GUEST_HINT = 'Guest accounts have no ratings or watchlist';

	const getUserRole = getContext<() => string | null>('userRole');
	let isGuest = $derived(getUserRole?.() === 'restricted_user');

	let key = $derived(page.params.key ?? '');
	let refinement = $derived($browseRefinements[key] ?? NO_REFINEMENT);

	let carousel = $state<BrowseCarousel | null>(null);
	let rows = $state<AnimeSearchResult[] | null>(null);
	let notice = $state('');

	let search = $derived(carousel ? refinedSearch(carousel, refinement, isGuest) : null);
	let groups = $derived(carousel ? filterSetGroups(carousel.filter_sets) : []);

	let request = 0;
	$effect(() => {
		void load(key, refinement);
	});

	async function load(key: string, r: Refinement) {
		const id = ++request;
		rows = null;
		notice = '';
		try {
			const c = await browseCarousel(key, r.on, r.off);
			if (id !== request) return;
			carousel = c;
			const s = refinedSearch(c, r, isGuest);
			// Guests: docs/features/browse.md#guests.
			if (isGuest && readsOwnData(s)) {
				notice = 'This list is built from your own ratings and watchlist — guest accounts have neither.';
				return;
			}
			// Unawaited: the tiers decorate tiles, so they must not hold the list back.
			if (!isGuest) void ensureRatingCoverage();
			const results = await browseRow(s, c.see_all_limit, { slot: key });
			if (id === request) rows = results;
		} catch (e) {
			if (id === request) notice = e instanceof ApiError ? e.detail : "Couldn't load this list.";
		}
	}

	function refine(next: Refinement) {
		browseRefinements.update((all) => ({ ...all, [key]: next }));
	}

	function setSort(change: { sort: SortKey; sort_dir?: SortDir }) {
		refine({ ...refinement, sort: change.sort, sort_dir: change.sort_dir });
	}

	function guestInert(set: BrowseFilterSet): boolean {
		return isGuest && readsOwnData(set.params);
	}
</script>

<svelte:head><title>{carousel?.title ?? 'Browse'} — Phsar</title></svelte:head>

<SeeAllResults
	back={{ from: carouselOrigin(carousel?.page), focus: key }}
	title={carousel?.title ?? ''}
	season={search ? pinnedSeason(search) : null}
	grain="anime"
	params={search}
	{rows}
	limit={carousel?.see_all_limit ?? 0}
	{notice}
	{isGuest}
	onSort={carousel?.sortable ? setSort : undefined}
	tileHref={(uuid) => buildDetailHref('anime', uuid, { from: 'carousel', carousel: key })}
>
	{#snippet actions()}
		<!-- The row as a search, toggles and sort included: everything editable from there. -->
		{#if search}
			<button
				type="button"
				class="group inline-flex items-center gap-0.5 px-2 text-sm font-medium text-white/70 hover:text-primary transition"
				onclick={() => navigateToSearch({ ...search, view_type: 'anime' })}
			>
				Open in search
				<ChevronRight class="size-4 transition group-hover:translate-x-0.5" />
			</button>
		{/if}
	{/snippet}
	{#if groups.length && !notice}
		<div class="flex flex-wrap items-center gap-x-5 gap-y-2">
			{#each groups as group (group[0].key)}
				{@const active = group.find((s) => isSetActive(s, refinement))?.key ?? ''}
				{@const heading = GROUP_HEADINGS[Object.keys(group[0].params)[0]]}
				{@const options = group.map((s) => {
					const inert = guestInert(s);
					return { value: s.key, label: s.label, disabled: inert, hint: inert ? GUEST_HINT : undefined };
				})}
				<!-- Tapping the lit choice clears it, in a group too. -->
				<div class="flex items-center gap-2">
					{#if group.length > 1}
						<span class="text-sm text-white/60">{heading ?? ''}</span>
					{/if}
					<PillToggle
						options={group.length > 1 ? [{ value: '', label: 'Any' }, ...options] : options}
						value={active}
						onSelect={(v) => refine(selectInGroup(group, refinement, v && v !== active ? v : null))}
						ariaLabel={heading}
					/>
				</div>
			{/each}
		</div>
	{/if}
</SeeAllResults>
