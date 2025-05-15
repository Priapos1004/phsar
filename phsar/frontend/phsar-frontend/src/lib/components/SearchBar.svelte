<script lang="ts">
	import { onMount } from 'svelte';
	import { SlidersHorizontal } from 'lucide-svelte';
	import { API_URL } from '$lib/config';
	import TagSelect from '$lib/components/TagSelect.svelte';
	import DoubleRangeSlider from '$lib/components/DoubleRangeSlider.svelte';
	import * as cls from '$lib/styles/classes';
	import type { MediaSearchFilters } from '$lib/utils/search';

	export let placeholder = "Search anime...";
	export let onSearch: (params: MediaSearchFilters) => void = () => {};
	export let searchParams: Partial<MediaSearchFilters> = {};

	let query = '';
	let showFilters = false;

	// --- Filter Configs ---
	type ListKey = keyof Pick<MediaSearchFilters,
		'genre_name' | 'anime_season' | 'studio_name' | 'airing_status' | 'relation_type' | 'media_type' | 'fsk'
	>;

	type SingleRangeKey = keyof Pick<MediaSearchFilters,
		'scored_by_min'
	>;

	type DoubleRangeKey = keyof Pick<MediaSearchFilters,
		'episodes_min' | 'episodes_max' | 'score_min' | 'score_max'
	>;

	type TimeKey = keyof Pick<MediaSearchFilters,
		'duration_per_episode_min' | 'duration_per_episode_max' |
		'total_watch_time_min' | 'total_watch_time_max'
	>;

	const listFilterConfig = [
		{ key: 'genre_name', label: 'Genres', placeholder: 'Search genres...' },
		{ key: 'anime_season', label: 'Seasons', placeholder: 'Search seasons...' },
		{ key: 'studio_name', label: 'Studios', placeholder: 'Search studios...' },
		{ key: 'airing_status', label: 'Airing Status', placeholder: 'Search airing status...' },
		{ key: 'relation_type', label: 'Relation Type', placeholder: 'Search relation types...' },
		{ key: 'media_type', label: 'Media Type', placeholder: 'Search media types...' },
		{ key: 'fsk', label: 'FSK', placeholder: 'Search FSK ratings...' }
	] satisfies { key: ListKey; label: string; placeholder: string }[];

	const singleRangeFilterConfig = [
		{ minKey: 'scored_by_min', label: 'Scored By', maxValue: 500_000, step: 1000 }
	] satisfies {
		minKey: SingleRangeKey;
		label: string;
		maxValue: number;
		step: number;
	}[];

	const doubleRangeFilterConfig = [
        { minKey: 'episodes_min', maxKey: 'episodes_max', label: 'Episodes', maxValue: 200, step: 1 },
		{ minKey: 'score_min', maxKey: 'score_max', label: 'Score', maxValue: 10, step: 0.1 }
	] satisfies {
		minKey: DoubleRangeKey;
		maxKey: DoubleRangeKey;
		label: string;
		maxValue: number;
		step: number;
	}[];

	const timeFilterConfig = [
		{ minKey: 'duration_per_episode_min', maxKey: 'duration_per_episode_max', label: 'Duration per Episode', maxValue: 3600 },
		{ minKey: 'total_watch_time_min', maxKey: 'total_watch_time_max', label: 'Total Watch Time', maxValue: 100000 }
	] satisfies {
		minKey: TimeKey;
		maxKey: TimeKey;
		label: string;
		maxValue: number;
	}[];

	let listFilters: Partial<Record<ListKey, string[]>> = {};
	let singleRangeFilters: Partial<Record<SingleRangeKey, number>> = {};
	let doubleRangeFilters: Partial<Record<DoubleRangeKey, number>> = {};
	let timeFilters: Partial<Record<TimeKey, number>> = {};
	let filterOptions: Partial<Record<ListKey, string[]>> = {};

	// --- Reactivity ---
	$: {
		query = searchParams.query ?? '';

		listFilterConfig.forEach(({ key }) => {
			listFilters[key] = [...(searchParams[key] ?? [])];
		});

		singleRangeFilterConfig.forEach(({ minKey }) => {
			singleRangeFilters[minKey] = searchParams[minKey] ?? undefined;
		});

		doubleRangeFilterConfig.forEach(({ minKey, maxKey }) => {
			doubleRangeFilters[minKey] = searchParams[minKey] ?? undefined;
			doubleRangeFilters[maxKey] = searchParams[maxKey] ?? undefined;
		});

		timeFilterConfig.forEach(({ minKey, maxKey }) => {
			timeFilters[minKey] = searchParams[minKey] ?? undefined;
			timeFilters[maxKey] = searchParams[maxKey] ?? undefined;
		});
	}

	onMount(fetchFilters);

	async function fetchFilters() {
		try {
			const token = localStorage.getItem('token');
			if (!token) return;

			const res = await fetch(`${API_URL}/filters/options`, {
				headers: { Authorization: `Bearer ${token}` }
			});

			if (!res.ok) throw new Error(`Failed to load filters`);
			const data = await res.json();

			listFilterConfig.forEach(({ key }) => {
				filterOptions[key] = data[key] ?? [];
			});
		} catch (err) {
			console.error('Filter fetch error:', err);
		}
	}

	function handleSubmit(e: Event) {
		e.preventDefault();
		const params: MediaSearchFilters = {
			query,
			...listFilters,
			...singleRangeFilters,
			...doubleRangeFilters,
			...timeFilters
		};
		onSearch(params);
	}

	function clearFilters() {
		listFilterConfig.forEach(({ key }) => listFilters[key] = []);
		singleRangeFilterConfig.forEach(({ minKey }) => singleRangeFilters[minKey] = undefined);
		doubleRangeFilterConfig.forEach(({ minKey, maxKey }) => {
			doubleRangeFilters[minKey] = undefined;
			doubleRangeFilters[maxKey] = undefined;
		});
		timeFilterConfig.forEach(({ minKey, maxKey }) => {
			timeFilters[minKey] = undefined;
			timeFilters[maxKey] = undefined;
		});
	}
