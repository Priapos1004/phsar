<script lang="ts">
	// A list past a row's or a search's cap, as poster tiles. The pages own the fetch; this
	// owns the layout, the slicing and the return to a tile.
	import type { Snippet } from 'svelte';
	import { page } from '$app/state';
	import BackLink from '$lib/components/BackLink.svelte';
	import PosterCard from '$lib/components/PosterCard.svelte';
	import SortControl from '$lib/components/SortControl.svelte';
	import * as cls from '$lib/styles/classes';
	import type { AnimeSearchResult, MediaSearchResult } from '$lib/types/api';
	import type { DetailHrefOptions } from '$lib/utils/navigation';
	import { consumeFocus, pageCovering, revealFocused } from '$lib/utils/scrollFocus';
	import {
		effectiveSort,
		type MediaSearchFilters,
		type SortDir,
		type SortKey,
		type ViewType,
	} from '$lib/utils/search';

	interface Props {
		/** Where the back link goes. */
		back: DetailHrefOptions;
		title: string;
		season?: string | null;
		grain: ViewType;
		/** The search shown, once known: the sort control and each tile's line read it. */
		params: MediaSearchFilters | null;
		/** Null while loading. */
		rows: (AnimeSearchResult | MediaSearchResult)[] | null;
		/** The most the page asked for; a list that long says so with a "+". */
		limit: number;
		/** Shown in place of the list — a failure, or a guest's explanation. */
		notice?: string;
		isGuest: boolean;
		/** Without it the order is shown, not offered. */
		onSort?: (change: { sort: SortKey; sort_dir?: SortDir }) => void;
		tileHref: (uuid: string) => string;
		/** Between the title and the list: a refinement bar, a notice. */
		children?: Snippet;
		/** Beside the back link, as the media page's "To anime": a link off the whole list,
		 *  styled `cls.pageNavLink`. */
		actions?: Snippet;
	}

	let {
		back, title, season = null, grain, params, rows, limit, notice = '', isGuest, onSort, tileHref, children, actions,
	}: Props = $props();

	/** One "Show More" step: a whole number of rows at 3–6 columns. */
	const PAGE_STEP = 60;

	let order = $derived(params ? effectiveSort(params) : null);
	let sort = $derived(order?.sort ?? null);
	let orderLabel = $derived(
		order ? (order.dir && order.option.dir ? `${order.option.label} · ${order.option.dir[order.dir]}` : order.option.label) : '',
	);
	// Exactly at the cap reads "+" too: the cap can be the endpoint's own, which can't be
	// probed by asking for one more.
	let countLabel = $derived(rows ? `${rows.length >= limit ? `${limit}+` : rows.length} ${grain}` : '');

	let visibleCount = $state(PAGE_STEP);

	// A new list starts at the first step. Declared before the reveal below, which runs
	// after it on the same change and may expand past it.
	$effect(() => {
		void rows;
		visibleCount = PAGE_STEP;
	});

	// Restore the tile a back link came from, as the search page restores its card.
	let revealed = false;
	$effect(() => {
		if (revealed || !rows?.length) return;
		revealed = true;
		const uuid = consumeFocus(page.url);
		if (!uuid) return;
		const index = rows.findIndex((r) => r.uuid === uuid);
		if (index < 0) return;
		visibleCount = pageCovering(index, PAGE_STEP, visibleCount);
		revealFocused(uuid);
	});
</script>

<div class="{cls.pageWidth} space-y-4">
	<BackLink origin={back} children={notice ? undefined : actions} />

	<div class="flex flex-wrap items-center gap-2">
		<!-- wrap-anywhere: the user's query in a flex item (rules/frontend.md, "A user's string can be one long word"). -->
		<h1 class="text-2xl font-bold text-white wrap-anywhere">{title}</h1>
		{#if season}
			<span class={cls.seasonPill}>{season}</span>
		{/if}
	</div>

	{@render children?.()}

	{#if notice}
		<div class={cls.noticeCard}>{notice}</div>
	{:else}
		{#if params}
			<div class="flex flex-wrap items-center gap-2">
				<span class="mr-auto text-sm text-white/70">{countLabel}</span>
				{#if onSort}
					<SortControl {params} {isGuest} onChange={onSort} />
				{:else}
					<span class="text-sm text-white/60">{orderLabel}</span>
				{/if}
			</div>
		{/if}

		<div class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-3">
			{#if rows}
				{#each rows.slice(0, visibleCount) as row (row.uuid)}
					<div data-focus-uuid={row.uuid}>
						<PosterCard
							{row}
							href={tileHref(row.uuid)}
							{sort}
						/>
					</div>
				{/each}
			{:else}
				{#each { length: 12 } as _}
					<div>
						<div class="aspect-[2/3] rounded-xl bg-white/5 animate-pulse"></div>
						<div class="h-10"></div>
					</div>
				{/each}
			{/if}
		</div>

		{#if rows && rows.length === 0}
			<p class="text-center text-white/60">Nothing here right now.</p>
		{:else if rows && rows.length > visibleCount}
			<div class="text-center">
				<button
					onclick={() => (visibleCount += PAGE_STEP)}
					class="mt-2 px-4 py-2 bg-primary text-primary-foreground rounded-full hover:bg-primary/80 transition"
				>
					Show More
				</button>
			</div>
		{/if}
	{/if}
</div>
