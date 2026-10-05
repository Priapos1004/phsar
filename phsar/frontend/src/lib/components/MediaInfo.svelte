<script lang="ts">
	import { formatNumber, formatAiringStatus, formatRelationType, formatMediaType } from '$lib/utils/formatString';
	import { buildDetailHref, type DetailOrigin } from '$lib/utils/navigation';
	import { CheckCircle2 } from 'lucide-svelte';
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
		fromParam?: DetailOrigin | null;
		/**
		 * Anime-only: admin-marked story-complete. Renders a small badge by the title.
		 *
		 * Deliberately bare here — no tooltip. A hover popup firing while the user
		 * scrolls a result list is intrusive, so the airing-vs-story explanation lives
		 * only on the anime detail page's "Story Complete" badge, where the cursor is
		 * already at rest.
		 */
		is_finished?: boolean;
	}

	let {
		info_type, title, score = null, scoredBy = null,
		anime_season = null, season_range = null, airing_status,
		has_upcoming = false, age_rating_numeric = null,
		genres = null, media_type = null, media_types = null,
		relation_type = null, relation_types = null, watchtime = null,
		imageUrl = null, media_uuid, is_rated = false,
		searchToken = null, fromParam = null, is_finished = false,
	}: Props = $props();

	let imgFailed = $state(false);

	let href = $derived(buildDetailHref(info_type, media_uuid, { q: searchToken, from: fromParam }));

	let displaySeason = $derived(season_range ?? anime_season);
	let displayStatus = $derived(formatAiringStatus(airing_status, has_upcoming));
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
		<Card.Content class="flex gap-4">
			<SpoilerGuard visible={isCoverVisible} mode="image">
				{#if imageUrl && !imgFailed}
				<img
					src={imageUrl}
					alt={`Cover of ${title}`}
					class="w-24 h-36 object-cover rounded-lg shadow-sm"
					loading="lazy"
					onerror={() => { imgFailed = true; }}
				/>
				{:else}
					<div class="w-24 h-36 bg-muted rounded-lg flex items-center justify-center text-muted-foreground text-sm italic">
						No image
					</div>
				{/if}
			</SpoilerGuard>

			<div class="flex flex-col justify-between flex-grow space-y-2">
				<div class="flex items-start justify-between">
					<div>
						<h3 class="text-lg font-bold text-card-foreground inline-flex items-center gap-1.5">
							{title}
							{#if is_finished}
								<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-semibold border align-middle {cls.badgeComplete}">
									<CheckCircle2 class="size-3" /> Complete
								</span>
							{/if}
						</h3>
						{#if displaySeason || airing_status === 'Not yet aired' || airing_status === 'Currently Airing' || has_upcoming}
							<p class="text-primary">
								{#if displaySeason}
									{displaySeason}
								{/if}

								{#if age_rating_numeric !== null}
									<span class="text-card-foreground px-1 py-0.5">
										{age_rating_numeric}+
									</span>
								{/if}

								{#if airing_status === 'Not yet aired' || airing_status === 'Currently Airing' || has_upcoming}
									<span class="ml-2 text-sm text-primary/70">({displayStatus})</span>
								{/if}
							</p>
						{/if}
					</div>
					{#if watchlistColors.length}
						<WatchlistBookmarkIcon colors={watchlistColors} iconClass="w-5 h-5" />
					{/if}
				</div>

				{#if media_type || relation_type || media_types?.length || relation_types?.length || genres?.length}
					<div class="flex flex-wrap gap-2">
						{#if relation_types?.length}
							{#each relation_types as rt}
								<Badge variant="secondary" class={cls.badgeRelationType}>{formatRelationType(rt.relation_type)}: {rt.count}</Badge>
							{/each}
						{:else if relation_type}
							<Badge variant="secondary" class={cls.badgeRelationType}>{formatRelationType(relation_type)}</Badge>
						{/if}

						{#if media_types?.length}
							{#each media_types as mt}
								<Badge variant="secondary" class={cls.badgeMediaType}>{formatMediaType(mt.media_type)}: {mt.count}</Badge>
							{/each}
						{:else if media_type}
							<Badge variant="secondary" class={cls.badgeMediaType}>{formatMediaType(media_type)}</Badge>
						{/if}

						{#each genres ?? [] as genre}
							<Badge variant="secondary" class={cls.badgeGenre}>{genre}</Badge>
						{/each}
					</div>
				{/if}

				<div class="flex justify-between text-sm text-muted-foreground">
					<span>{watchtime ? `Watch time: ${watchtime}` : 'Watch time: N/A'}</span>
					{#if score !== null && scoredBy !== null}
						<span>⭐ {score} — {formatNumber(scoredBy)} {info_type === 'anime' ? 'ratings/media' : 'ratings'}</span>
					{:else}
						<span>No ratings</span>
					{/if}
				</div>
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
