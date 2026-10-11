<script lang="ts">
	// One browse row. Its params are final: docs/features/browse.md.
	//
	// Items load when the row nears the viewport, so a page of rows costs one search per
	// row the user actually reaches — once per visit to Browse (`stores/browseRows`). The
	// row a back link names loads at once instead, since it is the one the page is about
	// to scroll to.
	import { onMount, tick } from 'svelte';
	import { ChevronLeft, ChevronRight } from 'lucide-svelte';
	import PosterCard from '$lib/components/PosterCard.svelte';
	import type { AnimeSearchResult, BrowseCarousel } from '$lib/types/api';
	import { browseRow } from '$lib/stores/browseRows';
	import { userSettings } from '$lib/stores/userSettings';
	import { buildDetailHref, navigateToSearch } from '$lib/utils/navigation';
	import { carouselFocus, revealFocused } from '$lib/utils/scrollFocus';
	import {
		effectiveSort,
		sortLine,
		stripForGuest,
		unusualAnnouncedType,
		type MediaSearchFilters,
	} from '$lib/utils/search';

	const ROW_SIZE = 25;
	const ARROW =
		'absolute top-[40%] -translate-y-1/2 z-10 flex size-9 items-center justify-center rounded-full bg-black/60 text-white backdrop-blur hover:bg-black/80 transition pointer-coarse:hidden';

	interface Props {
		carousel: BrowseCarousel;
		isGuest: boolean;
		/** Set when a back link returned to this row; `uuid` is the tile in it. */
		focus?: { uuid: string | null } | null;
	}

	let { carousel, isGuest, focus = null }: Props = $props();

	let search = $derived<MediaSearchFilters>({ query: '', search_type: 'title', ...carousel.params, view_type: 'anime' });
	// Guests: docs/features/browse.md#guests.
	let guestBlocked = $derived(isGuest && stripForGuest(search).stripped);
	let sort = $derived(effectiveSort(search).sort);
	// A row pinned to one season names it; no carousel field says so.
	let season = $derived(search.anime_season?.length === 1 ? search.anime_season[0] : null);
	let nameLanguage = $derived($userSettings?.name_language ?? 'english');
	let ratingStep = $derived(Number($userSettings?.rating_step ?? '0.5'));

	let items = $state<AnimeSearchResult[] | null>(null);
	let failed = $state(false);
	let section = $state<HTMLElement>();
	let scroller = $state<HTMLDivElement>();
	let atStart = $state(true);
	let atEnd = $state(true);

	async function load() {
		try {
			items = await browseRow(search, ROW_SIZE);
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
		const tile = id ? scroller?.querySelector<HTMLElement>(`[data-focus-uuid="${CSS.escape(id)}"]`) : null;
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

	function updateArrows() {
		if (!scroller) return;
		atStart = scroller.scrollLeft <= 1;
		atEnd = scroller.scrollLeft + scroller.clientWidth >= scroller.scrollWidth - 1;
	}

	// Once the tiles are in — a ResizeObserver reports as it starts observing — and again
	// whenever the row itself resizes, which the window is not the only thing to change.
	$effect(() => {
		if (!items || !scroller || typeof ResizeObserver === 'undefined') return;
		const observer = new ResizeObserver(updateArrows);
		observer.observe(scroller);
		return () => observer.disconnect();
	});

	function page(direction: 1 | -1) {
		scroller?.scrollBy({ left: direction * scroller.clientWidth * 0.9, behavior: 'smooth' });
	}
</script>

<section bind:this={section} data-focus-uuid={carousel.key} class="space-y-2">
	{#if guestBlocked}
		<h2 class="text-lg font-semibold text-white">{carousel.title}</h2>
		<div class="rounded-xl border border-white/10 bg-card/40 px-4 py-6 text-sm text-white/60">
			This row is built from your own ratings and watchlist — guest accounts have neither.
		</div>
	{:else}
		<div class="flex items-center gap-2">
			<button
				type="button"
				class="group inline-flex items-center gap-1 text-lg font-semibold text-white hover:text-primary transition"
				onclick={() => navigateToSearch(search)}
			>
				{carousel.title}
				<ChevronRight class="size-5 transition group-hover:translate-x-0.5" />
			</button>
			{#if season}
				<span class="rounded-full bg-white/10 px-2.5 py-0.5 text-xs font-medium text-white/70">{season}</span>
			{/if}
		</div>

		{#if failed}
			<p class="text-sm text-white/60">Couldn't load this row.</p>
		{:else if items && items.length === 0}
			<p class="text-sm text-white/60">Nothing here right now.</p>
		{:else}
			<div class="relative">
				<div
					bind:this={scroller}
					onscroll={updateArrows}
					class="flex gap-3 overflow-x-auto snap-x snap-mandatory pt-1 pb-2 no-scrollbar"
				>
					{#if items}
						{#each items as item (item.uuid)}
							{@const focusId = carouselFocus(carousel.key, item.uuid)}
							<div class="snap-start shrink-0 w-32 sm:w-36" data-focus-uuid={focusId}>
								<PosterCard
									row={item}
									href={buildDetailHref('anime', item.uuid, { from: 'browse', focus: focusId })}
									{nameLanguage}
									line={sortLine(sort, item, ratingStep)}
									badge={unusualAnnouncedType(item)}
								/>
							</div>
						{/each}
					{:else}
						{#each { length: 8 } as _}
							<div class="snap-start shrink-0 w-32 sm:w-36">
								<div class="aspect-[2/3] rounded-xl bg-white/5 animate-pulse"></div>
								<div class="h-10"></div>
							</div>
						{/each}
					{/if}
				</div>
				{#if items && !atStart}
					<button type="button" aria-label="Scroll left" class="{ARROW} left-1" onclick={() => page(-1)}>
						<ChevronLeft class="size-5" />
					</button>
				{/if}
				{#if items && !atEnd}
					<button type="button" aria-label="Scroll right" class="{ARROW} right-1" onclick={() => page(1)}>
						<ChevronRight class="size-5" />
					</button>
				{/if}
			</div>
		{/if}
	{/if}
</section>
