<script lang="ts">
	import SearchBar from '$lib/components/SearchBar.svelte';
	import GrainToggle from '$lib/components/GrainToggle.svelte';
	import Notice from '$lib/components/Notice.svelte';
	import { X } from 'lucide-svelte';
	import { page } from '$app/state';
	import {
		carryAcrossView,
		fetchAnimeSearchResults,
		fetchSearchResults,
		filterChips,
		omitKeys,
		stripForGuest,
		type MediaSearchFilters,
		type ViewType,
	} from '$lib/utils/search';
	import { getContext } from 'svelte';
	import { ensureRatingCoverage } from '$lib/stores/ratingCoverage';
	import { navigateToSearch } from '$lib/utils/navigation';
	import { formatDuration, formatSeason, formatSeasonRange, resolveTitle } from '$lib/utils/formatString';
	import { api } from '$lib/api';
	import { userSettings } from '$lib/stores/userSettings';
	import type { MediaSearchResult, AnimeSearchResult } from '$lib/types/api';
	import * as cls from '$lib/styles/classes';
	import MediaInfo from '$lib/components/MediaInfo.svelte';
	import SkeletonCard from '$lib/components/SkeletonMediaInfo.svelte';
	import { consumeFocus, pageCovering, revealFocused } from '$lib/utils/scrollFocus';

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');

	const getUserRole = getContext<() => string | null>('userRole');
	let mediaResults: MediaSearchResult[] = $state([]);
	let animeResults: AnimeSearchResult[] = $state([]);
	let isLoading = $state(false);
	let error = $state('');
	let hasToken = $state(false);
	// A guest's shared link lost the filters that read the caller's own ratings or watchlist.
	let strippedForGuest = $state(false);
	let filtersOpen = $state(false);

	let defaultView = $derived($userSettings?.default_search_view ?? 'anime');
	let decodedParams = $state<MediaSearchFilters>({ query: '', search_type: 'title' });
	// The view is the applied search's, so it has one writer: whatever loaded the search.
	let viewType = $derived<ViewType>(decodedParams.view_type ?? defaultView);
	let searchToken = $derived(page.url.searchParams.get('q'));
	let chips = $derived(filterChips(decodedParams, viewType));

	/** One "Show More" step, and the initial cut. */
	const PAGE_STEP = 20;

	let visibleCount = $state(PAGE_STEP);
	let loadRequestId = 0;

	let currentResults = $derived(viewType === 'anime' ? animeResults : mediaResults);

	function showMore() {
		visibleCount = Math.min(visibleCount + PAGE_STEP, currentResults.length);
	}

	// Reads the `searchToken` derived above, never `page.url` directly. A derived only
	// notifies when its VALUE changes, so stripping `?focus=` after a return re-derives
	// the same token and this does not fire — reloading there would refetch and collapse
	// the expansion the return had just restored.
	$effect(() => {
		hasToken = !!searchToken;

		if (searchToken) {
			loadSearchParamsFromToken(searchToken);
		} else {
			// No search token → browse: run an empty (no query, no filters) search in the default
			// view so the page shows ranked results instead of a blank state. Reading defaultView
			// re-runs this once settings resolve (e.g. a media-default user).
			loadDefaultBrowse(defaultView);
		}
	});

	async function loadDefaultBrowse(view: 'anime' | 'media') {
		const thisRequest = ++loadRequestId;
		isLoading = true;
		error = '';
		mediaResults = [];
		animeResults = [];
		strippedForGuest = false;
		const params: MediaSearchFilters = { query: '', search_type: 'title', view_type: view };
		decodedParams = params;
		try {
			await loadSearchResults(params, thisRequest);
		} finally {
			if (thisRequest === loadRequestId) isLoading = false;
		}
	}

	async function loadSearchParamsFromToken(token: string) {
		const thisRequest = ++loadRequestId;
		isLoading = true;
		error = '';
		mediaResults = [];
		animeResults = [];

		try {
			const parsed = await api.post<MediaSearchFilters>('/filters/verify-token', { token });
			if (thisRequest !== loadRequestId) return;

			const { params, stripped } = getUserRole?.() === 'restricted_user'
				? stripForGuest(parsed)
				: { params: parsed, stripped: false };
			strippedForGuest = stripped;
			decodedParams = params;
			await loadSearchResults(params, thisRequest);
		} catch (err) {
			if (thisRequest !== loadRequestId) return;
			error = err instanceof Error ? err.message : 'An unexpected error occurred';
		} finally {
			if (thisRequest === loadRequestId) isLoading = false;
		}
	}

	async function loadSearchResults(params: MediaSearchFilters, requestId?: number) {
		// Anime view only, and never for the one role that 403s on it — the media
		// view reads `is_rated` off each hit and never touches the store, and the
		// layout's rule is that a request known to fail shouldn't be sent.
		// Unawaited: the tiers decorate cards, so they must not hold results back.
		if (viewType === 'anime' && getUserRole?.() !== 'restricted_user') void ensureRatingCoverage();
		try {
			if (viewType === 'anime') {
				const results = await fetchAnimeSearchResults(params);
				if (requestId !== undefined && requestId !== loadRequestId) return;
				animeResults = results;
			} else {
				const results = await fetchSearchResults(params);
				if (requestId !== undefined && requestId !== loadRequestId) return;
				mediaResults = results;
			}
			visibleCount = PAGE_STEP;
		} catch (err) {
			if (requestId !== undefined && requestId !== loadRequestId) return;
			error = err instanceof Error ? err.message : 'An unexpected error occurred';
		}
	}

	// Restore the card a back link came from: expand past the "Show More" cut far
	// enough to render it, then centre it. The whole result set arrives in one request
	// and is sliced client-side, so this is an integer, not another fetch.
	//
	// Gated on results rather than on the load resolving, because the skeleton grid
	// renders ABOVE the results for as long as `isLoading` holds — centring while it
	// is still there scrolls to a position its removal then shifts.
	let revealed = false;
	$effect(() => {
		if (revealed || isLoading || !currentResults.length) return;
		revealed = true;
		const uuid = consumeFocus(page.url);
		if (!uuid) return;
		const index = currentResults.findIndex((r) => r.uuid === uuid);
		if (index < 0) return;
		visibleCount = pageCovering(index, PAGE_STEP, visibleCount);
		revealFocused(uuid);
	});

	function handleSearch(params: MediaSearchFilters) {
		navigateToSearch({ ...params, view_type: viewType });
	}

	// What survives the switch is `carryAcrossView`'s call; the new token reloads the page.
	function switchView(newView: ViewType) {
		if (newView !== viewType) navigateToSearch(carryAcrossView(decodedParams, newView));
	}

	function removeFilters(keys: (keyof MediaSearchFilters)[]) {
		navigateToSearch({ ...omitKeys(decodedParams, keys), view_type: viewType });
	}
