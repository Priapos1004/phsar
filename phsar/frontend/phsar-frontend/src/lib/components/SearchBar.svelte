<script lang="ts">
    import { onMount } from 'svelte';
    import { SlidersHorizontal } from 'lucide-svelte';
    import { API_URL } from '$lib/config';
    import TagSelect from '$lib/components/TagSelect.svelte';

    export let placeholder = "Search anime...";
    export let onSearch: (params: { query: string; genre: string[]; season: string[] }) => void = () => {};

    let query = '';
    let showFilters = false;

    let genres: string[] = [];
    let seasons: string[] = [];
    let selectedGenres: string[] = [];
    let selectedSeasons: string[] = [];

    async function fetchFilters() {
        try {
            const token = localStorage.getItem('token');
            if (!token) return;

            const res = await fetch(`${API_URL}/filters/`, {
                headers: { Authorization: `Bearer ${token}` }
            });

            if (!res.ok) throw new Error(`Failed to load filters: ${res.status}`);
            const data = await res.json();
            genres = data.genre_name || [];
            seasons = data.anime_season || [];
        } catch (err) {
            console.error('Failed to fetch filters:', err);
        }
    }

    function handleSubmit(e: Event) {
        e.preventDefault();
        onSearch({ query, genre: selectedGenres, season: selectedSeasons });
    }

    function handleAdd(items: string[], item: string, setItems: (val: string[]) => void) {
        if (!items.includes(item)) {
            setItems([...items, item]);
        }
    }

    function handleRemove(items: string[], item: string, setItems: (val: string[]) => void) {
        setItems(items.filter(i => i !== item));
    }

    onMount(() => {
        showFilters = false;
        fetchFilters();
    });
</script>

<form on:submit={handleSubmit} class="w-full max-w-xl mx-auto">
    <div class="relative">
        <input
            type="text"
            bind:value={query}
            placeholder={placeholder}
            class="w-full px-5 py-3 rounded-full bg-white/80 backdrop-blur border border-gray-300 focus:outline-none focus:ring-2 focus:ring-purple-500 pr-12"
        />
        <button
            type="button"
            class="absolute top-1/2 right-3 transform -translate-y-1/2 text-purple-700 hover:text-purple-500"
            on:click={() => (showFilters = !showFilters)}
            aria-label="Toggle filters"
        >
            <SlidersHorizontal class="w-5 h-5" />
        </button>
    </div>

    {#if showFilters}
        <div class="mt-3 bg-white/80 backdrop-blur rounded-xl p-4 shadow space-y-4">
            <TagSelect
                placeholder="Search genres..."
                options={genres}
                selectedItems={selectedGenres}
                onAdd={(item) => handleAdd(selectedGenres, item, v => selectedGenres = v)}
                onRemove={(item) => handleRemove(selectedGenres, item, v => selectedGenres = v)}
            />

            <TagSelect
                placeholder="Search seasons..."
                options={seasons}
                selectedItems={selectedSeasons}
                onAdd={(item) => handleAdd(selectedSeasons, item, v => selectedSeasons = v)}
                onRemove={(item) => handleRemove(selectedSeasons, item, v => selectedSeasons = v)}
            />
        </div>
    {/if}
</form>
