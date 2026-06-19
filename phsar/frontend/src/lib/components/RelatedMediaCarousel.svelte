<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import { Badge } from '$lib/components/ui/badge';
	import { formatSeason, resolveTitle, formatRelationType, formatMediaType, formatAiringStatus } from '$lib/utils/formatString';
	import { buildDetailHref, type DetailOrigin } from '$lib/utils/navigation';
	import { userSettings } from '$lib/stores/userSettings';
	import SpoilerGuard from '$lib/components/SpoilerGuard.svelte';
	import { visibleMediaSet } from '$lib/stores/spoilerVisibility';
	import * as cls from '$lib/styles/classes';
	import type { MediaSibling } from '$lib/types/api';

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');

	interface Props {
		siblings: MediaSibling[];
		/** Index in the chronological sibling chain where the current media slots.
		 * 0 = before every sibling, siblings.length = after the last. */
		currentPosition: number;
		searchToken?: string | null;
		fromParam?: DetailOrigin | null;
		jobUuid?: string | null;
	}

	let { siblings, currentPosition, searchToken = null, fromParam = null, jobUuid = null }: Props = $props();

	let imgFailed = $state<Record<string, boolean>>({});
</script>

{#snippet hereMarker()}
	<div
		role="separator"
		aria-label="Current media position in the chain"
		class="snap-start shrink-0 flex flex-col items-center justify-center gap-1 px-1"
	>
		<div class="w-0.5 flex-1 min-h-4 bg-primary/60"></div>
		<span class="rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wider font-semibold text-primary-foreground bg-primary whitespace-nowrap">You are here</span>
		<div class="w-0.5 flex-1 min-h-4 bg-primary/60"></div>
	</div>
{/snippet}

<div class="flex gap-3 overflow-x-auto snap-x snap-mandatory pb-2 no-scrollbar">
	{#each siblings as sibling, i}
		{#if i === currentPosition}{@render hereMarker()}{/if}
		<a
			href={buildDetailHref('media', sibling.uuid, { q: searchToken, from: fromParam, job: jobUuid })}
			class="snap-start shrink-0 w-40 transition duration-200 transform hover:scale-[1.03]"
		>
			<Card.Root class="h-full {cls.cardGlass}">
				<Card.Content class="p-3 space-y-2">
					<SpoilerGuard visible={$visibleMediaSet.has(sibling.uuid)} mode="image">
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
					</SpoilerGuard>

					<p class="text-xs font-semibold text-card-foreground line-clamp-2 leading-tight">
						{resolveTitle(sibling.title, sibling.name_eng, sibling.name_jap, nameLanguage)}
					</p>

					<div class="flex flex-wrap gap-1">
						<Badge variant="secondary" class="text-[11px] px-1.5 py-0 {cls.badgeMediaTypeColor}">
							{formatMediaType(sibling.media_type)}
						</Badge>
						<Badge variant="secondary" class="text-[11px] px-1.5 py-0 {cls.badgeRelationTypeColor}">
							{formatRelationType(sibling.relation_type)}
						</Badge>
					</div>

					{@const season = formatSeason(sibling.anime_season_name, sibling.anime_season_year)}
					<p class="text-[11px] text-muted-foreground">
						{#if season}
							{season}
						{:else if sibling.episodes != null}
							{sibling.episodes} eps
						{:else}
							{formatAiringStatus(sibling.airing_status, false)}
						{/if}
					</p>
				</Card.Content>
			</Card.Root>
		</a>
	{/each}
	{#if currentPosition === siblings.length}{@render hereMarker()}{/if}
</div>
