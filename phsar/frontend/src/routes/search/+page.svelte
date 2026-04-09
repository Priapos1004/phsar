<script lang="ts">
	import SearchBar from '$lib/components/SearchBar.svelte';
	import { page } from '$app/state';
	import { fetchSearchResults, fetchAnimeSearchResults } from '$lib/utils/search';
	import type { MediaSearchFilters } from '$lib/utils/search';
	import { navigateToSearch } from '$lib/utils/navigation';
	import { formatDuration, formatSeason, formatSeasonRange, resolveTitle } from '$lib/utils/formatString';
	import { api } from '$lib/api';
	import { userSettings } from '$lib/stores/userSettings';
	import type { MediaConnected, AnimeSearchResult } from '$lib/types/api';
	import * as cls from '$lib/styles/classes';
	import MediaInfo from '$lib/components/MediaInfo.svelte';
	import SkeletonCard from '$lib/components/SkeletonMediaInfo.svelte';

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');

	let mediaResults: MediaConnected[] = $state([]);
	let animeResults: AnimeSearchResult[] = $state([]);
	let isLoading = $state(false);
	let error = $state('');
	let hasToken = $state(false);

	let defaultView = $derived($userSettings?.default_search_view ?? 'anime');
	let viewType = $state<'anime' | 'media'>('anime');
	// Apply default search view from settings on initial load (before any token overrides)
	$effect(() => { if (!hasToken) viewType = defaultView; });
	let decodedParams: Partial<MediaSearchFilters> = $state({});
	let searchToken = $derived(page.url.searchParams.get('q'));

	let visibleCount = $state(20);
	let loadRequestId = 0;

	let currentResults = $derived(viewType === 'anime' ? animeResults : mediaResults);

	function showMore() {
		visibleCount = Math.min(visibleCount + 20, currentResults.length);
	}

	$effect(() => {
		const tokenParam = page.url.searchParams.get('q');

		hasToken = !!tokenParam;

		if (tokenParam) {
			loadSearchParamsFromToken(tokenParam);
		} else {
			mediaResults = [];
			animeResults = [];
		}
	});

	async function loadSearchParamsFromToken(token: string) {
		const thisRequest = ++loadRequestId;
		isLoading = true;
		error = '';
		mediaResults = [];
		animeResults = [];

		try {
			const parsed = await api.post<MediaSearchFilters>('/filters/verify-token', { token });
			if (thisRequest !== loadRequestId) return;

			decodedParams = parsed;
			viewType = parsed.view_type === 'media' ? 'media' : 'anime';
			await loadSearchResults(parsed, thisRequest);
		} catch (err) {
			if (thisRequest !== loadRequestId) return;
			error = err instanceof Error ? err.message : 'An unexpected error occurred';
		} finally {
			if (thisRequest === loadRequestId) isLoading = false;
		}
	}

	async function loadSearchResults(params: MediaSearchFilters, requestId?: number) {
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
			visibleCount = 20;
		} catch (err) {
			if (requestId !== undefined && requestId !== loadRequestId) return;
			error = err instanceof Error ? err.message : 'An unexpected error occurred';
		}
	}

	function handleSearch(params: MediaSearchFilters) {
		navigateToSearch({ ...params, view_type: viewType });
	}

	async function switchView(newView: 'anime' | 'media') {
		if (newView === viewType) return;
		viewType = newView;
		mediaResults = [];
		animeResults = [];
		decodedParams = {};
		error = '';
		visibleCount = 20;
		// Auto-submit empty search to show unfiltered results for the new view
		navigateToSearch({ query: '', search_type: 'title', view_type: newView });
	}
</script>

<div class={`${cls.container} p-4 space-y-4`}>
	<!-- View toggle — subtle, top-right, below navbar -->
	<div class="flex justify-end">
		<div class="inline-flex rounded-full border border-border bg-card/60 backdrop-blur p-0.5 text-xs">
			<button
				class="px-3 py-1 rounded-full font-medium transition {viewType === 'anime' ? 'bg-primary text-primary-foreground' : 'text-card-foreground/70 hover:text-card-foreground'}"
				onclick={() => switchView('anime')}
			>
				Anime
			</button>
			<button
				class="px-3 py-1 rounded-full font-medium transition {viewType === 'media' ? 'bg-primary text-primary-foreground' : 'text-card-foreground/70 hover:text-card-foreground'}"
				onclick={() => switchView('media')}
			>
				Media
			</button>
		</div>
	</div>

	<SearchBar onSearch={handleSearch} searchParams={decodedParams} {viewType} />

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
