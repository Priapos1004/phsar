<script lang="ts">
	import { page } from '$app/state';
	import { getContext } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { formatNumber, formatDuration, formatDecimalDigits, formatSeason, cleanDescription, resolveTitle, resolveSubtitles } from '$lib/utils/formatString';
	import { buildDetailHref } from '$lib/utils/navigation';
	import * as Card from '$lib/components/ui/card';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import RelatedMediaCarousel from '$lib/components/RelatedMediaCarousel.svelte';
	import RatingCard from '$lib/components/RatingCard.svelte';
	import { ArrowLeft, Bookmark, Star, Tv, Clock, Calendar, Film } from 'lucide-svelte';
	import * as cls from '$lib/styles/classes';
	import { userSettings } from '$lib/stores/userSettings';
	import type { MediaDetail, RatingOut } from '$lib/types/api';

	const getUserRole = getContext<() => string | null>('userRole');
	let nameLanguage = $derived($userSettings?.name_language ?? 'english');

	let media = $state<MediaDetail | null>(null);
	let userRating = $state<RatingOut | null>(null);
	let loading = $state(true);
	let error = $state('');
	let descriptionExpanded = $state(false);
	let coverFailed = $state(false);
	let loadRequestId = 0;

	let isRestricted = $derived(getUserRole() === 'restricted_user');
	let searchToken = $derived(page.url.searchParams.get('q'));

	let cleanedDescription = $derived(media?.description ? cleanDescription(media.description) : null);
	let mediaSeason = $derived(media ? formatSeason(media.anime_season_name, media.anime_season_year) : null);

	$effect(() => {
		const uuid = page.url.searchParams.get('uuid');
		if (uuid) {
			loadMedia(uuid);
		} else {
			loading = false;
			error = 'No media UUID provided';
		}
	});

	async function loadMedia(uuid: string) {
		const thisRequest = ++loadRequestId;
		loading = true;
		error = '';
		media = null;
		userRating = null;
		coverFailed = false;

		try {
			const [mediaResult, ratingResult] = await Promise.allSettled([
				api.get<MediaDetail>(`/media/${uuid}`),
				api.get<RatingOut>(`/ratings/media/${uuid}`),
			]);

			// Discard stale response if user navigated to a different media
			if (thisRequest !== loadRequestId) return;

			if (mediaResult.status === 'rejected') throw mediaResult.reason;
			media = mediaResult.value;

			if (ratingResult.status === 'fulfilled') {
				userRating = ratingResult.value;
			} else if (
				ratingResult.reason instanceof ApiError &&
				(ratingResult.reason.status === 404 || ratingResult.reason.status === 403)
			) {
				// 404 = no rating yet, 403 = restricted user (can't rate)
				userRating = null;
			} else {
				throw ratingResult.reason;
			}
		} catch (err) {
			if (thisRequest !== loadRequestId) return;
			error = err instanceof ApiError ? err.detail : 'Failed to load media';
		} finally {
			if (thisRequest === loadRequestId) loading = false;
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
		{#if searchToken}
			<a
				href={`/search?q=${encodeURIComponent(searchToken)}`}
				class="inline-flex items-center gap-1.5 text-sm text-white/70 hover:text-white transition mb-2"
			>
				<ArrowLeft class="size-4" /> Back to search
			</a>
		{/if}

		<div class="relative rounded-xl overflow-hidden">
			{#if media.cover_image && !coverFailed}
				<div class="absolute inset-0">
					<img
						src={media.cover_image}
						alt=""
						class="w-full h-full object-cover scale-110 blur-2xl opacity-40"
						onerror={() => { coverFailed = true; }}
					/>
					<div class="absolute inset-0 bg-card/75 backdrop-blur-sm"></div>
				</div>
			{:else}
				<div class="absolute inset-0 bg-card/85"></div>
			{/if}

			<div class="relative flex flex-col md:flex-row gap-6 p-6">
				<div class="shrink-0 flex flex-col items-center md:items-start">
					{#if media.cover_image && !coverFailed}
						<img
							src={media.cover_image}
							alt={`Cover of ${media.title}`}
							class="w-44 h-auto rounded-lg shadow-xl ring-1 ring-border"
							onerror={() => { coverFailed = true; }}
						/>
					{:else}
						<div class="w-44 h-64 bg-muted rounded-lg flex items-center justify-center text-muted-foreground italic">
							No image
						</div>
					{/if}
				</div>

				<div class="flex-1 space-y-4 min-w-0">
					<div class="flex items-start justify-between gap-4">
						<div class="min-w-0">
							<h1 class="text-2xl md:text-3xl font-bold text-card-foreground leading-tight">
								{resolveTitle(media.title, media.name_eng, media.name_jap, nameLanguage)}
							</h1>
							{#if media.airing_status === 'Currently Airing'}
								<span class="inline-flex items-center gap-1.5 mt-1.5 px-2.5 py-1 rounded-md font-semibold bg-green-100 text-green-800 border border-green-200">
									<span class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
									{media.airing_status}
								</span>
							{:else if media.airing_status === 'Not yet aired'}
								<span class="inline-block mt-1.5 px-2.5 py-1 rounded-md font-semibold bg-yellow-100 text-yellow-800 border border-yellow-200">
									{media.airing_status}
								</span>
							{:else}
								<span class="inline-block mt-1.5 px-2.5 py-1 rounded-md font-medium bg-muted text-muted-foreground">
									{media.airing_status}
								</span>
							{/if}
							{#each resolveSubtitles(media.title, media.name_eng, media.name_jap, nameLanguage) as subtitle, i}
								<p class="text-sm {i === 0 ? 'text-muted-foreground mt-1' : 'text-muted-foreground/70'}">{subtitle}</p>
							{/each}
						</div>

						<!-- Watchlist bookmark placeholder -->
						<button
							class="shrink-0 p-2 rounded-lg opacity-50 cursor-not-allowed"
							disabled
							title="Coming soon"
						>
							<Bookmark class="size-6 text-muted-foreground" />
						</button>
					</div>

					{#if media.score !== null}
						<div class="flex items-center gap-3">
							<div class="flex items-center gap-1.5 bg-primary/10 rounded-full px-3 py-1.5">
								<Star class="size-4 text-yellow-500" fill="currentColor" />
								<span class="text-lg font-bold text-card-foreground">
									{formatDecimalDigits(media.score, 2)}
								</span>
								<span class="text-muted-foreground">/ 10</span>
							</div>
							<span class="text-muted-foreground">
								{formatNumber(media.scored_by)} ratings
							</span>
						</div>
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
								<Badge variant="secondary" class={cls.badgeGenre}>{genre}</Badge>
							{/each}
						</div>
					{/if}

					<div class="grid grid-cols-2 md:grid-cols-4 gap-3 pt-1">
						{#if media.episodes !== null}
							<div class="flex items-center gap-2 text-card-foreground">
								<Tv class="size-4 text-primary shrink-0" />
								<span>{media.episodes} ep{media.episodes !== 1 ? 's' : ''}</span>
							</div>
						{/if}
						{#if media.duration_seconds}
							<div class="flex items-center gap-2 text-card-foreground">
								<Clock class="size-4 text-primary shrink-0" />
								<span>{formatDuration(media.duration_seconds)} per ep</span>
							</div>
						{/if}
						{#if mediaSeason}
							<div class="flex items-center gap-2 text-card-foreground">
								<Calendar class="size-4 text-primary shrink-0" />
								<span>{mediaSeason}</span>
							</div>
						{/if}
						{#if media.total_watch_time !== null}
							<div class="flex items-center gap-2 text-card-foreground">
								<Film class="size-4 text-primary shrink-0" />
								<span>{formatDuration(media.total_watch_time)}</span>
							</div>
						{/if}
					</div>

					{#if media.studio.length}
						<div class="flex items-center gap-2">
							<span class="text-muted-foreground font-medium">Studio</span>
							{#each media.studio as studio}
								<span class="px-2.5 py-0.5 rounded-md font-medium bg-card-foreground/8 text-card-foreground border border-border">
									{studio}
								</span>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		</div>

		{#if cleanedDescription}
			<Card.Root class={cls.cardGlass}>
				<Card.Content>
					<h2 class="text-lg font-semibold text-card-foreground mb-2">Synopsis</h2>
					<div
						class="text-card-foreground leading-relaxed {descriptionExpanded ? '' : 'line-clamp-4'}"
					>
						{cleanedDescription}
					</div>
					{#if cleanedDescription.length > 300}
						<button
							class="text-primary hover:underline mt-1"
							onclick={() => (descriptionExpanded = !descriptionExpanded)}
						>
							{descriptionExpanded ? 'Show less' : 'Read more'}
						</button>
					{/if}
				</Card.Content>
			</Card.Root>
		{/if}

		{#if !isRestricted}
			<RatingCard
				mediaUuid={media.uuid}
				totalEpisodes={media.episodes}
				existingRating={userRating}
				onSaved={handleRatingSaved}
				onDeleted={handleRatingDeleted}
			/>
		{:else}
			<Card.Root class={cls.cardGlass}>
				<Card.Content>
					<div class="flex items-center justify-between">
						<h2 class="text-lg font-semibold text-card-foreground">Your Rating</h2>
						<Button disabled>Rate This</Button>
					</div>
					<p class="text-muted-foreground mt-1">You don't have permission to rate media</p>
				</Card.Content>
			</Card.Root>
		{/if}

		<Card.Root class={cls.cardGlass}>
			<Card.Content>
				<h2 class="text-lg font-semibold text-card-foreground mb-1">Related Media</h2>
				<p class="text-muted-foreground {media.sibling_media.length ? 'mb-3' : ''}">
					Part of anime:
					<a
						href={buildDetailHref('anime', media.anime_uuid, searchToken)}
						class="text-primary font-medium hover:underline"
					>{resolveTitle(media.anime_title, media.anime_name_eng, media.anime_name_jap, nameLanguage)}</a>
				</p>
				{#if media.sibling_media.length}
					<RelatedMediaCarousel siblings={media.sibling_media} {searchToken} />
				{:else}
					<p class="text-muted-foreground/70 text-sm mt-2">No other media in this anime</p>
				{/if}
			</Card.Content>
		</Card.Root>
	{/if}
</div>
