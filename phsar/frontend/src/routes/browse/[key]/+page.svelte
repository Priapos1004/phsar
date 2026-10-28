<script lang="ts">
	// A carousel's see-all (docs/features/browse.md).
	import { getContext } from 'svelte';
	import { page } from '$app/state';
	import { ArrowRight, RotateCcw } from 'lucide-svelte';
	import * as cls from '$lib/styles/classes';
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
		type Step,
	} from '$lib/stores/browseRefinements';
	import { browseCarousel, carouselResults, knownStep, refinedFromDefaults } from '$lib/stores/browseRows';
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
	// What the list shows: the viewer's refinement, widened where its row is, so the toggles
	// light the Top step actually applied — the step Reset comes back to. Null until the first
	// list decides it, so the toggles never show a step it is about to leave.
	let shown = $state<Refinement | null>(null);

	let search = $derived(carousel && shown ? refinedSearch(carousel, shown, isGuest) : null);
	let groups = $derived(carousel ? filterSetGroups(carousel.filter_sets) : []);

	let request = 0;
	$effect(() => {
		void load(key, refinement);
	});

	function show(at: Step) {
		carousel = at.carousel;
		shown = at.refinement;
	}

	async function load(key: string, asked: Refinement) {
		const id = ++request;
		rows = null;
		notice = '';
		try {
			const c = await browseCarousel(key, asked.on, asked.off);
			if (id !== request) return;
			// Guests: docs/features/browse.md#guests.
			if (isGuest && readsOwnData(refinedSearch(c, asked, isGuest))) {
				show({ carousel: c, refinement: asked });
				notice = 'This list is built from your own ratings and watchlist — guest accounts have neither.';
				return;
			}
			// Shown at once where the step is known; a list still to be counted keeps the
			// toggles where they were until it decides.
			const known = knownStep(c, asked);
			if (known) show(known);
			else carousel = c;
			// Unawaited: the tiers decorate tiles, so they must not hold the list back.
			if (!isGuest) void ensureRatingCoverage();
			const listed = await carouselResults(c, asked, isGuest, c.see_all_limit, { slot: key });
			if (id !== request) return;
			show(listed);
			rows = listed.results;
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

	// Reset shows while the list differs from what it returns to.
	let refined = $derived(carousel && shown ? refinedFromDefaults(carousel, shown) : false);

	function reset() {
		browseRefinements.update(({ [key]: _, ...rest }) => rest);
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
			<button type="button" class={cls.pageNavLink} onclick={() => navigateToSearch({ ...search, view_type: 'anime' })}>
				Open in search <ArrowRight class="size-4" />
			</button>
		{/if}
	{/snippet}
	{#if shown && (groups.length || refined) && !notice}
		<!-- From sm a full line's groups reach both edges, its last group under "Open in search". -->
		<div class="flex flex-wrap items-center gap-x-5 gap-y-2 sm:justify-between">
			{#each groups as group (group[0].key)}
				{@const active = group.find((s) => isSetActive(s, shown!))?.key ?? ''}
				{@const heading = GROUP_HEADINGS[Object.keys(group[0].params)[0]]}
				{@const multi = group.length > 1}
				{@const options = group.map((s) => {
					const inert = guestInert(s);
					return { value: s.key, label: s.label, disabled: inert, hint: inert ? GUEST_HINT : undefined };
				})}
				<!-- Tapping the lit choice clears it, in a group too. On a phone a group stacks
				     its label over a full-width toggle: beside the label, Top's percent scale
				     overflows a 320px screen even shared equally. -->
				<div class="flex items-center gap-2 {multi ? cls.stackOnPhone : ''}">
					{#if multi}
						<span class="text-sm text-white/60">{heading ?? ''}</span>
					{/if}
					<PillToggle
						stretchOnPhone={multi}
						options={multi ? [{ value: '', label: 'Any' }, ...options] : options}
						value={active}
						onSelect={(v) => refine(selectInGroup(group, shown!, v && v !== active ? v : null))}
						ariaLabel={heading}
					/>
				</div>
			{/each}
			{#if refined}
				<button
					type="button"
					class="inline-flex items-center gap-1.5 text-sm font-medium text-white/70 transition hover:text-white"
					onclick={reset}
				>
					<RotateCcw class="size-4" />
					Reset
				</button>
			{/if}
		</div>
	{/if}
</SeeAllResults>
