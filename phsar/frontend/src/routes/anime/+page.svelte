<script lang="ts">
	import { page } from '$app/state';
	import { getContext } from 'svelte';
	import { api, ApiError } from '$lib/api';
	import { formatNumber, formatDuration, formatDecimalDigits, formatSeason, cleanDescription, formatAiringStatus } from '$lib/utils/formatString';
	import { buildDetailHref } from '$lib/utils/navigation';
	import * as Card from '$lib/components/ui/card';
	import { Badge } from '$lib/components/ui/badge';
	import { Button } from '$lib/components/ui/button';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import * as Dialog from '$lib/components/ui/dialog';
	import { ArrowLeft, Bookmark, Star, Tv, Calendar, Film, Layers, X, ListChecks, BookmarkPlus, Trash2 } from 'lucide-svelte';
	import * as cls from '$lib/styles/classes';
	import type { AnimeDetail, AnimeMediaItem, RatingOut } from '$lib/types/api';
	import RatingsOverview from '$lib/components/RatingsOverview.svelte';
	import BulkRateDialog from '$lib/components/BulkRateDialog.svelte';

	const getUserRole = getContext<() => string | null>('userRole');

	let anime = $state<AnimeDetail | null>(null);
	let loading = $state(true);
	let error = $state('');
	let descriptionExpanded = $state(false);
	let coverFailed = $state(false);
	let loadRequestId = 0;

	let userRatingsList = $state<RatingOut[]>([]);
	let userRatings = $derived(new Map(userRatingsList.map(r => [r.media_uuid, r.rating])));
	let selectMode = $state(false);
	let selectedUuids = $state<Set<string>>(new Set());

	let showRateDialog = $state(false);
	let showDeleteDialog = $state(false);
	let showWatchlistDialog = $state(false);

	let bulkDeleting = $state(false);
	let bulkDeleteError = $state('');

	let alreadyRatedCount = $derived(
		[...selectedUuids].filter(uuid => userRatings.has(uuid)).length
	);

	let showNoteDialog = $state(false);
	let noteDialogMedia = $state('');

	let bulkRateDialog = $state<BulkRateDialog>();

	function openBulkRateDialog() {
		bulkRateDialog?.reset();
		showRateDialog = true;
	}

	function handleBulkRateSaved(results: RatingOut[], note: string) {
		showRateDialog = false;
		selectMode = false;
		selectedUuids = new Set();

		// Show which media got the note
		if (note) {
			const noteRating = results.find(r => r.note);
			if (noteRating) {
				const mediaItem = anime?.media.find(m => m.uuid === noteRating.media_uuid);
				noteDialogMedia = mediaItem?.name_eng ?? noteRating.media_title;
				showNoteDialog = true;
			}
		}

		refreshUserRatings();
	}

	async function handleBulkDelete() {
		bulkDeleting = true;
		bulkDeleteError = '';

		try {
			await api.post('/ratings/bulk-delete', { media_uuids: [...selectedUuids] });
			showDeleteDialog = false;
			selectMode = false;
			selectedUuids = new Set();
			await refreshUserRatings();
		} catch (err) {
			bulkDeleteError = err instanceof ApiError ? err.detail : 'Failed to delete ratings';
		} finally {
			bulkDeleting = false;
		}
	}

	let isRestricted = $derived(getUserRole() === 'restricted_user');
	let searchToken = $derived(page.url.searchParams.get('q'));

	let cleanedDescription = $derived(anime?.description ? cleanDescription(anime.description) : null);

	let displayStatus = $derived(
		anime ? formatAiringStatus(anime.airing_status, anime.has_upcoming) : ''
	);

	let allSelected = $derived(anime ? selectedUuids.size === anime.media.length : false);
	let someSelected = $derived(selectedUuids.size > 0);

	$effect(() => {
		const uuid = page.url.searchParams.get('uuid');
		if (uuid) {
			loadAnime(uuid);
		} else {
			loading = false;
			error = 'No anime UUID provided';
		}
	});

	async function loadAnime(uuid: string) {
		const thisRequest = ++loadRequestId;
		loading = true;
		error = '';
		anime = null;
		userRatingsList = [];
		coverFailed = false;
		selectMode = false;
		selectedUuids = new Set();

		try {
			const [animeResult, ratingsResult] = await Promise.allSettled([
				api.get<AnimeDetail>(`/media/anime/${uuid}`),
				api.get<RatingOut[]>(`/ratings/anime/${uuid}`),
			]);

			if (thisRequest !== loadRequestId) return;

			if (animeResult.status === 'rejected') throw animeResult.reason;
			anime = animeResult.value;

			if (ratingsResult.status === 'fulfilled') {
				userRatingsList = ratingsResult.value;
			}
			// 403/401 = not logged in or restricted — silently ignore
		} catch (err) {
			if (thisRequest !== loadRequestId) return;
			error = err instanceof ApiError ? err.detail : 'Failed to load anime';
		} finally {
			if (thisRequest === loadRequestId) loading = false;
		}
	}

	async function refreshUserRatings() {
		if (!anime) return;
		try {
			const ratings = await api.get<RatingOut[]>(`/ratings/anime/${anime.uuid}`);
			userRatingsList = ratings;
		} catch {
			// silently ignore — user may not be logged in
		}
	}

	function toggleSelectMode() {
		selectMode = !selectMode;
		if (!selectMode) selectedUuids = new Set();
	}

	function toggleMedia(uuid: string) {
		const next = new Set(selectedUuids);
		if (next.has(uuid)) next.delete(uuid);
		else next.add(uuid);
		selectedUuids = next;
	}

	function toggleAll() {
		if (!anime) return;
		if (allSelected) {
			selectedUuids = new Set();
		} else {
			selectedUuids = new Set(anime.media.map(m => m.uuid));
		}
	}

	function mediaHref(item: AnimeMediaItem): string {
		return buildDetailHref('media', item.uuid, searchToken);
	}

	function imgFailed(e: Event) {
		const img = e.target as HTMLImageElement;
		img.style.display = 'none';
		const placeholder = img.nextElementSibling as HTMLElement;
		if (placeholder) placeholder.style.display = 'flex';
	}
