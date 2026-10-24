<script lang="ts">
	import { formatCompactNumber, formatAiringStatus, formatRelationType, formatMediaType } from '$lib/utils/formatString';
	import { fitChipCount } from '$lib/utils/shareContent';
	import { buildDetailHref } from '$lib/utils/navigation';
	import { CheckCircle2, Clock, MessageSquareQuote, Star } from 'lucide-svelte';
	import * as Card from '$lib/components/ui/card';
	import { Badge } from '$lib/components/ui/badge';
	import * as cls from '$lib/styles/classes';
	import SpoilerGuard from '$lib/components/SpoilerGuard.svelte';
	import WatchlistBookmarkIcon from '$lib/components/WatchlistBookmarkIcon.svelte';
	import { visibleMediaSet } from '$lib/stores/spoilerVisibility';
	import { watchlistTags, watchlistAnimeColors } from '$lib/stores/watchlist';
	import { ratingCoverage } from '$lib/stores/ratingCoverage';
	import { COVERAGE_STYLE } from '$lib/utils/ratingCoverage';
	import type { RelationTypeSummary, MediaTypeSummary } from '$lib/types/api';

	interface Props {
		info_type: 'anime' | 'media';
		title: string;
		score?: number | null;
		scoredBy?: number | null;
		anime_season?: string | null;
		season_range?: string | null;
		airing_status: string;
		has_upcoming?: boolean;
		age_rating_numeric?: number | null;
		genres?: string[] | null;
		media_type?: string | null;
		media_types?: MediaTypeSummary[] | null;
		relation_type?: string | null;
		relation_types?: RelationTypeSummary[] | null;
		watchtime?: string | null;
		imageUrl?: string | null;
		media_uuid: string;
		/** Media-only: the caller has rated this entry (`MediaSearchResult.is_rated`).
		 *  The anime grain reads its tier from the coverage store instead — only the
		 *  anime grain has a denominator to be a fraction of. */
		is_rated?: boolean;
		searchToken?: string | null;
		/**
		 * Anime-only: admin-marked story-complete. Renders a small badge by the title.
		 *
		 * Deliberately bare here — no tooltip. A hover popup firing while the user
		 * scrolls a result list is intrusive, so the airing-vs-story explanation lives
		 * only on the anime detail page's "Story Complete" badge, where the cursor is
		 * already at rest.
		 */
		is_finished?: boolean;
		/** Notes search: the caller's note that matched, quoted on one line. */
		matched_note?: string | null;
	}

	let {
		info_type, title, score = null, scoredBy = null,
		anime_season = null, season_range = null, airing_status,
		has_upcoming = false, age_rating_numeric = null,
		genres = null, media_type = null, media_types = null,
		relation_type = null, relation_types = null, watchtime = null,
		imageUrl = null, media_uuid, is_rated = false,
		searchToken = null, is_finished = false, matched_note = null,
	}: Props = $props();

	let imgFailed = $state(false);

	// The phone genre line: how many genres fold into its "+N" (`fitChipCount`). The line
	// is observed, not the row inside it, because the "+N" narrows only the row; a hidden
	// line (from sm) measures nothing. Reads `genres` so a reused card (the result list is
	// unkeyed) re-counts on new props.
	let genreLine = $state<HTMLElement | null>(null);
	let hiddenGenres = $state(0);
	$effect(() => {
		const line = genreLine;
		if (!line || !genres?.length) return;
		const width = (el: Element) => el.getBoundingClientRect().width;
		const observer = new ResizeObserver(([entry]) => {
			if (!entry.contentRect.width) return;
			const row = line.firstElementChild!;
			const gap = parseFloat(getComputedStyle(row).columnGap) || 0;
			const probe = line.querySelector('[data-overflow-probe]')!;
			hiddenGenres = row.children.length - fitChipCount([...row.children].map(width), width(line), gap, width(probe));
		});
		observer.observe(line);
		return () => observer.disconnect();
	});

	let href = $derived(buildDetailHref(info_type, media_uuid, { q: searchToken }));

	let displaySeason = $derived(season_range ?? anime_season);
	let displayStatus = $derived(formatAiringStatus(airing_status, has_upcoming));
	let showStatus = $derived(airing_status === 'Not yet aired' || airing_status === 'Currently Airing' || has_upcoming);
	// Spoiler: anime cards are always visible; media cards check the frontier store
	let isCoverVisible = $derived(info_type === 'anime' || $visibleMediaSet.has(media_uuid));
	// Watchlist indicator colors: a media card maps to its single tag; an anime card
	// aggregates its watchlisted media's distinct tag colors (solid, or a gradient when
	// it spans tags). Empty → no bookmark.
	let watchlistColors = $derived(
		info_type === 'media'
			? ($watchlistTags.get(media_uuid) ? [$watchlistTags.get(media_uuid)!.tag_color] : [])
			: ($watchlistAnimeColors.get(media_uuid) ?? [])
	);
	// Rated-coverage marking. An anime card shows how much of the anime is rated (the
	// store is keyed by anime uuid, which is what `media_uuid` holds in that view);
	// a media card is binary, so it only ever reaches the base tier.
	let coverage = $derived.by(() => {
		const tier = info_type === 'anime' ? $ratingCoverage.get(media_uuid) : is_rated ? 'some' : undefined;
		return tier ? COVERAGE_STYLE[tier] : null;
	});
	let coverageRing = $derived(
		coverage
			? `box-shadow:0 0 0 2px ${coverage.edge}` +
				(coverage.hairline ? `, 0 0 0 3.5px ${coverage.hairline}` : '')
			: undefined
	);
