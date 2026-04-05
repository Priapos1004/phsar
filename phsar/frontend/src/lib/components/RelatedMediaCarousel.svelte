<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import { Badge } from '$lib/components/ui/badge';
	import { formatSeason } from '$lib/utils/formatString';
	import * as cls from '$lib/styles/classes';
	import type { MediaSibling } from '$lib/types/api';

	interface Props {
		siblings: MediaSibling[];
	}

	let { siblings }: Props = $props();

	let imgFailed = $state<Record<string, boolean>>({});
</script>

<div class="flex gap-3 overflow-x-auto snap-x snap-mandatory pb-2 no-scrollbar">
	{#each siblings as sibling}
		<a
			href={`/media?uuid=${sibling.uuid}`}
			class="snap-start shrink-0 w-40 transition duration-200 transform hover:scale-[1.03]"
		>
			<Card.Root class="h-full {cls.cardGlass}">
				<Card.Content class="p-3 space-y-2">
					{#if sibling.cover_image && !imgFailed[sibling.uuid]}
						<img
							src={sibling.cover_image}
							alt={`Cover of ${sibling.title}`}
							class="w-full h-24 object-cover rounded"
							loading="lazy"
							onerror={() => { imgFailed[sibling.uuid] = true; }}
						/>
					{:else}
						<div class="w-full h-24 bg-muted rounded flex items-center justify-center text-muted-foreground text-xs italic">
							No image
						</div>
					{/if}

					<p class="text-xs font-semibold text-card-foreground line-clamp-2 leading-tight">
						{sibling.name_eng ?? sibling.title}
					</p>

					<div class="flex flex-wrap gap-1">
						<Badge variant="secondary" class="text-[11px] px-1.5 py-0 {cls.badgeMediaTypeColor}">
							{sibling.media_type}
						</Badge>
						<Badge variant="secondary" class="text-[11px] px-1.5 py-0 {cls.badgeRelationTypeColor}">
							{sibling.relation_type}
						</Badge>
					</div>

					{@const season = formatSeason(sibling.anime_season_name, sibling.anime_season_year)}
					<p class="text-[11px] text-muted-foreground">
						{#if season}
							{season}
						{:else}
							{sibling.episodes ?? '?'} eps
						{/if}
					</p>
				</Card.Content>
			</Card.Root>
		</a>
	{/each}
</div>
