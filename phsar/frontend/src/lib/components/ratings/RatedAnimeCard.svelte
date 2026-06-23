<script lang="ts">
	import { Badge } from '$lib/components/ui/badge';
	import { scoreColor } from '$lib/utils/chartColors';
	import { formatDecimalDigits, resolveTitle } from '$lib/utils/formatString';
	import { buildDetailHref } from '$lib/utils/navigation';
	import * as cls from '$lib/styles/classes';
	import type { AnimeRatingRow } from '$lib/utils/ratingStats';

	interface Props {
		row: AnimeRatingRow;
		nameLanguage: 'english' | 'japanese' | 'romaji';
		scoreDecimals: number;
	}

	let { row, nameLanguage, scoreDecimals }: Props = $props();

	let title = $derived(resolveTitle(row.title, row.name_eng, row.name_jap, nameLanguage));
	let imgFailed = $state(false);
	// Anime covers are never spoiler-protected (per the spoiler rules), so no SpoilerGuard.
	let href = $derived(buildDetailHref('anime', row.anime_uuid, { from: 'ratings' }));
</script>

<a {href} class="group block transition duration-200 hover:-translate-y-0.5">
	<div class="{cls.cardGlass} rounded-xl overflow-hidden border border-border h-full flex flex-col shadow-sm group-hover:shadow-md group-hover:ring-1 group-hover:ring-primary/40 transition">
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
				<Badge variant="destructive" class="absolute top-1.5 left-1.5 text-[10px] h-5">Dropped</Badge>
			{:else if row.statusBadge === 'on_hold'}
				<Badge variant="secondary" class="absolute top-1.5 left-1.5 text-[10px] h-5 {cls.badgeOnHold}">On Hold</Badge>
			{/if}
		</div>

		<div class="p-2.5 flex flex-col gap-1.5 flex-grow">
			<h3 class="text-sm font-medium text-card-foreground line-clamp-2 leading-snug" title={title}>
				{title}
			</h3>
			<div class="mt-auto flex items-center gap-2 flex-wrap text-[11px]">
				{#if row.ratedMediaCount > 1}
					<span class="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">{row.ratedMediaCount} rated</span>
				{/if}
				{#if row.malDelta !== null}
					<span class="font-medium {row.malDelta >= 0 ? 'text-emerald-600' : 'text-rose-600'}">
						{row.malDelta >= 0 ? '+' : ''}{formatDecimalDigits(row.malDelta, 1)} vs MAL
					</span>
				{/if}
			</div>
		</div>
	</div>
</a>
