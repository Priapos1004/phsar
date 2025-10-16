<script lang="ts">
	import { onMount } from 'svelte';
	import { SlidersHorizontal } from 'lucide-svelte';
	import { API_URL } from '$lib/config';
	import TagSelect from '$lib/components/TagSelect.svelte';
	import DoubleRangeSlider from '$lib/components/DoubleRangeSlider.svelte';
	import * as cls from '$lib/styles/classes';
	import type { MediaSearchFilters } from '$lib/utils/search';
    import { formatDecimalDigits, formatDuration, formatNumber } from '$lib/utils/formatString';

	export let placeholder = "Search anime...";
	export let onSearch: (params: MediaSearchFilters) => void = () => {};
	export let searchParams: Partial<MediaSearchFilters> = {};

	let query = '';
	let showFilters = false;

	type UnifiedFilterConfig =
		| { type: 'list'; key: keyof Pick<MediaSearchFilters, 'genre_name' | 'anime_season' | 'studio_name' | 'airing_status' | 'relation_type' | 'media_type' | 'age_rating'>; label: string; placeholder: string }
		| { type: 'Range'; minKey: keyof Pick<MediaSearchFilters, 'episodes_min' | 'score_min' | 'scored_by_min'>; maxKey: keyof Pick<MediaSearchFilters, 'episodes_max' | 'score_max' | 'scored_by_max'>; label: string; step: number, large_number: boolean }
		| { type: 'timeRange'; minKey: keyof Pick<MediaSearchFilters, 'duration_per_episode_min' | 'total_watch_time_min'>; maxKey: keyof Pick<MediaSearchFilters, 'duration_per_episode_max' | 'total_watch_time_max'>; label: string;  step: number };

	const filterConfig: UnifiedFilterConfig[] = [
		{ type: 'list', key: 'genre_name', label: 'Genres', placeholder: 'Search genres...' },
		{ type: 'list', key: 'anime_season', label: 'Seasons', placeholder: 'Search seasons...' },
		{ type: 'list', key: 'studio_name', label: 'Studios', placeholder: 'Search studios...' },
		{ type: 'list', key: 'airing_status', label: 'Airing Status', placeholder: 'Search airing status...' },
		{ type: 'list', key: 'relation_type', label: 'Relation Type', placeholder: 'Search relation types...' },
		{ type: 'list', key: 'media_type', label: 'Media Type', placeholder: 'Search media types...' },
		{ type: 'list', key: 'age_rating', label: 'Age Rating', placeholder: 'Search age ratings...' },
		{ type: 'Range', minKey: 'episodes_min', maxKey: 'episodes_max', label: 'Episodes', step: 1, large_number: false },
		{ type: 'Range', minKey: 'score_min', maxKey: 'score_max', label: 'Score', step: 0.01, large_number: false },
        { type: 'Range', minKey: 'scored_by_min', maxKey: 'scored_by_max', label: 'Scored By', step: 100, large_number: true },
		{ type: 'timeRange', minKey: 'duration_per_episode_min', maxKey: 'duration_per_episode_max', label: 'Average Duration per Episode', step: 60 },
		{ type: 'timeRange', minKey: 'total_watch_time_min', maxKey: 'total_watch_time_max', label: 'Total Watch Time', step: 60 },
	];

	// Filter state
	let listFilters: Partial<Record<string, string[]>> = {};
	let numberFilters: Partial<Record<string, number | undefined>> = {};

	// Options loaded from API
	let listFilterOptions: Partial<Record<string, string[]>> = {};
    let numberFilterOptions: Partial<Record<string, number>> = {};

    // Helper functions
    function calculate_min_max_timerange(
        min: number | undefined | null,
        max: number | undefined | null,
        base_value: number
    ): [number | undefined, number | undefined] {
        if (typeof min !== 'number' || typeof max !== 'number') {
            return [undefined, undefined];
        }

        const new_min = Math.floor(min / base_value) * base_value;
        const new_max = Math.ceil(max / base_value) * base_value;
        return [new_min, new_max];
    }

    function handleRangeChange(
        minKey: string,
        maxKey: string,
        from: number,
        to: number,
    ): void {
        const minDefault = numberFilterOptions[minKey];
        const maxDefault = numberFilterOptions[maxKey];

        numberFilters[minKey] = from === minDefault ? undefined : from;
        numberFilters[maxKey] = to === maxDefault ? undefined : to;
    }

    function getFormatDisplay(config: UnifiedFilterConfig): (val: number) => string {
        if (config.type === 'timeRange') {
            return (val) => formatDuration(val);
        }

        if (config.type === 'Range') {
            const digits = (config.step.toString().split('.')[1] || '').length;
            return (val) => formatNumber(formatDecimalDigits(val, digits));
        }

        // Fallback — should never happen
        return (val) => String(val);
    }

	// --- Reactivity ---
	function syncFiltersFromParams() {
		query = searchParams.query ?? '';

		filterConfig.forEach(config => {
			if (config.type === 'list') {
				listFilters[config.key] = [...(searchParams[config.key] ?? [])];
            } else if (config.type === 'timeRange' || config.large_number === true) {
                const [newMin, newMax] = calculate_min_max_timerange(searchParams[config.minKey], searchParams[config.maxKey], config.step);
                numberFilters[config.minKey] = newMin;
                numberFilters[config.maxKey] = newMax;
			} else {
				numberFilters[config.minKey] = searchParams[config.minKey] ?? undefined;
				numberFilters[config.maxKey] = searchParams[config.maxKey] ?? undefined;
			}
		});
	}

	let hasSynced = false;
    $: if (!hasSynced && Object.keys(searchParams).length) {
        syncFiltersFromParams();
        hasSynced = true;
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

			filterConfig.forEach(config => {
                if (config.type === 'list') {
                    listFilterOptions[config.key] = data[config.key] ?? [];
                } else if (config.type === 'timeRange' || config.large_number === true) {
                    const [newMin, newMax] = calculate_min_max_timerange(data[config.minKey], data[config.maxKey], config.step);
                    numberFilterOptions[config.minKey] = newMin;
                    numberFilterOptions[config.maxKey] = newMax;
                } else {
                    numberFilterOptions[config.minKey] = data[config.minKey];
                    numberFilterOptions[config.maxKey] = data[config.maxKey];
                }
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
			...numberFilters
		};
		onSearch(params);
        showFilters = false;
	}

	function clearFilters() {
        query = '';

        // Reset list filters to empty arrays
        filterConfig.forEach(config => {
            if (config.type === 'list') {
                listFilters[config.key] = [];
            } else {
                numberFilters[config.minKey] = undefined;
                numberFilters[config.maxKey] = undefined;
            }
        });
    }
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
			class={`absolute top-1/2 right-3 -translate-y-1/2 ${cls.iconButton}`}
			on:click={() => (showFilters = !showFilters)}
			aria-label="Toggle filters"
		>
			<SlidersHorizontal class="w-5 h-5" />
		</button>
	</div>

	<button type="submit" class="hidden">Submit</button>

	{#if showFilters}
		<div class="{cls.blurBox} relative z-10 space-y-4">
			<div class="flex justify-between items-center mb-2">
				<h2 class="text-lg font-semibold text-gray-800">Filters</h2>
				{#if Object.values(listFilters).some(arr => arr?.length)
					|| Object.values(numberFilters).some(v => v !== undefined)}
					<button
						on:click={clearFilters}
						class="text-sm text-red-600 font-medium px-2 py-1 rounded hover:bg-red-50 transition"
					>
						Clear all
					</button>
				{/if}
			</div>

			{#each filterConfig as config}
				{#if config.type === 'list'}
					<TagSelect
						placeholder={config.placeholder}
						options={listFilterOptions[config.key] ?? []}
						selectedItems={listFilters[config.key] ?? []}
						onAdd={(item) => listFilters[config.key] = [...(listFilters[config.key] ?? []), item]}
						onRemove={(item) => listFilters[config.key] = (listFilters[config.key] ?? []).filter(i => i !== item)}
					/>
                    {:else if config.type === 'Range' || config.type === 'timeRange'}
                        <DoubleRangeSlider
                            label={config.label}
                            minValue={numberFilterOptions[config.minKey]}
                            maxValue={numberFilterOptions[config.maxKey]}
                            step={config.step}
                            from={numberFilters[config.minKey] ?? numberFilterOptions[config.minKey]}
                            to={numberFilters[config.maxKey] ?? numberFilterOptions[config.maxKey]}
                            onChange={({ from, to }) =>
                                handleRangeChange(config.minKey, config.maxKey, from, to)
                            }
                            formatDisplay={getFormatDisplay(config)}
                        />
				{/if}
			{/each}
		</div>
	{/if}
</form>
