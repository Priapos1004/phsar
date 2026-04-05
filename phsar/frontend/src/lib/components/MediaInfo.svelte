<script lang="ts">
	import { formatNumber } from '$lib/utils/formatString';
	import { Bookmark } from 'lucide-svelte';
	import * as Card from '$lib/components/ui/card';
	import { Badge } from '$lib/components/ui/badge';
	import * as cls from '$lib/styles/classes';

	interface Props {
		info_type: string;
		title: string;
		score?: number | null;
		scoredBy?: number | null;
		anime_season?: string | null;
		airing_status: string;
		age_rating_numeric?: number | null;
		genres?: string[] | null;
		media_type: string;
		relation_type: string;
		watchtime?: string | null;
		imageUrl?: string | null;
		on_watchlist: boolean;
		media_uuid: string;
		searchToken?: string | null;
	}

	let {
		info_type, title, score = null, scoredBy = null,
		anime_season = null, airing_status, age_rating_numeric = null,
		genres = null, media_type, relation_type, watchtime = null,
		imageUrl = null, on_watchlist, media_uuid, searchToken = null
	}: Props = $props();

	let imgFailed = $state(false);

	let href = $derived(
		searchToken
			? `/${info_type}?uuid=${media_uuid}&q=${encodeURIComponent(searchToken)}`
			: `/${info_type}?uuid=${media_uuid}`
	);
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
						{#if anime_season || airing_status === 'Not yet aired' || airing_status === 'Currently Airing'}
							<p class="text-primary">
								{#if anime_season}
									{anime_season}
								{/if}

								{#if age_rating_numeric !== null}
									<span class="text-card-foreground px-1 py-0.5">
										{age_rating_numeric}+
									</span>
								{/if}

								{#if airing_status === 'Not yet aired' || airing_status === 'Currently Airing'}
									<span class="ml-2 text-sm text-primary/70">({airing_status})</span>
								{/if}
							</p>
						{/if}
					</div>
					{#if on_watchlist}
						<Bookmark class="w-5 h-5 text-primary" fill="currentColor" />
					{/if}
				</div>

				{#if media_type || relation_type || genres?.length}
					<div class="flex flex-wrap gap-2">
						{#if media_type}
							<Badge variant="secondary" class={cls.badgeMediaType}>{media_type}</Badge>
						{/if}

						{#if relation_type}
							<Badge variant="secondary" class={cls.badgeRelationType}>{relation_type}</Badge>
						{/if}

						{#each genres ?? [] as genre}
							<Badge variant="secondary" class={cls.badgeGenre}>{genre}</Badge>
						{/each}
					</div>
				{/if}

				<div class="flex justify-between text-sm text-muted-foreground">
					<span>{watchtime ? `Watch time: ${watchtime}` : 'Watch time: N/A'}</span>
					{#if score !== null && scoredBy !== null}
						<span>⭐ {score} — {formatNumber(scoredBy)} ratings</span>
					{:else}
						<span>No ratings</span>
					{/if}
				</div>
			</div>
		</Card.Content>
	</Card.Root>
</a>
