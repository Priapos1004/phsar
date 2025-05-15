<script lang="ts">
	import { onMount } from 'svelte';
	import { SlidersHorizontal } from 'lucide-svelte';
	import { API_URL } from '$lib/config';
	import TagSelect from '$lib/components/TagSelect.svelte';
	import * as cls from '$lib/styles/classes';
	import type { SearchParams } from '$lib/utils/search';

	export let placeholder = "Search anime...";
	export let onSearch: (params: { query: string; genre_name: string[]; anime_season: string[] }) => void = () => {};

	export let searchParams: Partial<SearchParams> = {};
    
	let showFilters = false;
	let genres: string[] = [];
	let seasons: string[] = [];

	let query = '';
	let selectedGenres: string[] = [];
	let selectedSeasons: string[] = [];

	$: if (searchParams) {
		query = searchParams.query ?? '';
		selectedGenres = [...(searchParams.genre_name ?? [])];
		selectedSeasons = [...(searchParams.anime_season ?? [])];
	}

	async function fetchFilters() {
		try {
			const token = localStorage.getItem('token');
			if (!token) return;

			const res = await fetch(`${API_URL}/filters/options`, {
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
		onSearch({ query, genre_name: selectedGenres, anime_season: selectedSeasons });
	}

	function handleAdd(items: string[], item: string, setItems: (val: string[]) => void) {
		if (!items.includes(item)) {
			setItems([...items, item]);
		}
	}

	function handleRemove(items: string[], item: string, setItems: (val: string[]) => void) {
		setItems(items.filter(i => i !== item));
	}

    function clearFilters() {
        selectedGenres = [];
        selectedSeasons = [];
        // optionally clear other filters too
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
			class={cls.input}
		/>

		<button
			type="button"
			class={`absolute top-1/2 right-3 transform -translate-y-1/2 ${cls.iconButton}`}
			on:click={() => (showFilters = !showFilters)}
			aria-label="Toggle filters"
		>
			<SlidersHorizontal class="w-5 h-5" />
		</button>
	</div>

	<button type="submit" class="hidden">Submit</button>

	{#if showFilters}
		<div class="{cls.blurBox} relative z-10">
            <div class="flex justify-between items-center mb-2">
                <h2 class="text-lg font-semibold text-gray-800">Filters</h2>
            
                {#if selectedGenres.length || selectedSeasons.length}
                    <button
                        on:click={clearFilters}
                        class="text-sm text-red-600 font-medium px-2 py-1 rounded hover:bg-red-50 transition"
                    >
                        Clear all
                    </button>
                {/if}
            </div>

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