</script>

<svelte:head>
	<title>Search — Phsar</title>
</svelte:head>

<div class={`${cls.container} p-4 space-y-4`}>
	<div class="flex justify-end">
		<GrainToggle grain={viewType} onSelect={switchView} />
	</div>

	<SearchBar onSearch={handleSearch} applied={decodedParams} {viewType} bind:filtersOpen />

	{#if strippedForGuest}
		<div class="max-w-xl mx-auto">
			<Notice>This link filtered by ratings or the watchlist, which guest accounts don't have, so those filters were left out.</Notice>
		</div>
	{/if}

	{#if chips.length}
		<div class="flex flex-wrap items-center justify-center gap-2 max-w-3xl mx-auto">
			{#each chips as chip (chip.id)}
				<span class="inline-flex items-center rounded-full border border-primary/40 bg-primary/15 text-sm text-primary">
					<button type="button" class="pl-3 pr-1.5 py-1 hover:text-white" onclick={() => (filtersOpen = true)}>
						{chip.label}
					</button>
					<button
						type="button"
						class="pr-2 pl-0.5 py-1 hover:text-white"
						aria-label="Remove {chip.label}"
						onclick={() => removeFilters(chip.keys)}
					>
						<X class="size-3.5" />
					</button>
				</span>
			{/each}
			{#if chips.length > 1}
				<button
					type="button"
					class="px-2 py-1 text-sm text-white/60 hover:text-white"
					onclick={() => removeFilters(chips.flatMap((c) => c.keys))}
				>Clear all</button>
			{/if}
		</div>
	{/if}

	{#if isLoading}
		<div class={cls.mediaInfoGrid}>
			{#each Array(6) as _}
				<SkeletonCard />
			{/each}
		</div>
	{/if}

	{#if error}
		<div class="text-center text-destructive">{error}</div>
	{/if}

	{#if currentResults.length}
		<div class={cls.mediaInfoGrid}>
			{#if viewType === 'anime'}
				{#each animeResults.slice(0, visibleCount) as result}
					<MediaInfo
						info_type="anime"
						title={resolveTitle(result.title, result.name_eng, result.name_jap, nameLanguage)}
						score={result.avg_score}
						scoredBy={result.avg_scored_by}
						season_range={formatSeasonRange(result.season_start, result.season_end)}
						airing_status={result.airing_status}
						has_upcoming={result.has_upcoming}
						age_rating_numeric={result.age_rating_numeric}
						genres={result.genres}
						media_types={result.media_types}
						relation_types={result.relation_types}
						watchtime={result.total_watch_time !== null ? formatDuration(result.total_watch_time) : null}
						imageUrl={result.cover_image}
						is_finished={result.is_finished}
						media_uuid={result.uuid}
						{searchToken}
					/>
				{/each}
			{:else}
				{#each mediaResults.slice(0, visibleCount) as result}
					<MediaInfo
						info_type="media"
						title={resolveTitle(result.title, result.name_eng, result.name_jap, nameLanguage)}
						score={result.score}
						scoredBy={result.scored_by}
						anime_season={formatSeason(result.anime_season_name, result.anime_season_year)}
						airing_status={result.airing_status}
						age_rating_numeric={result.age_rating_numeric}
						genres={result.genres}
						media_type={result.media_type}
						relation_type={result.relation_type}
						watchtime={result.total_watch_time !== null ? formatDuration(result.total_watch_time) : null}
						imageUrl={result.cover_image}
						is_rated={result.is_rated}
						media_uuid={result.uuid}
						{searchToken}
					/>
				{/each}
			{/if}
		</div>

		{#if currentResults.length > visibleCount}
			<div class="text-center">
				<button
					onclick={showMore}
					class="mt-4 px-4 py-2 bg-primary text-primary-foreground rounded-full hover:bg-primary/80 transition"
				>
					Show More
				</button>
			</div>
		{/if}
	{:else if !isLoading && !error}
		{#if hasToken}
			<div class="text-center text-muted-foreground">No results found :-(</div>
		{:else}
			<div class="text-center text-muted-foreground">Start searching!!!</div>
		{/if}
	{/if}
</div>
