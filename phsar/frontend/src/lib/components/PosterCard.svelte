<script lang="ts">
	// A compact cover tile for browse rows and see-all grids: one `line` of metadata rather
	// than the search card's full set, so a row shows several at once. The coverage marking
	// follows `RatedAnimeCard`. At the media grain the cover, bookmark and band are
	// `MediaInfo`'s: behind the spoiler guard, and rated or not.
	import SpoilerGuard from '$lib/components/SpoilerGuard.svelte';
	import WatchlistBookmarkIcon from '$lib/components/WatchlistBookmarkIcon.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { ratingCoverage } from '$lib/stores/ratingCoverage';
	import { visibleMediaSet } from '$lib/stores/spoilerVisibility';
	import { userSettings } from '$lib/stores/userSettings';
	import { watchlistAnimeColors, watchlistTags } from '$lib/stores/watchlist';
	import * as cls from '$lib/styles/classes';
	import type { AnimeSearchResult, MediaSearchResult } from '$lib/types/api';
	import { formatMediaType, resolveTitle } from '$lib/utils/formatString';
	import { isAnimeResult, sortLine, unusualAnnouncedType, type SortKey } from '$lib/utils/search';
	import { COVERAGE_STYLE } from '$lib/utils/ratingCoverage';

	interface Props {
		row: AnimeSearchResult | MediaSearchResult;
		href: string;
		/** What the list is ordered by: the tile's one line is this row's value under it, and
		 *  null (still loading) shows none. */
		sort: SortKey | null;
	}

	let { row, href, sort }: Props = $props();

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');
	let ratingStep = $derived(Number($userSettings?.rating_step ?? '0.5'));
	let line = $derived(sort ? sortLine(sort, row, ratingStep) : null);
	// Shows only under the announced sort, the one that fills `announced_type`; anime only,
	// since a media has no franchise to differ from.
	let badge = $derived(isAnimeResult(row) ? unusualAnnouncedType(row) : null);

	let title = $derived(resolveTitle(row.title, row.name_eng, row.name_jap, nameLanguage));
	let bookmarkColors = $derived.by(() => {
		if (isAnimeResult(row)) return $watchlistAnimeColors.get(row.uuid) ?? [];
		const tag = $watchlistTags.get(row.uuid);
		return tag ? [tag.tag_color] : [];
	});
	let coverage = $derived.by(() => {
		const tier = isAnimeResult(row) ? $ratingCoverage.get(row.uuid) : row.is_rated ? 'some' : undefined;
		return tier ? COVERAGE_STYLE[tier] : null;
	});
	let imgFailed = $state(false);
</script>

<a {href} class="group block h-full transition duration-200 hover:-translate-y-0.5">
	<div
		class="{cls.cardGlass} rounded-xl overflow-hidden border border-border h-full flex flex-col shadow-sm group-hover:shadow-md group-hover:ring-1 group-hover:ring-primary/40 transition"
		style:outline={coverage ? `2px solid ${coverage.edge}` : undefined}
		style:border-color={coverage?.hairline}
	>
		<div class="relative">
			<SpoilerGuard visible={isAnimeResult(row) || $visibleMediaSet.has(row.uuid)} mode="image">
				{#if row.cover_image && !imgFailed}
					<img
						src={row.cover_image}
						alt={`Cover of ${title}`}
						class="w-full aspect-[2/3] object-cover"
						loading="lazy"
						onerror={() => (imgFailed = true)}
					/>
				{:else}
					<div class="w-full aspect-[2/3] bg-muted flex items-center justify-center text-muted-foreground text-xs italic">
						No image
					</div>
				{/if}
			</SpoilerGuard>
			{#if badge}
				<Badge variant="secondary" class="absolute top-1.5 left-1.5 text-[10px] h-5 {cls.badgeMediaTypeColor}">
					{formatMediaType(badge)}
				</Badge>
			{/if}
			{#if bookmarkColors.length > 0}
				<div class={cls.coverBookmark}>
					<WatchlistBookmarkIcon colors={bookmarkColors} iconClass="size-3.5 block" />
				</div>
			{/if}
		</div>

		<!-- Only the metal tiers tint the footer: they carry a text colour for it, the
		     theme-coloured base tier does not. -->
		<div
			class="p-2 flex flex-col gap-0.5 flex-grow"
			style:background={coverage?.foreground ? coverage.band : undefined}
		>
			{#if coverage}
				<span class="sr-only">{coverage.label}</span>
			{/if}
			<h3
				class="text-xs font-medium text-card-foreground line-clamp-2 leading-snug"
				style:color={coverage?.foreground}
				{title}
			>
				{title}
			</h3>
			{#if line}
				<span class="mt-auto text-[11px] text-muted-foreground" style:color={coverage?.foreground}>{line}</span>
			{/if}
		</div>
	</div>
</a>