</script>

<!-- Template -->
<form on:submit={handleSubmit} class="w-full max-w-xl mx-auto">
	<div class="relative">
		<input type="text" bind:value={query} placeholder={placeholder} class={cls.input} />
		<button type="button" class={`absolute top-1/2 right-3 -translate-y-1/2 ${cls.iconButton}`} on:click={() => (showFilters = !showFilters)} aria-label="Toggle filters">
			<SlidersHorizontal class="w-5 h-5" />
		</button>
	</div>

	<button type="submit" class="hidden">Submit</button>

	{#if showFilters}
		<div class="{cls.blurBox} relative z-10 space-y-4">
			<div class="flex justify-between items-center mb-2">
				<h2 class="text-lg font-semibold text-gray-800">Filters</h2>
				{#if Object.values(listFilters).some(arr => arr?.length) || Object.values(singleRangeFilters).some(Boolean) || Object.values(doubleRangeFilters).some(Boolean) || Object.values(timeFilters).some(Boolean)}
					<button on:click={clearFilters} class="text-sm text-red-600 font-medium px-2 py-1 rounded hover:bg-red-50 transition">Clear all</button>
				{/if}
			</div>

			<!-- List Filters -->
			{#each listFilterConfig as { key, placeholder }}
				<TagSelect
					placeholder={placeholder}
					options={filterOptions[key] ?? []}
					selectedItems={listFilters[key] ?? []}
					onAdd={(item) => listFilters[key] = [...(listFilters[key] ?? []), item]}
					onRemove={(item) => listFilters[key] = (listFilters[key] ?? []).filter(i => i !== item)}
				/>
			{/each}

			<!-- Double Range Filters -->
			{#each doubleRangeFilterConfig as { minKey, maxKey, label, maxValue, step }}
				<DoubleRangeSlider
					label={label}
					minValue={0}
					maxValue={maxValue}
					step={step}
					from={doubleRangeFilters[minKey] ?? 0}
					to={doubleRangeFilters[maxKey] ?? maxValue}
					onChange={({ from, to }) => {
						doubleRangeFilters[minKey] = from;
						doubleRangeFilters[maxKey] = to;
					}}
				/>
			{/each}

            <!-- Single Range Filters -->
            {#each singleRangeFilterConfig as { minKey, label, maxValue }}
                <!-- Placeholder — replace with SingleRangeSlider later -->
                <div class="text-sm text-gray-500 italic">{label} filter coming soon...</div>
            {/each}

			<!-- Time Filters -->
			{#each timeFilterConfig as { minKey, maxKey, label, maxValue }}
				<!-- Placeholder — replace with TimeSlider later -->
				<div class="text-sm text-gray-500 italic">{label} filter coming soon...</div>
			{/each}
		</div>
	{/if}
</form>