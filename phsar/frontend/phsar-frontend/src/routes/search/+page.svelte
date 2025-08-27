<script lang="ts">
	import SearchBar from '$lib/components/SearchBar.svelte';
	import { page } from '$app/stores';
	import { fetchSearchResults } from '$lib/utils/search';
    import type { MediaSearchFilters } from '$lib/utils/search';
	import { navigateToSearch } from '$lib/utils/navigation';
	import { calculateWatchtime } from '$lib/utils/getMediaInfo';
	import { formatDuration } from '$lib/utils/formatString';
	import { API_URL } from '$lib/config';
	import * as cls from '$lib/styles/classes';
	import MediaInfo from '$lib/components/MediaInfo.svelte';
	import SkeletonCard from '$lib/components/SkeletonMediaInfo.svelte';

	let searchResults: any[] = [];
	let isLoading = false;
	let error = '';
	let hasToken = false;

	let decodedParams: Partial<MediaSearchFilters> = {};

	let visibleCount = 20;

	function showMore() {
		visibleCount = Math.min(visibleCount + 20, searchResults.length);
	}

	$: {
		const searchParams = $page.url.searchParams;
		const tokenParam = searchParams.get('q');

		hasToken = !!tokenParam;

		if (tokenParam) {
			loadSearchParamsFromToken(tokenParam);
		}
	}

	async function loadSearchParamsFromToken(token: string) {
		isLoading = true;
		error = '';
		searchResults = [];

		try {
			const authToken = localStorage.getItem('token');

			const verifyResponse = await fetch(`${API_URL}/filters/verify-token`, {
				method: 'POST',
				headers: {
					'Content-Type': 'application/json',
					Authorization: `Bearer ${authToken}`
				},
				body: JSON.stringify({ token })
			});

			if (!verifyResponse.ok) {
				throw new Error('Failed to verify search token');
			}

			const parsed: MediaSearchFilters = await verifyResponse.json();
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
			const token = localStorage.getItem('token');
			const results = await fetchSearchResults(params, token);
			searchResults = results;
			console.debug('Found search results:', searchResults);
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
		<div class="text-center text-red-500">{error}</div>
	{/if}

	{#if searchResults.length}
		<div class={cls.mediaInfoGrid}>
			{#each searchResults.slice(0, visibleCount) as result}
				<MediaInfo
					info_type="media"
					title={result.name_eng ?? result.title}
					score={result.score}
					scoredBy={result.scored_by}
					anime_season={result.anime_season}
					airing_status={result.airing_status}
					age_rating_numeric={result.age_rating_numeric}
					genres={result.genres}
					media_type={result.media_type}
					relation_type={result.relation_type}
					watchtime={result.total_watch_time !== null ? formatDuration(result.total_watch_time) : null}
					imageUrl={result.cover_image}
					on_watchlist={false}
					media_uuid={result.uuid}
				/>
			{/each}
		</div>

		{#if searchResults.length > visibleCount}
			<div class="text-center">
				<button
					on:click={showMore}
					class="mt-4 px-4 py-2 bg-purple-600 text-white rounded-full hover:bg-purple-700 transition"
				>
					Show More
				</button>
			</div>
		{/if}
	{:else if !isLoading && !error}
		{#if hasToken}
			<div class="text-center text-gray-400">No results found :-(</div>
		{:else}
			<div class="text-center text-gray-400">Start searching!!!</div>
		{/if}
	{/if}
</div>
