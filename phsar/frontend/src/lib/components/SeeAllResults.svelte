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
		SEE_ALL_STEP,
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
		/** Null while loading — and between two lists, which is how a new one starts at the
		 *  first step. */
		rows: (AnimeSearchResult | MediaSearchResult)[] | null;
		/** `rows` is the first step of a list whose rest is still loading: the count reads
		 *  "+", and a Show More clicked meanwhile waits for the rest. */
		pending?: boolean;
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
		back, title, season = null, grain, params, rows, pending = false, limit, notice = '', isGuest, onSort, tileHref,
		children, actions,
	}: Props = $props();

	let order = $derived(params ? effectiveSort(params) : null);
	let sort = $derived(order?.sort ?? null);
	let orderLabel = $derived(
		order ? (order.dir && order.option.dir ? `${order.option.label} · ${order.option.dir[order.dir]}` : order.option.label) : '',
	);
	// Exactly at the cap reads "+" too: the cap can be the endpoint's own, which can't be
	// probed by asking for one more.
	const count = (n: number) => (pending ? `${n}+` : n >= limit ? `${limit}+` : `${n}`);
	let countLabel = $derived(rows ? `${count(rows.length)} ${grain}` : '');

	let visibleCount = $state(SEE_ALL_STEP);
	// A Show More clicked before the rest arrived.
	let waiting = $derived(pending && rows !== null && visibleCount > rows.length);

	// On the loading state rather than on `rows`, so the rest of a list arriving keeps a Show
	// More clicked meanwhile. Declared before the reveal below, which runs after it on the
	// same change and may expand past it.
	$effect(() => {
		if (rows === null) visibleCount = SEE_ALL_STEP;
	});

	// Restore the tile a back link came from, as the search page restores its card — over
	// the whole list, which a first step may not reach.
	let revealed = false;
	$effect(() => {
		if (revealed || !rows?.length || pending) return;
		revealed = true;
		const uuid = consumeFocus(page.url);
		if (!uuid) return;
		const index = rows.findIndex((r) => r.uuid === uuid);
		if (index < 0) return;
		visibleCount = pageCovering(index, SEE_ALL_STEP, visibleCount);
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
		{:else if rows && (rows.length > visibleCount || pending)}
			<div class="text-center">
				<button
					onclick={() => (visibleCount += SEE_ALL_STEP)}
					disabled={waiting}
					class="mt-2 px-4 py-2 bg-primary text-primary-foreground rounded-full hover:bg-primary/80 transition disabled:opacity-60"
				>
					{waiting ? 'Loading…' : 'Show More'}
				</button>
			</div>
		{/if}
	{/if}
</div>
