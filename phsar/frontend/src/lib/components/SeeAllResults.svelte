<script lang="ts">
	// A list past a row's or a search's cap, as poster tiles. The pages own the fetch; this
	// owns the layout, the slicing and the return to a tile.
	import type { Snippet } from 'svelte';
	import { page } from '$app/state';
	import BackLink from '$lib/components/BackLink.svelte';
	import PosterCard from '$lib/components/PosterCard.svelte';
	import SortControl from '$lib/components/SortControl.svelte';
	import { userSettings } from '$lib/stores/userSettings';
	import type { AnimeSearchResult, MediaSearchResult } from '$lib/types/api';
	import type { DetailHrefOptions } from '$lib/utils/navigation';
	import { consumeFocus, pageCovering, revealFocused } from '$lib/utils/scrollFocus';
	import {
		effectiveSort,
		isAnimeResult,
		sortLine,
		unusualAnnouncedType,
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
		/** At the end of the title row: an action on the whole list. */
		actions?: Snippet;
	}

	let {
		back, title, season = null, grain, params, rows, limit, notice = '', isGuest, onSort, tileHref, children, actions,
	}: Props = $props();

	/** One "Show More" step: a whole number of rows at 3–6 columns. */
	const PAGE_STEP = 60;

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');
	let ratingStep = $derived(Number($userSettings?.rating_step ?? '0.5'));
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

<div class="mx-auto max-w-5xl space-y-4">
	<BackLink origin={back} />

	<div class="flex flex-wrap items-center gap-2">
		<h1 class="text-2xl font-bold text-white">{title}</h1>
		{#if season}
			<span class="rounded-full bg-white/10 px-2.5 py-0.5 text-xs font-medium text-white/70">{season}</span>
		{/if}
		{#if actions && !notice}
			<div class="ml-auto">{@render actions()}</div>
		{/if}
	</div>

	{@render children?.()}

	{#if notice}
		<div class="rounded-xl border border-white/10 bg-card/40 px-4 py-6 text-sm text-white/60">{notice}</div>
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
							{nameLanguage}
							line={sort ? sortLine(sort, row, ratingStep) : null}
							badge={isAnimeResult(row) ? unusualAnnouncedType(row) : null}
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