</script>

{#snippet completeBadge(placement: string)}
	<span class="{placement} inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-semibold border align-middle whitespace-nowrap {cls.badgeComplete}">
		<CheckCircle2 class="size-3" /> Complete
	</span>
{/snippet}

{#snippet typeBadges()}
	{#if relation_type}
		<Badge variant="secondary" class={cls.badgeRelationType}>{formatRelationType(relation_type)}</Badge>
	{/if}
	{#if media_type}
		<Badge variant="secondary" class={cls.badgeMediaType}>{formatMediaType(media_type)}</Badge>
	{/if}
{/snippet}

{#snippet stats()}
	<span><Clock class={cls.glassIcon} aria-hidden="true" /><span class="sr-only">Watch time:</span> {watchtime ?? 'N/A'}</span>
	{#if score !== null && scoredBy !== null}
		<span><Star class={cls.glassIcon} aria-hidden="true" /> {score} <span class="whitespace-nowrap">({formatCompactNumber(scoredBy)} {info_type === 'anime' ? 'ratings/media' : 'ratings'})</span></span>
	{:else}
		<span>No ratings</span>
	{/if}
{/snippet}

<a
	{href}
	data-focus-uuid={media_uuid}
	class="block transition duration-200 transform hover:scale-[1.015]"
>
	<!-- An inline box-shadow, which beats Card.Root's own `ring-1` utility
	     (Tailwind implements a ring as a box-shadow too) — deliberately, since
	     that ring is static and nothing animates it. -->
	<Card.Root class="relative h-full bg-card/80 backdrop-blur" style={coverageRing}>
		{#if coverage}
			<!--
				The band that carries the tier, inside the crisp ring: two mask layers,
				one fading in from the left and right edges and one from top and bottom.
				`mask-composite` defaults to `add`, so their union hugs all four edges and
				falls off toward the middle of the card, strongest in the corners.

				Held opaque for the outer slice rather than fading both ways — a band
				soft on both sides reads as a glow rather than as an edge.

				Named rather than aria-hidden: the band is the only thing carrying the
				coverage state on a search card.
			-->
			<div
				class="coverage-band"
				style:background={coverage.band}
				role="img"
				aria-label={coverage.label}
			></div>
		{/if}
		<!-- A smaller cover and tighter padding on a phone, so the column beside the cover
		     holds a vote count down to 320px. flex-1 fills a card its grid row stretched,
		     and content-between keeps the stats line at its bottom, level with the
		     neighbour's. -->
		<Card.Content class="flex-1 flex flex-wrap content-between gap-x-3 sm:gap-x-4 gap-y-3 px-3 sm:px-4">
			<SpoilerGuard visible={isCoverVisible} mode="image">
				{#if imageUrl && !imgFailed}
				<img
					src={imageUrl}
					alt={`Cover of ${title}`}
					class="w-20 h-30 sm:w-24 sm:h-36 object-cover rounded-lg shadow-sm"
					loading="lazy"
					onerror={() => { imgFailed = true; }}
				/>
				{:else}
					<div class="w-20 h-30 sm:w-24 sm:h-36 bg-muted rounded-lg flex items-center justify-center text-muted-foreground text-sm italic">
						No image
					</div>
				{/if}
			</SpoilerGuard>

			<!-- flex-1's zero basis keeps the column beside the cover — an auto basis lets a
			     long title wrap it under. min-w-0 lets the note quote truncate. -->
			<div class="flex flex-col flex-1 min-w-0 space-y-2">
				<div class="flex items-start justify-between">
					<div>
						<!-- Plain flow, not flex: the badge follows the last word, where a flex row
						     would squeeze the title to a word per line beside it. On a phone the
						     title fills its line, so the badge waits behind the age instead. -->
						<h3 class="text-lg font-bold text-card-foreground">
							{title}
							{#if is_finished}{@render completeBadge('ml-1 max-sm:hidden')}{/if}
						</h3>
						<!-- From sm the status shares the season's line, so brackets set it apart
						     as an aside; on a line of its own it needs none. -->
						<div class="flex flex-col sm:flex-row sm:flex-wrap sm:gap-x-2">
							{#if displaySeason}
								<span class="text-primary">{displaySeason}</span>
							{/if}
							{#if showStatus}
								<span class="text-primary/70 sm:order-last sm:before:content-['('] sm:after:content-[')']">{displayStatus}</span>
							{/if}
							{#if age_rating_numeric !== null || is_finished}
								<span class="text-card-foreground">{#if age_rating_numeric !== null}{age_rating_numeric}+{/if}{#if is_finished}{@render completeBadge('ml-1.5 sm:hidden')}{/if}</span>
							{/if}
						</div>
					</div>
					{#if watchlistColors.length}
						<WatchlistBookmarkIcon colors={watchlistColors} iconClass="w-5 h-5" />
					{/if}
				</div>

				{#if media_type || relation_type || media_types?.length || relation_types?.length || genres?.length}
					<!-- Not on a phone, where the column is too narrow for them: the anime grain's
					     counts stay on the anime page, and the media grain's badges and the genres
					     move under the cover. -->
					<div class="flex flex-wrap gap-2 max-sm:hidden">
						{#each relation_types ?? [] as rt}
							<Badge variant="secondary" class={cls.badgeRelationType}>{formatRelationType(rt.relation_type)}: {rt.count}</Badge>
						{/each}
						{#each media_types ?? [] as mt}
							<Badge variant="secondary" class={cls.badgeMediaType}>{formatMediaType(mt.media_type)}: {mt.count}</Badge>
						{/each}
						{@render typeBadges()}

						{#each genres ?? [] as genre}
							<Badge variant="secondary" class={cls.badgeGenre}>{genre}</Badge>
						{/each}
					</div>
				{/if}

				{#if matched_note}
					<p class="flex items-center gap-1.5 text-sm italic text-card-foreground/80" title={matched_note}>
						<MessageSquareQuote class="size-4 shrink-0 not-italic text-primary" />
						<span class="truncate">{matched_note}</span>
					</p>
				{/if}

				<!-- On a phone, stacked beside the cover with the score first: the card's full
				     width can't hold both on one line. From sm it spans the card below. -->
				<div class="flex flex-col-reverse text-sm text-muted-foreground sm:hidden">
					{@render stats()}
				</div>
			</div>

			{#if relation_type || media_type}
				<div class="basis-full flex flex-wrap gap-2 sm:hidden">
					{@render typeBadges()}
				</div>
			{/if}
			{#if genres?.length}
				<!-- Whole genres only: the row wraps but shows one line, so what doesn't fit
				     beside the "+N" drops out of sight still measurable. The line's gap
				     matches the row's, which is the gap fitChipCount assumes before the "+N". -->
				<div bind:this={genreLine} class="relative basis-full flex gap-x-1 text-primary sm:hidden">
					<div class="flex flex-wrap gap-x-1 h-[1lh] overflow-hidden min-w-0 flex-1">
						{#each genres as genre, i}
							<span>{i ? '· ' : ''}{genre}</span>
						{/each}
					</div>
					{#if hiddenGenres}
						<span class="shrink-0 text-muted-foreground">+{hiddenGenres}</span>
					{/if}
					<span data-overflow-probe class="invisible absolute">+{genres.length}</span>
				</div>
			{/if}
			<!-- From sm, the card's full width, so every card shows its stats in the same place:
			     the watch time under the cover's edge, the score at the right. -->
			<div class="basis-full flex justify-between gap-x-4 text-sm text-muted-foreground max-sm:hidden">
				{@render stats()}
			</div>
		</Card.Content>
	</Card.Root>
</a>

<style>
	.coverage-band {
		position: absolute;
		inset: 0;
		pointer-events: none;
		border-radius: inherit;
		--band-w: 11px;
		--band-solid: calc(var(--band-w) * 0.3);
		/* Named once: the falloff shape is one edit, not four in lockstep. */
		--band-stops: #000 0, #000 var(--band-solid), transparent var(--band-w),
			transparent calc(100% - var(--band-w)), #000 calc(100% - var(--band-solid)), #000 100%;
		--band-mask: linear-gradient(to right, var(--band-stops)),
			linear-gradient(to bottom, var(--band-stops));
		-webkit-mask-image: var(--band-mask);
		mask-image: var(--band-mask);
	}
</style>
