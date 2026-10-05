<script lang="ts">
	import { Badge } from '$lib/components/ui/badge';
	import { scoreColor } from '$lib/utils/chartColors';
	import { formatDecimalDigits, resolveTitle } from '$lib/utils/formatString';
	import { buildDetailHref } from '$lib/utils/navigation';
	import * as cls from '$lib/styles/classes';
	import { mainSideLabel } from '$lib/utils/relations';
	import { type AnimeRatingRow } from '$lib/utils/ratingStats';
	import { ratingCoverage } from '$lib/stores/ratingCoverage';
	import { ratingsGridTier, COVERAGE_STYLE } from '$lib/utils/ratingCoverage';

	interface Props {
		row: AnimeRatingRow;
		nameLanguage: 'english' | 'japanese' | 'romaji';
		scoreDecimals: number;
	}

	let { row, nameLanguage, scoreDecimals }: Props = $props();

	let title = $derived(resolveTitle(row.title, row.name_eng, row.name_jap, nameLanguage));
	// Anime grain only: `row.anime_uuid` is the PARENT anime at media grain, so a
	// single rated side story would inherit the whole franchise's tier and every
	// sibling card would show it too. `media_uuid` is set exactly at media grain.
	let coverageTier = $derived(
		row.media_uuid ? null : ratingsGridTier($ratingCoverage.get(row.anime_uuid))
	);
	let coverage = $derived(coverageTier ? COVERAGE_STYLE[coverageTier] : null);
	let imgFailed = $state(false);
	// Anime covers are never spoiler-protected (per the spoiler rules), so no SpoilerGuard.
	// Media grain → link to the media page; anime grain → the anime page.
	let href = $derived(
		row.media_uuid
			? buildDetailHref('media', row.media_uuid, { from: 'ratings' })
			: buildDetailHref('anime', row.anime_uuid, { from: 'ratings' }),
	);
</script>

<a {href} data-focus-uuid={row.detailUuid} class="group block transition duration-200 hover:-translate-y-0.5">
	<!-- `outline`, not `box-shadow`: it hugs this element's own border box (so no
	     gap opens up the way it does on the wrapping <a>, which is a different
	     box), and it is a separate property from the composed `shadow-sm` +
	     `group-hover:` chain below, which an inline box-shadow would beat. The
	     1px border carries the second tone. -->
	<div
		class="{cls.cardGlass} rounded-xl overflow-hidden border border-border h-full flex flex-col shadow-sm group-hover:shadow-md group-hover:ring-1 group-hover:ring-primary/40 transition"
		style:outline={coverage ? `2px solid ${coverage.edge}` : undefined}
		style:border-color={coverage?.hairline}
		data-coverage={coverageTier}
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
				<div class="w-full aspect-[2/3] bg-muted flex items-center justify-center text-muted-foreground text-sm italic">
					No image
				</div>
			{/if}

			<!-- Gradient scrim so the score reads over any cover -->
			<div class="absolute inset-x-0 top-0 h-14 bg-gradient-to-b from-black/55 to-transparent pointer-events-none"></div>

			<!-- User's score, the headline of the card -->
			<span
				class="absolute top-1.5 right-1.5 rounded-md px-1.5 py-0.5 text-sm font-bold text-white shadow-md ring-1 ring-black/10"
				style="background-color: {scoreColor(row.userScore)}"
			>
				{formatDecimalDigits(row.userScore, scoreDecimals)}
			</span>

			{#if row.statusBadge === 'dropped'}
				<Badge variant="secondary" class="absolute top-1.5 left-1.5 text-[10px] h-5 {cls.badgeDropped}">Dropped</Badge>
			{:else if row.statusBadge === 'on_hold'}
				<Badge variant="secondary" class="absolute top-1.5 left-1.5 text-[10px] h-5 {cls.badgeOnHold}">On Hold</Badge>
			{/if}
		</div>

		<div class="p-2.5 flex flex-col gap-1.5 flex-grow" style:background={coverage?.band}>
			{#if coverage}
				<span class="sr-only">{coverage.label}</span>
			{/if}
			<h3
				class="text-sm font-medium text-card-foreground line-clamp-2 leading-snug"
				style:color={coverage?.foreground}
				title={title}
			>
				{title}
			</h3>
			<!-- Anime grain shows the main/side breakdown; media grain the media's relation
			     type (mutually exclusive) — mirrors WatchlistCard. -->
			<span class="mt-auto {cls.mutedPill}">
				{row.relationLabel ?? mainSideLabel(row.mainCount, row.sideCount)}
			</span>
		</div>
	</div>
</a>
