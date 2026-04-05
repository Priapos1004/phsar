<script lang="ts">
	import { page } from '$app/state';
	import { getContext } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { formatNumber, formatDuration, formatDecimalDigits, formatSeason } from '$lib/utils/formatString';
	import * as Card from '$lib/components/ui/card';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import RelatedMediaCarousel from '$lib/components/RelatedMediaCarousel.svelte';
	import RatingModal from '$lib/components/RatingModal.svelte';
	import { ExternalLink, Bookmark, Star } from 'lucide-svelte';
	import * as cls from '$lib/styles/classes';
	import type { MediaDetail, RatingOut } from '$lib/types/api';
	import { RATING_ATTRIBUTE_OPTIONS } from '$lib/types/api';

	const getUserRole = getContext<() => string | null>('userRole');

	let media = $state<MediaDetail | null>(null);
	let userRating = $state<RatingOut | null>(null);
	let loading = $state(true);
	let error = $state('');
	let showRatingModal = $state(false);
	let descriptionExpanded = $state(false);

	let isRestricted = $derived(getUserRole() === 'restricted_user');

	let filledAttributes = $derived(
		userRating ? Object.entries(RATING_ATTRIBUTE_OPTIONS)
			.filter(([key]) => (userRating as Record<string, unknown>)[key])
			.map(([key, config]) => ({
				label: config.label,
				value: config.options.find(o => o.value === (userRating as Record<string, unknown>)[key])?.label
					?? String((userRating as Record<string, unknown>)[key]),
			}))
		: []
	);

	$effect(() => {
		const uuid = page.url.searchParams.get('uuid');
		if (uuid) {
			loadMedia(uuid);
		}
	});

	async function loadMedia(uuid: string) {
		loading = true;
		error = '';
		media = null;
		userRating = null;

		try {
			const [mediaResult, ratingResult] = await Promise.allSettled([
				api.get<MediaDetail>(`/media/${uuid}`),
				api.get<RatingOut>(`/ratings/media/${uuid}`),
			]);

			if (mediaResult.status === 'rejected') throw mediaResult.reason;
			media = mediaResult.value;

			if (ratingResult.status === 'fulfilled') {
				userRating = ratingResult.value;
			} else if (ratingResult.reason instanceof ApiError && ratingResult.reason.status === 404) {
				userRating = null;
			} else {
				throw ratingResult.reason;
			}
		} catch (err) {
			error = err instanceof ApiError ? err.detail : 'Failed to load media';
		} finally {
			loading = false;
		}
	}

	function handleRatingSaved(rating: RatingOut) {
		userRating = rating;
	}

	function handleRatingDeleted() {
		userRating = null;
	}
</script>

