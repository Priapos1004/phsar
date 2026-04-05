<script lang="ts">
	import SearchBar from '$lib/components/SearchBar.svelte';
	import { page } from '$app/state';
	import { fetchSearchResults } from '$lib/utils/search';
	import type { MediaSearchFilters } from '$lib/utils/search';
	import { navigateToSearch } from '$lib/utils/navigation';
	import { formatDuration } from '$lib/utils/formatString';
	import { api } from '$lib/api';
	import type { MediaConnected } from '$lib/types/api';
	import * as cls from '$lib/styles/classes';
	import MediaInfo from '$lib/components/MediaInfo.svelte';
	import SkeletonCard from '$lib/components/SkeletonMediaInfo.svelte';

	let searchResults: MediaConnected[] = $state([]);
	let isLoading = $state(false);
	let error = $state('');
	let hasToken = $state(false);

	let decodedParams: Partial<MediaSearchFilters> = $state({});
	let searchToken = $derived(page.url.searchParams.get('q'));

	let visibleCount = $state(20);

	function showMore() {
		visibleCount = Math.min(visibleCount + 20, searchResults.length);
	}

	$effect(() => {
		const tokenParam = page.url.searchParams.get('q');

		hasToken = !!tokenParam;

		if (tokenParam) {
			loadSearchParamsFromToken(tokenParam);
		}
	});

	async function loadSearchParamsFromToken(token: string) {
		isLoading = true;
		error = '';
		searchResults = [];

		try {
			const parsed = await api.post<MediaSearchFilters>('/filters/verify-token', { token });
			decodedParams = parsed;
			await loadSearchResults(parsed);
		} catch (err) {
			error = err instanceof Error ? err.message : 'An unexpected error occurred';
		} finally {
			isLoading = false;
		}
	}

	async function loadSearchResults(params: MediaSearchFilters) {
		try {
			const results = await fetchSearchResults(params);
			searchResults = results;
			visibleCount = 20;
		} catch (err) {
			error = err instanceof Error ? err.message : 'An unexpected error occurred';
		}
	}

	function handleSearch(params: MediaSearchFilters) {
		navigateToSearch(params);
	}
</script>

<div class={`${cls.container} p-4 space-y-4`}>
	<SearchBar onSearch={handleSearch} searchParams={decodedParams} />

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

	{#if searchResults.length}
		<div class={cls.mediaInfoGrid}>
			{#each searchResults.slice(0, visibleCount) as result}
				<MediaInfo
					info_type="media"
					title={result.name_eng ?? result.title}
					score={result.score}
					scoredBy={result.scored_by}
					anime_season={result.anime_season_name && result.anime_season_year ? result.anime_season_name + " " + result.anime_season_year : null}
					airing_status={result.airing_status}
					age_rating_numeric={result.age_rating_numeric}
					genres={result.genres}
					media_type={result.media_type}
					relation_type={result.relation_type}
					watchtime={result.total_watch_time !== null ? formatDuration(result.total_watch_time) : null}
					imageUrl={result.cover_image}
					on_watchlist={false}
					media_uuid={result.uuid}
					{searchToken}
				/>
			{/each}
		</div>

		{#if searchResults.length > visibleCount}
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