</script>

<div class={`${cls.container} ${cls.sectionSpacing} py-4`}>
	{#if loading}
		<div class="flex justify-center py-20">
			<div class="animate-pulse text-muted-foreground">Loading...</div>
		</div>
	{:else if error}
		<div class="text-center text-destructive py-20">{error}</div>
	{:else if anime}
		{#if searchToken}
			<a
				href={`/search?q=${encodeURIComponent(searchToken)}`}
				class="inline-flex items-center gap-1.5 text-sm text-white/70 hover:text-white transition mb-2"
			>
				<ArrowLeft class="size-4" /> Back to search
			</a>
		{/if}

		<!-- Hero section -->
		<div class="relative rounded-xl overflow-hidden">
			{#if anime.cover_image && !coverFailed}
				<div class="absolute inset-0">
					<img
						src={anime.cover_image}
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
					{#if anime.cover_image && !coverFailed}
						<img
							src={anime.cover_image}
							alt={`Cover of ${anime.title}`}
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
								{anime.name_eng ?? anime.title}
							</h1>
							{#if anime.airing_status === 'Currently Airing'}
								<span class="inline-flex items-center gap-1.5 mt-1.5 px-2.5 py-1 rounded-md font-semibold bg-green-100 text-green-800 border border-green-200">
									<span class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
									{displayStatus}
								</span>
							{:else if anime.airing_status === 'Not yet aired'}
								<span class="inline-block mt-1.5 px-2.5 py-1 rounded-md font-semibold bg-yellow-100 text-yellow-800 border border-yellow-200">
									{displayStatus}
								</span>
							{:else}
								<span class="inline-block mt-1.5 px-2.5 py-1 rounded-md font-medium bg-muted text-muted-foreground">
									{displayStatus}
								</span>
							{/if}
							{#if anime.name_eng && anime.name_eng !== anime.title}
								<p class="text-sm text-muted-foreground mt-1">{anime.title}</p>
							{/if}
							{#if anime.name_jap}
								<p class="text-sm text-muted-foreground/70">{anime.name_jap}</p>
							{/if}
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

					{#if anime.avg_score !== null}
						<div class="flex items-center gap-3">
							<div class="flex items-center gap-1.5 bg-primary/10 rounded-full px-3 py-1.5">
								<Star class="size-4 text-yellow-500" fill="currentColor" />
								<span class="text-lg font-bold text-card-foreground">
									{formatDecimalDigits(anime.avg_score, 2)}
								</span>
								<span class="text-muted-foreground">/ 10</span>
							</div>
							<span class="text-muted-foreground">
								{formatNumber(anime.avg_scored_by)} ratings/media
							</span>
						</div>
					{/if}

					<div class="flex flex-wrap gap-2">
						{#each anime.relation_types as rt}
							<Badge variant="secondary" class={cls.badgeRelationType}>{rt.relation_type}: {rt.count}</Badge>
						{/each}
						{#each anime.media_types as mt}
							<Badge variant="secondary" class={cls.badgeMediaType}>{mt.media_type}: {mt.count}</Badge>
						{/each}
						{#if anime.age_rating_numeric !== null}
							<Badge variant="secondary" class={cls.badgeAgeRating}>{anime.age_rating_numeric}+</Badge>
						{/if}
					</div>

					{#if anime.genres.length}
						<div class="flex flex-wrap gap-1.5">
							{#each anime.genres as genre}
								<Badge variant="secondary" class={cls.badgeGenre}>{genre}</Badge>
							{/each}
						</div>
					{/if}

					<div class="grid grid-cols-2 md:grid-cols-4 gap-3 pt-1">
						{#if anime.total_episodes !== null}
							<div class="flex items-center gap-2 text-card-foreground">
								<Tv class="size-4 text-primary shrink-0" />
								<span>{anime.total_episodes} ep{anime.total_episodes !== 1 ? 's' : ''}</span>
							</div>
						{/if}
						<div class="flex items-center gap-2 text-card-foreground">
							<Layers class="size-4 text-primary shrink-0" />
							<span>{anime.media.length} media</span>
						</div>
						{#if anime.season_start}
							{@const isRange = anime.season_end && anime.season_end !== anime.season_start}
							<div class="flex items-start gap-2 text-card-foreground">
								<Calendar class="size-4 text-primary shrink-0 {isRange ? 'mt-0.5' : ''}" />
								{#if isRange}
									<div class="flex flex-col leading-tight">
										<span>{anime.season_start}</span>
										<span class="text-muted-foreground">{anime.season_end}</span>
									</div>
								{:else}
									<span>{anime.season_start}</span>
								{/if}
							</div>
						{/if}
						{#if anime.total_watch_time !== null}
							<div class="flex items-center gap-2 text-card-foreground">
								<Film class="size-4 text-primary shrink-0" />
								<span>{formatDuration(anime.total_watch_time)}</span>
							</div>
						{/if}
					</div>

					{#if anime.studios.length}
						<div class="flex items-center gap-2">
							<span class="text-muted-foreground font-medium">Studio</span>
							{#each anime.studios as studio}
								<span class="px-2.5 py-0.5 rounded-md font-medium bg-card-foreground/8 text-card-foreground border border-border">
									{studio}
								</span>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		</div>

		<!-- Synopsis -->
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

		{#if userRatingsList.length > 0 && anime}
			<RatingsOverview ratings={userRatingsList} media={anime.media} />
		{/if}

		<!-- Media table -->
		<Card.Root class={cls.cardGlass}>
			<Card.Content>
				<div class="flex items-center justify-between mb-4">
					<h2 class="text-lg font-semibold text-card-foreground">
						All Media ({anime.media.length})
					</h2>
					<button
						class="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition
							{selectMode ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-card-foreground'}"
						onclick={toggleSelectMode}
					>
						{#if selectMode}
							<X class="size-4" />
							Cancel
						{:else}
							<ListChecks class="size-4" />
							Select
						{/if}
					</button>
				</div>

				<!-- Floating action bar — slides in when items are selected -->
				{#if selectMode}
					<div class="flex items-center gap-3 mb-4 px-3 py-2.5 rounded-lg bg-primary/10 border border-primary/20">
						<button
							class="flex items-center gap-1.5 text-sm font-medium text-card-foreground hover:text-primary transition"
							onclick={toggleAll}
						>
							<Checkbox checked={allSelected} />
							{allSelected ? 'Deselect all' : 'Select all'}
						</button>

						<div class="h-5 w-px bg-border"></div>

						<span class="text-sm text-muted-foreground">
							{selectedUuids.size} selected
						</span>

						<div class="flex-1"></div>

						{#if someSelected}
							<Button
								size="sm"
								disabled={isRestricted}
								onclick={openBulkRateDialog}
							>
								<Star class="size-3.5 mr-1.5" />
								Rate
							</Button>
							<Button
								size="sm"
								variant="secondary"
								onclick={() => { showWatchlistDialog = true; }}
							>
								<BookmarkPlus class="size-3.5 mr-1.5" />
								Watchlist
							</Button>
							{#if alreadyRatedCount > 0}
								<Button
									size="sm"
									variant="destructive"
									onclick={() => { bulkDeleteError = ''; showDeleteDialog = true; }}
								>
									<Trash2 class="size-3.5 mr-1.5" />
									Delete Ratings
								</Button>
							{/if}
						{/if}
					</div>
				{/if}

				<!-- Compact media rows -->
				<div class="divide-y divide-border rounded-lg border border-border overflow-hidden">
					{#each anime.media as item}
						{@const isSelected = selectedUuids.has(item.uuid)}
						<div
							class="flex items-center gap-3 px-3 py-2 transition
								{selectMode ? (isSelected ? 'bg-primary/8' : 'hover:bg-muted/50 cursor-pointer') : 'hover:bg-muted/50'}"
							onclick={() => {
								if (selectMode) toggleMedia(item.uuid);
								else window.location.href = mediaHref(item);
							}}
							role={selectMode ? 'checkbox' : 'link'}
							aria-checked={selectMode ? isSelected : undefined}
							tabindex="0"
							onkeydown={(e) => {
								if (e.key === 'Enter' || e.key === ' ') {
									e.preventDefault();
									if (selectMode) toggleMedia(item.uuid);
									else window.location.href = mediaHref(item);
								}
							}}
						>
							<!-- Checkbox / row number -->
							{#if selectMode}
								<div class="shrink-0 w-6 flex justify-center">
									<Checkbox checked={isSelected} />
								</div>
							{/if}

							<!-- Cover thumbnail -->
							{#if item.cover_image}
								<img
									src={item.cover_image}
									alt=""
									class="w-10 h-14 object-cover rounded shadow-sm shrink-0"
									loading="lazy"
									onerror={imgFailed}
								/>
								<div class="w-10 h-14 bg-muted rounded flex items-center justify-center text-muted-foreground text-xs shrink-0" style="display:none">
									?
								</div>
							{:else}
								<div class="w-10 h-14 bg-muted rounded flex items-center justify-center text-muted-foreground text-xs shrink-0">
									?
								</div>
							{/if}

							<!-- Title + badges -->
							<div class="flex-1 min-w-0">
								<p class="font-medium text-card-foreground truncate">
									{item.name_eng ?? item.title}
								</p>
								<div class="flex items-center gap-1.5 mt-0.5 flex-wrap">
									<Badge variant="secondary" class={`${cls.badgeRelationTypeColor} text-xs px-1.5 py-0`}>{item.relation_type}</Badge>
									<Badge variant="secondary" class={`${cls.badgeMediaTypeColor} text-xs px-1.5 py-0`}>{item.media_type}</Badge>
									{#if item.episodes}
										<span class="text-xs text-muted-foreground">{item.episodes} ep{item.episodes !== 1 ? 's' : ''}</span>
									{/if}
								</div>
							</div>

							<!-- Season -->
							<div class="hidden sm:block text-sm text-muted-foreground whitespace-nowrap">
								{formatSeason(item.anime_season_name, item.anime_season_year) ?? ''}
							</div>

							<!-- User rating -->
							<div class="text-sm text-card-foreground whitespace-nowrap w-12 text-right">
								{#if userRatings.has(item.uuid)}
									<span class="font-medium">{formatDecimalDigits(userRatings.get(item.uuid)!, 1)}</span>
								{:else}
									<span class="text-muted-foreground">--</span>
								{/if}
							</div>

							<!-- Status indicator -->
							<div class="shrink-0 w-2">
								{#if item.airing_status === 'Currently Airing'}
									<div class="w-2 h-2 rounded-full bg-green-500 animate-pulse" title="Currently Airing"></div>
								{:else if item.airing_status === 'Not yet aired'}
									<div class="w-2 h-2 rounded-full bg-yellow-500" title="Not yet aired"></div>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			</Card.Content>
		</Card.Root>

		<!-- Bulk rating dialog -->
		<BulkRateDialog
			bind:this={bulkRateDialog}
			bind:open={showRateDialog}
			{selectedUuids}
			{alreadyRatedCount}
			onSaved={handleBulkRateSaved}
		/>

		<Dialog.Root bind:open={showWatchlistDialog}>
			<Dialog.Content>
				<Dialog.Header>
					<Dialog.Title>{selectMode && someSelected ? `Add ${selectedUuids.size} to Watchlist` : 'Add All to Watchlist'}</Dialog.Title>
					<Dialog.Description>
						Watchlist features will be available in a future update.
					</Dialog.Description>
				</Dialog.Header>
				<Dialog.Footer>
					<Button onclick={() => { showWatchlistDialog = false; }}>OK</Button>
				</Dialog.Footer>
			</Dialog.Content>
		</Dialog.Root>

		<!-- Note placement info dialog -->
		<Dialog.Root bind:open={showNoteDialog}>
			<Dialog.Content class="bg-card text-card-foreground">
				<Dialog.Header>
					<Dialog.Title class="text-card-foreground">Note Added</Dialog.Title>
					<Dialog.Description class="text-muted-foreground">
						Your note was added to: <span class="font-medium text-card-foreground">{noteDialogMedia}</span>
					</Dialog.Description>
				</Dialog.Header>
				<Dialog.Footer>
					<Button onclick={() => { showNoteDialog = false; }}>OK</Button>
				</Dialog.Footer>
			</Dialog.Content>
		</Dialog.Root>

		<!-- Bulk delete confirmation dialog -->
		<Dialog.Root bind:open={showDeleteDialog}>
			<Dialog.Content class="bg-card text-card-foreground">
				<Dialog.Header>
					<Dialog.Title class="text-card-foreground">Delete Ratings</Dialog.Title>
					<Dialog.Description class="text-muted-foreground">
						This will permanently delete {alreadyRatedCount} rating{alreadyRatedCount !== 1 ? 's' : ''} from the selected media. This cannot be undone.
					</Dialog.Description>
				</Dialog.Header>
				{#if bulkDeleteError}
					<p class="text-destructive text-sm">{bulkDeleteError}</p>
				{/if}
				<Dialog.Footer>
					<Button variant="secondary" onclick={() => { showDeleteDialog = false; }} disabled={bulkDeleting}>
						Cancel
					</Button>
					<Button variant="destructive" onclick={handleBulkDelete} disabled={bulkDeleting}>
						{bulkDeleting ? 'Deleting...' : 'Delete'}
					</Button>
				</Dialog.Footer>
			</Dialog.Content>
		</Dialog.Root>
	{/if}
</div>
