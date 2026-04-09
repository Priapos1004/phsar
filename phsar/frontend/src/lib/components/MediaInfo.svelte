<script lang="ts">
	import { formatNumber, formatAiringStatus } from '$lib/utils/formatString';
	import { buildDetailHref } from '$lib/utils/navigation';
	import { Bookmark } from 'lucide-svelte';
	import * as Card from '$lib/components/ui/card';
	import { Badge } from '$lib/components/ui/badge';
	import * as cls from '$lib/styles/classes';
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
		on_watchlist?: boolean;
		media_uuid: string;
		searchToken?: string | null;
	}

	let {
		info_type, title, score = null, scoredBy = null,
		anime_season = null, season_range = null, airing_status,
		has_upcoming = false, age_rating_numeric = null,
		genres = null, media_type = null, media_types = null,
		relation_type = null, relation_types = null, watchtime = null,
		imageUrl = null, on_watchlist = false, media_uuid, searchToken = null
	}: Props = $props();

	let imgFailed = $state(false);

	let href = $derived(buildDetailHref(info_type, media_uuid, searchToken));

	let displaySeason = $derived(season_range ?? anime_season);
	let displayStatus = $derived(formatAiringStatus(airing_status, has_upcoming));
</script>

<a
	{href}
	class="block transition duration-200 transform hover:scale-[1.015]"
>
	<Card.Root class="h-full bg-card/80 backdrop-blur">
		<Card.Content class="flex gap-4">
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

			<div class="flex flex-col justify-between flex-grow space-y-2">
				<div class="flex items-start justify-between">
					<div>
						<h3 class="text-lg font-bold text-card-foreground">{title}</h3>
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
					{#if on_watchlist}
						<Bookmark class="w-5 h-5 text-primary" fill="currentColor" />
					{/if}
				</div>

				{#if media_type || relation_type || media_types?.length || relation_types?.length || genres?.length}
					<div class="flex flex-wrap gap-2">
						{#if relation_types?.length}
							{#each relation_types as rt}
								<Badge variant="secondary" class={cls.badgeRelationType}>{rt.relation_type}: {rt.count}</Badge>
							{/each}
						{:else if relation_type}
							<Badge variant="secondary" class={cls.badgeRelationType}>{relation_type}</Badge>
						{/if}

						{#if media_types?.length}
							{#each media_types as mt}
								<Badge variant="secondary" class={cls.badgeMediaType}>{mt.media_type}: {mt.count}</Badge>
							{/each}
						{:else if media_type}
							<Badge variant="secondary" class={cls.badgeMediaType}>{media_type}</Badge>
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
