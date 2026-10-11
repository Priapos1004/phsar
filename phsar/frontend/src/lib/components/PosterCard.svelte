<script lang="ts">
	// A compact cover tile for browse rows: one `line` of metadata rather than the search
	// card's full set, so a row shows several at once. The coverage marking follows
	// `RatedAnimeCard`.
	import WatchlistBookmarkIcon from '$lib/components/WatchlistBookmarkIcon.svelte';
	import { Badge } from '$lib/components/ui/badge';
	import { ratingCoverage } from '$lib/stores/ratingCoverage';
	import { watchlistAnimeColors } from '$lib/stores/watchlist';
	import * as cls from '$lib/styles/classes';
	import type { AnimeSearchResult } from '$lib/types/api';
	import { formatMediaType, resolveTitle } from '$lib/utils/formatString';
	import { COVERAGE_STYLE } from '$lib/utils/ratingCoverage';

	interface Props {
		row: AnimeSearchResult;
		href: string;
		nameLanguage: 'english' | 'japanese' | 'romaji';
		/** What the list is ordered by, for this row; nothing when the order has no value to show. */
		line: string | null;
		/** A media type to name on the cover, when the list has one worth naming. */
		badge?: string | null;
	}

	let { row, href, nameLanguage, line, badge = null }: Props = $props();

	let title = $derived(resolveTitle(row.title, row.name_eng, row.name_jap, nameLanguage));
	let bookmarkColors = $derived($watchlistAnimeColors.get(row.uuid) ?? []);
	let coverage = $derived.by(() => {
		const tier = $ratingCoverage.get(row.uuid);
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
