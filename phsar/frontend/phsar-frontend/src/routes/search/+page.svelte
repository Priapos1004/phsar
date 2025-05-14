<script lang="ts">
    import SearchBar from '$lib/components/SearchBar.svelte';
    import { page } from '$app/stores';
    import { fetchSearchResults } from '$lib/utils/search';
    import { navigateToSearch } from '$lib/utils/navigation';
    import type { SearchParams } from '$lib/utils/search';
    import { API_URL } from '$lib/config';
    import * as cls from '$lib/styles/classes';
    import MediaInfo from '$lib/components/MediaInfo.svelte';

    let searchResults: any[] = [];
    let isLoading = false;
    let error = '';
    let hasToken = false;

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

            const decodedParams: SearchParams = await verifyResponse.json();
            await loadSearchResults(decodedParams);

        } catch (err) {
            error = err instanceof Error ? err.message : 'An unexpected error occurred';
        } finally {
            isLoading = false;
        }
    }

    async function loadSearchResults(params: SearchParams) {
        try {
            const token = localStorage.getItem('token');
            const results = await fetchSearchResults(params, token);
            searchResults = results;
        } catch (err) {
            error = err instanceof Error ? err.message : 'An unexpected error occurred';
        }
    }

    function handleSearch(params: SearchParams) {
        navigateToSearch(params);
    }
</script>

<div class={`${cls.container} p-4 space-y-4`}>
    <SearchBar onSearch={handleSearch} />

    {#if isLoading}
        <div class="text-center text-purple-500">Loading...</div>
    {/if}

    {#if error}
        <div class="text-center text-red-500">{error}</div>
    {/if}

    {#if searchResults.length}
        <div class="grid grid-cols-1 gap-4">
            {#each searchResults as result}
                <MediaInfo
                    title={result.title}
                    score={result.score}
                    scoredBy={result.scored_by}
                />
            {/each}
        </div>
    {:else if !isLoading && !error}
        {#if hasToken}
            <div class="text-center text-gray-400">No results found :-(</div>
        {:else}
            <div class="text-center text-gray-400">Start searching!!!</div>
        {/if}
    {/if}
</div>