<div class={`${cls.container} ${cls.sectionSpacing} py-4`}>
	{#if loading}
		<div class="flex justify-center py-20">
			<div class="animate-pulse text-muted-foreground">Loading...</div>
		</div>
	{:else if error}
		<div class="text-center text-destructive py-20">{error}</div>
	{:else if media}
		<Card.Root class={cls.cardGlass}>
			<Card.Content class="flex flex-col md:flex-row gap-6">
				<div class="shrink-0">
					{#if media.cover_image}
						<img
							src={media.cover_image}
							alt={`Cover of ${media.title}`}
							class="w-48 h-auto object-cover rounded-lg shadow-md mx-auto md:mx-0"
						/>
					{:else}
						<div class="w-48 h-72 bg-muted rounded-lg flex items-center justify-center text-muted-foreground italic">
							No image
						</div>
					{/if}
				</div>

				<div class="flex-1 space-y-4">
					<div>
						<h1 class="text-2xl font-bold text-card-foreground">
							{media.name_eng ?? media.title}
						</h1>
						{#if media.name_eng && media.name_eng !== media.title}
							<p class="text-sm text-muted-foreground">{media.title}</p>
						{/if}
						{#if media.name_jap}
							<p class="text-sm text-muted-foreground">{media.name_jap}</p>
						{/if}
					</div>

					{#if media.score !== null}
						<div class="flex items-center gap-2">
							<Star class="size-5 text-yellow-500" fill="currentColor" />
							<span class="text-lg font-semibold text-card-foreground">
								{formatDecimalDigits(media.score, 2)}
							</span>
							<span class="text-sm text-muted-foreground">
								/ 10 — {formatNumber(media.scored_by)} ratings
							</span>
						</div>
					{:else}
						<p class="text-sm text-muted-foreground">No score yet</p>
					{/if}

					<div class="flex flex-wrap gap-2">
						<Badge variant="secondary" class={cls.badgeMediaType}>{media.media_type}</Badge>
						<Badge variant="secondary" class={cls.badgeRelationType}>{media.relation_type}</Badge>
						{#if media.age_rating_numeric !== null}
							<Badge variant="secondary" class={cls.badgeAgeRating}>{media.age_rating_numeric}+</Badge>
						{/if}
					</div>

					{#if media.genres.length}
						<div class="flex flex-wrap gap-1.5">
							{#each media.genres as genre}
								<Badge variant="secondary" class="{cls.badgeGenre} text-xs">{genre}</Badge>
							{/each}
						</div>
					{/if}

					{#if media.studio.length}
						<p class="text-sm text-card-foreground">
							<span class="text-muted-foreground">Studio:</span>
							{media.studio.join(', ')}
						</p>
					{/if}

					<div class="flex flex-wrap gap-x-6 gap-y-1 text-sm text-card-foreground">
						{#if media.episodes !== null}
							<span>{media.episodes} episode{media.episodes !== 1 ? 's' : ''}</span>
						{/if}
						{#if media.duration}
							<span>{media.duration}</span>
						{/if}
						{#if media.total_watch_time !== null}
							<span>Total: {formatDuration(media.total_watch_time)}</span>
						{/if}
						{#if formatSeason(media.anime_season_name, media.anime_season_year)}
							<span>{formatSeason(media.anime_season_name, media.anime_season_year)}</span>
						{/if}
						<span class="text-muted-foreground">{media.airing_status}</span>
					</div>

					<a
						href={media.mal_url}
						target="_blank"
						rel="noopener noreferrer"
						class="inline-flex items-center gap-1 text-sm text-primary hover:underline"
					>
						View on MyAnimeList <ExternalLink class="size-3.5" />
					</a>

					<div class="border-t border-border pt-4 space-y-3">
						{#if userRating && !isRestricted}
							<div class="space-y-2">
								<div class="flex items-center gap-2">
									<Star class="size-4 text-primary" fill="currentColor" />
									<span class="font-semibold text-card-foreground">
										{formatDecimalDigits(userRating.rating, 1)} / 10
									</span>
									{#if userRating.dropped}
										<Badge variant="destructive" class="text-xs">Dropped</Badge>
									{:else}
										<span class="text-xs text-muted-foreground">Completed</span>
									{/if}
									{#if userRating.episodes_watched !== null}
										<span class="text-xs text-muted-foreground">
											· {userRating.episodes_watched} eps watched
										</span>
									{/if}
								</div>

								{#if filledAttributes.length}
									<div class="flex flex-wrap gap-1.5">
										{#each filledAttributes as attr}
											<Badge variant="outline" class="text-xs">
												{attr.label}: {attr.value}
											</Badge>
										{/each}
									</div>
								{/if}

								{#if userRating.note}
									<p class="text-sm text-muted-foreground italic line-clamp-2">
										"{userRating.note}"
									</p>
								{/if}
							</div>
						{/if}

						<div class="flex gap-2">
							{#if isRestricted}
								<Button disabled title="Upgrade your account to rate media">
									Rate This
								</Button>
								<Button variant="outline" disabled title="Upgrade your account to save media">
									<Bookmark class="size-4 mr-1" /> Watchlist
								</Button>
							{:else}
								<Button onclick={() => (showRatingModal = true)}>
									{userRating ? 'Edit Rating' : 'Rate This'}
								</Button>
								<!-- Wired up in v0.15.0 -->
								<Button variant="outline" disabled title="Coming soon">
									<Bookmark class="size-4 mr-1" /> Watchlist
								</Button>
							{/if}
						</div>
					</div>
				</div>
			</Card.Content>
		</Card.Root>

		{#if media.description}
			<Card.Root class={cls.cardGlass}>
				<Card.Content>
					<h2 class="text-lg font-semibold text-card-foreground mb-2">Synopsis</h2>
					<div
						class="text-sm text-card-foreground leading-relaxed {descriptionExpanded ? '' : 'line-clamp-4'}"
					>
						{media.description}
					</div>
					{#if media.description.length > 300}
						<button
							class="text-sm text-primary hover:underline mt-1"
							onclick={() => (descriptionExpanded = !descriptionExpanded)}
						>
							{descriptionExpanded ? 'Show less' : 'Read more'}
						</button>
					{/if}
				</Card.Content>
			</Card.Root>
		{/if}

		{#if media.sibling_media.length}
			<Card.Root class={cls.cardGlass}>
				<Card.Content>
					<h2 class="text-lg font-semibold text-card-foreground mb-1">Related Media</h2>
					<p class="text-sm text-muted-foreground mb-3">
						Part of: <span class="text-primary font-medium">{media.anime_title}</span>
					</p>
					<RelatedMediaCarousel siblings={media.sibling_media} />
				</Card.Content>
			</Card.Root>
		{/if}

		{#if !isRestricted}
			<RatingModal
				bind:open={showRatingModal}
				mediaUuid={media.uuid}
				mediaTitle={media.name_eng ?? media.title}
				totalEpisodes={media.episodes}
				existingRating={userRating}
				onSaved={handleRatingSaved}
				onDeleted={handleRatingDeleted}
			/>
		{/if}
	{/if}
</div>
