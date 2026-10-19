<script lang="ts">
	// One browse row. Its params are final: docs/features/browse.md.
	//
	// Items load when the row nears the viewport, so a page of rows costs one search per
	// row the user actually reaches — once while `stores/browseRows` keeps it. The
	// row a back link names loads at once instead, since it is the one the page is about
	// to scroll to.
	import { onMount, tick } from 'svelte';
	import { ArrowRight, ChevronRight } from 'lucide-svelte';
	import PosterCard from '$lib/components/PosterCard.svelte';
	import ScrollRow from '$lib/components/ScrollRow.svelte';
	import * as cls from '$lib/styles/classes';
	import type { AnimeSearchResult, BrowseCarousel } from '$lib/types/api';
	import { NO_REFINEMENT, refinedSearch } from '$lib/stores/browseRefinements';
	import { browseRow } from '$lib/stores/browseRows';
	import { buildDetailHref, carouselOrigin } from '$lib/utils/navigation';
	import { carouselFocus, revealFocused } from '$lib/utils/scrollFocus';
	import {
		effectiveSort,
		pinnedSeason,
		readsOwnData,
		type MediaSearchFilters,
	} from '$lib/utils/search';

	const ROW_SIZE = 25;

	interface Props {
		carousel: BrowseCarousel;
		isGuest: boolean;
		/** Set when a back link returned to this row; `uuid` is the tile in it. */
		focus?: { uuid: string | null } | null;
	}

	let { carousel, isGuest, focus = null }: Props = $props();

	let search = $derived<MediaSearchFilters>({ ...refinedSearch(carousel, NO_REFINEMENT, isGuest), view_type: 'anime' });
	// Guests: docs/features/browse.md#guests.
	let guestBlocked = $derived(isGuest && readsOwnData(search));
	let sort = $derived(effectiveSort(search).sort);
	// A row pinned to one season names it; no carousel field says so.
	let season = $derived(pinnedSeason(search));

	let items = $state<AnimeSearchResult[] | null>(null);
	let failed = $state(false);
	let section = $state<HTMLElement>();

	async function load() {
		try {
			items = await browseRow(search, ROW_SIZE, { page: carousel.page });
		} catch {
			failed = true;
			return;
		}
		if (focus) await reveal(focus.uuid);
	}

	// Land a back link on the tile it left from, or on the row when that tile is gone.
	// Sideways first, here — the shared pin is vertical only (`pinCentred`) — and the pin
	// then finds the tile already in view.
	async function reveal(uuid: string | null) {
		await tick();
		const id = uuid ? carouselFocus(carousel.key, uuid) : null;
		const tile = id ? section?.querySelector<HTMLElement>(`[data-focus-uuid="${CSS.escape(id)}"]`) : null;
		if (!tile) return revealFocused(carousel.key);
		tile.scrollIntoView({ block: 'nearest', inline: 'center' });
		revealFocused(id);
	}

	onMount(() => {
		if (guestBlocked) return;
		if (focus || typeof IntersectionObserver === 'undefined') {
			void load();
			return;
		}
		const observer = new IntersectionObserver(
			(entries) => {
				if (!entries.some((e) => e.isIntersecting)) return;
				observer.disconnect();
				void load();
			},
			{ rootMargin: '400px 0px' },
		);
		observer.observe(section!);
		return () => observer.disconnect();
	});
</script>

<section bind:this={section} data-focus-uuid={carousel.key} class="space-y-2">
	<!-- A return to the row centres the section and flashes this header alone: a ring
	     round a whole carousel reads as a frame, not as a landing. -->
	<header data-flash-target class="-mx-2 flex items-center gap-2 rounded-lg px-2">
		{#if guestBlocked}
			<h2 class="text-lg font-semibold text-white">{carousel.title}</h2>
		{:else}
			<!-- The title and the end tile both open the see-all, as a row's title does in
			     most catalogue apps; opening the row as a search is the see-all's own link. -->
			<a
				href="/browse/{carousel.key}"
				class="group inline-flex items-center gap-1 text-lg font-semibold text-white hover:text-primary transition"
			>
				{carousel.title}
				<ChevronRight class="size-5 transition group-hover:translate-x-0.5" />
			</a>
			{#if season}
				<span class={cls.seasonPill}>{season}</span>
			{/if}
		{/if}
	</header>

	{#if guestBlocked}
		<div class={cls.noticeCard}>
			This row is built from your own ratings and watchlist — guest accounts have neither.
		</div>
	{:else}
		{#if failed}
			<p class="text-sm text-white/60">Couldn't load this row.</p>
		{:else if items && items.length === 0}
			<p class="text-sm text-white/60">Nothing here right now.</p>
		{:else if items}
			<ScrollRow class="gap-3 pt-1 pb-2">
				{#each items as item (item.uuid)}
					{@const focusId = carouselFocus(carousel.key, item.uuid)}
					<div class="snap-start shrink-0 w-32 sm:w-36" data-focus-uuid={focusId}>
						<PosterCard
							row={item}
							href={buildDetailHref('anime', item.uuid, { from: carouselOrigin(carousel.page), focus: focusId })}
							{sort}
						/>
					</div>
				{/each}
				<!-- The see-all again, for whoever scrolled to the end. A tile of the row's
				     own height and shell; the tint deepens rather than appears on hover, so
				     it reads as part of the row rather than as a button. -->
				<a
					href="/browse/{carousel.key}"
					class="group/all snap-start shrink-0 w-32 sm:w-36 transition duration-200 hover:-translate-y-0.5"
				>
					<div class="{cls.cardGlass} relative h-full overflow-hidden rounded-xl border border-border shadow-sm transition group-hover/all:shadow-md group-hover/all:ring-1 group-hover/all:ring-primary/40">
						<div class="absolute inset-0 bg-gradient-to-br from-primary/45 via-primary/15 to-primary/5 opacity-70 transition-opacity duration-300 group-hover/all:opacity-100"></div>
						<div class="relative flex h-full flex-col items-center justify-center gap-3">
							<span class="flex size-11 items-center justify-center rounded-full border border-primary/40 bg-primary/10 text-primary transition duration-300 group-hover/all:scale-105 group-hover/all:bg-primary/20">
								<ArrowRight class="size-5" />
							</span>
							<span class="text-sm font-medium text-card-foreground/80 transition group-hover/all:text-card-foreground">See all</span>
						</div>
					</div>
				</a>
			</ScrollRow>
		{:else}
			<!-- Outside ScrollRow: a skeleton is nothing to page through. -->
			<div class="flex gap-3 overflow-hidden pt-1 pb-2">
				{#each { length: 8 } as _}
					<div class="shrink-0 w-32 sm:w-36">
						<div class="aspect-[2/3] rounded-xl bg-white/5 animate-pulse"></div>
						<div class="h-10"></div>
					</div>
				{/each}
			</div>
		{/if}
	{/if}
</section>
