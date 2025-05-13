<script lang="ts">
    import SearchBar from '$lib/components/SearchBar.svelte';
    import { page } from '$app/stores';
    import { fetchSearchResults } from '$lib/utils/search';
    import { navigateToSearch } from '$lib/utils/navigation';
    import type { SearchParams } from '$lib/utils/search';
    import { API_URL } from '$lib/config';

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

<div class="max-w-5xl mx-auto p-4 space-y-4">
    <SearchBar onSearch={handleSearch} />

    {#if isLoading}
        <div class="text-center text-purple-500">Loading...</div>
    {/if}

    {#if error}
        <div class="text-center text-red-500">{error}</div>
    {/if}

    {#if searchResults.length}
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {#each searchResults as result}
                <div class="bg-white/80 backdrop-blur rounded-xl p-4 shadow">
                    <h3 class="font-bold text-lg">{result.title}</h3>
                    <p class="text-sm text-gray-700">{result.description}</p>
                    <p class="text-xs text-gray-500">Score: {result.score} By: {result.scored_by}</p>
                </div>
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
