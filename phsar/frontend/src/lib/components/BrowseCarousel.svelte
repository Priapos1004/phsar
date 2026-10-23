<script lang="ts">
	// One browse row. Its params are final: docs/features/browse.md.
	//
	// Items load when the row nears the viewport, so a page of rows costs one search per
	// row the user actually reaches — once while `stores/browseRows` keeps it. The
	// row a back link names loads at once instead, since it is the one the page is about
	// to scroll to.
	import { onMount, tick, untrack } from 'svelte';
	import { ArrowRight, ChevronRight, SearchX } from 'lucide-svelte';
	import PosterCard from '$lib/components/PosterCard.svelte';
	import ScrollRow from '$lib/components/ScrollRow.svelte';
	import * as cls from '$lib/styles/classes';
	import type { AnimeSearchResult, BrowseCarousel } from '$lib/types/api';
	import { NO_REFINEMENT, refinedSearch, ROW_SIZE } from '$lib/stores/browseRefinements';
	import { carouselResults, settledResults } from '$lib/stores/browseRows';
	import { buildDetailHref, carouselOrigin } from '$lib/utils/navigation';
	import { carouselFocus, revealFocused } from '$lib/utils/scrollFocus';
	import {
		effectiveSort,
		pinnedSeason,
		readsOwnData,
		type MediaSearchFilters,
	} from '$lib/utils/search';

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

	// A row already in hand (a return to the page) shows at once, at its final height. Read
	// once, as the row mounts: it loads once per mount either way.
	let items = $state<AnimeSearchResult[] | null>(
		untrack(() => settledResults(carousel, NO_REFINEMENT, isGuest, ROW_SIZE) ?? null),
	);
	let failed = $state(false);
	let section = $state<HTMLElement>();
	// The body's height as last seen on screen. A hidden tab (Browse keeps its tabs mounted)
	// measures 0, and easing from that on the way back would grow every row from nothing.
	let bodyHeight = $state<number>();

	async function load() {
		try {
			items = (await carouselResults(carousel, NO_REFINEMENT, isGuest, ROW_SIZE, { page: carousel.page })).results;
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
		// In hand, it still runs `load` (a cache hit) for the return to a tile it may owe.
		if (items || focus || typeof IntersectionObserver === 'undefined') {
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
		<!-- A row coming back empty or failed eases down to its line, so the page below glides
		     rather than jolts. Only then: a row filling with tiles takes its height at once, or
		     every row would visibly settle from the skeleton's two-line footer on each load.
		     `clip`, not `hidden`: a hidden box is a scroll container, which a return's
		     `scrollIntoView` could scroll. -->
		<div
			class="row-body"
			class:ease={failed || items?.length === 0}
			style:height={bodyHeight ? `${bodyHeight}px` : null}
		>
			<div bind:clientHeight={null, (h) => { if (h) bodyHeight = h; }}>
				{#if failed}
					<p class="text-sm text-white/60">Couldn't load this row.</p>
				{:else if items && items.length === 0}
					<!-- A row's own filters can empty it (Discover's start on "Not yet"), so the way out
					     is named: the see-all, where they switch. -->
					<div class="flex items-center gap-4 rounded-xl border border-dashed border-white/20 bg-white/5 px-5 py-5">
						<span class="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
							<SearchX class="size-5" />
						</span>
						<div class="space-y-0.5">
							<p class="font-medium text-white">Nothing here right now</p>
							{#if carousel.filter_sets.some((s) => s.default_on)}
								<p class="text-sm text-white/60">
									Switch off a filter in <a href="/browse/{carousel.key}" class="text-primary hover:underline">See all</a> to show more.
								</p>
							{/if}
						</div>
					</div>
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
					<!-- Outside ScrollRow: a skeleton is nothing to page through. Each slot is a tile's
					     footprint — PosterCard's border, cover and a footer as tall as its two-line
					     title and line — so the skeleton stands as tall as the tiles replacing it. -->
					<div class="flex gap-3 overflow-hidden pt-1 pb-2">
						{#each { length: 8 } as _}
							<div class="shrink-0 w-32 sm:w-36 rounded-xl border border-transparent">
								<div class="aspect-[2/3] rounded-xl bg-white/5 animate-pulse"></div>
								<div class="invisible flex flex-col gap-0.5 p-2" aria-hidden="true">
									<span class="text-xs leading-snug">&nbsp;<br />&nbsp;</span>
									<span class="text-[11px]">&nbsp;</span>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	{/if}
</section>

<style>
	.row-body {
		overflow: clip;
	}
	.row-body.ease {
		transition: height 350ms ease;
	}
	@media (prefers-reduced-motion: reduce) {
		.row-body.ease {
			transition: none;
		}
	}
</style>
