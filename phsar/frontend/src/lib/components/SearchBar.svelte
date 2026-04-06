<script lang="ts">
	import { onMount } from 'svelte';
	import { SlidersHorizontal } from 'lucide-svelte';
	import { api } from '$lib/api';
	import type { FilterOptions } from '$lib/types/api';
	import TagSelect from '$lib/components/TagSelect.svelte';
	import DoubleRangeSlider from '$lib/components/DoubleRangeSlider.svelte';
	import { Input } from '$lib/components/ui/input';
	import { Button } from '$lib/components/ui/button';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Label } from '$lib/components/ui/label';
	import * as Card from '$lib/components/ui/card';
	import type { MediaSearchFilters } from '$lib/utils/search';
	import { formatDecimalDigits, formatDuration, formatNumber } from '$lib/utils/formatString';

	interface Props {
		viewType?: 'anime' | 'media';
		onSearch?: (params: MediaSearchFilters) => void;
		searchParams?: Partial<MediaSearchFilters>;
	}

	let {
		viewType = 'anime',
		onSearch = () => {},
		searchParams = {},
	}: Props = $props();

	let query = $state('');
	let useDescription = $state(false);
	let showFilters = $state(false);

	const logBase = 2;
	const logStep = 0.1;

	type UnifiedFilterConfig =
		| {
			type: 'list';
			key: keyof Pick<MediaSearchFilters, 'genre_name' | 'anime_season' | 'studio_name' | 'airing_status' | 'relation_type' | 'media_type' | 'age_rating'>;
			label: string;
			placeholder: string;
		  }
		| {
			type: 'range';
			minKey: keyof Pick<MediaSearchFilters, 'episodes_min' | 'score_min' | 'scored_by_min'>;
			maxKey: keyof Pick<MediaSearchFilters, 'episodes_max' | 'score_max' | 'scored_by_max'>;
			label: string;
			step: number;
			large_number: boolean;
			scale?: 'linear' | 'log';
		  }
		| {
			type: 'timeRange';
			minKey: keyof Pick<MediaSearchFilters, 'duration_per_episode_min' | 'total_watch_time_min'>;
			maxKey: keyof Pick<MediaSearchFilters, 'duration_per_episode_max' | 'total_watch_time_max'>;
			label: string;
			step: number;
		};

	const filterConfig: UnifiedFilterConfig[] = [
		{ type: 'list', key: 'genre_name', label: 'Genres', placeholder: 'Search genres...' },
		{ type: 'list', key: 'anime_season', label: 'Seasons', placeholder: 'Search seasons...' },
		{ type: 'list', key: 'studio_name', label: 'Studios', placeholder: 'Search studios...' },
		{ type: 'list', key: 'airing_status', label: 'Airing Status', placeholder: 'Search airing status...' },
		{ type: 'list', key: 'relation_type', label: 'Relation Type', placeholder: 'Search relation types...' },
		{ type: 'list', key: 'media_type', label: 'Media Type', placeholder: 'Search media types...' },
		{ type: 'list', key: 'age_rating', label: 'Age Rating', placeholder: 'Search age ratings...' },
		{ type: 'range', minKey: 'episodes_min', maxKey: 'episodes_max', label: 'Episodes', step: 1, large_number: false },
		{ type: 'range', minKey: 'score_min', maxKey: 'score_max', label: 'Score', step: 0.01, large_number: false },
		{ type: 'range', minKey: 'scored_by_min', maxKey: 'scored_by_max', label: 'Scored By', step: 100, large_number: true, scale: 'log' },
		{ type: 'timeRange', minKey: 'duration_per_episode_min', maxKey: 'duration_per_episode_max', label: 'Average Duration per Episode', step: 60 },
		{ type: 'timeRange', minKey: 'total_watch_time_min', maxKey: 'total_watch_time_max', label: 'Total Watch Time', step: 60 },
	];

	// Hide duration-per-episode for anime view (not meaningful at aggregated level)
	let activeFilterConfig = $derived(
		viewType === 'anime'
			? filterConfig.filter(c => !(c.type === 'timeRange' && c.minKey === 'duration_per_episode_min'))
			: filterConfig
	);

	let listFilters: Partial<Record<string, string[]>> = $state({});
	let numberFilters: Partial<Record<string, number | undefined>> = $state({});
	let listFilterOptions: Partial<Record<string, string[]>> = $state({});
	let numberFilterOptions: Partial<Record<string, number>> = $state({});

	function calculate_min_max_timerange(
		min: number | undefined | null,
		max: number | undefined | null,
		base_value: number
	): [number | undefined, number | undefined] {
		if (typeof min !== 'number' || typeof max !== 'number') {
			return [undefined, undefined];
		}
		return [
			Math.floor(min / base_value) * base_value,
			Math.ceil(max / base_value) * base_value,
		];
	}

	function handleRangeChange(
		minKey: string,
		maxKey: string,
		from: number,
		to: number,
		config?: UnifiedFilterConfig
	): void {
		const tolerance = 1e-6;
		const minDefault = numberFilterOptions[minKey] ?? 0;
		const maxDefault = numberFilterOptions[maxKey] ?? 0;

		let actualFrom = from;
		let actualTo = to;

		if (config && config.type === 'range' && config.scale === 'log') {
			actualFrom = fromLog(from);
			actualTo = fromLog(to);
		}

		numberFilters[minKey] =
			Math.abs(actualFrom - minDefault) <= tolerance ? undefined : actualFrom;
		numberFilters[maxKey] =
			Math.abs(actualTo - maxDefault) <= tolerance ? undefined : actualTo;
	}

	function getFormatDisplay(config: UnifiedFilterConfig): (val: number) => string {
		if (config.type === 'timeRange') {
			return (val) => formatDuration(val);
		}
		if (config.type === 'range') {
			const digits = (config.step.toString().split('.')[1] || '').length;
			return (val) => formatNumber(formatDecimalDigits(val, digits));
		}
		return (val) => String(val);
	}

	function toLog(value: number): number {
		return Math.log(Math.max(value, 0) + 1) / Math.log(logBase);
	}

	function fromLog(logValue: number): number {
		return Math.round(Math.pow(logBase, logValue) - 1);
	}

	function syncFiltersFromParams() {
		query = searchParams.query ?? '';
		useDescription = searchParams.search_type === 'description';

		filterConfig.forEach((config) => {
			if (config.type === 'list') {
				listFilters[config.key] = [...(searchParams[config.key] ?? [])];
			} else if (config.type === 'timeRange' || (config.type === 'range' && config.large_number)) {
				const [newMin, newMax] = calculate_min_max_timerange(
					searchParams[config.minKey], searchParams[config.maxKey], config.step
				);
				numberFilters[config.minKey] = newMin;
				numberFilters[config.maxKey] = newMax;
			} else {
				numberFilters[config.minKey] = searchParams[config.minKey] ?? undefined;
				numberFilters[config.maxKey] = searchParams[config.maxKey] ?? undefined;
			}
		});
	}

	$effect(() => {
		if (Object.keys(searchParams).length) {
			syncFiltersFromParams();
		}
	});

	// Re-fetch filter options when viewType changes
	let prevViewType = viewType;
	$effect(() => {
		if (viewType !== prevViewType) {
			prevViewType = viewType;
			clearFilters();
			// Reset slider bounds so they don't show stale ranges during fetch
			listFilterOptions = {};
			numberFilterOptions = {};
			fetchFilters();
		}
	});

	onMount(fetchFilters);

	async function fetchFilters() {
		try {
			const params = new URLSearchParams({ view_type: viewType });
			const data = await api.get<FilterOptions>('/filters/options', { params });

			filterConfig.forEach((config) => {
				if (config.type === 'list') {
					listFilterOptions[config.key] = data[config.key] ?? [];
				} else if (config.type === 'timeRange' || (config.type === 'range' && config.large_number)) {
					const [newMin, newMax] = calculate_min_max_timerange(
						data[config.minKey], data[config.maxKey], config.step
					);
					numberFilterOptions[config.minKey] = newMin;
					numberFilterOptions[config.maxKey] = newMax;
				} else {
					numberFilterOptions[config.minKey] = data[config.minKey] ?? undefined;
					numberFilterOptions[config.maxKey] = data[config.maxKey] ?? undefined;
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
			search_type: useDescription ? 'description' : 'title',
			...listFilters,
			...numberFilters,
		};
		onSearch(params);
		showFilters = false;
	}

	function clearFilters() {
		query = '';
		useDescription = false;

		filterConfig.forEach((config) => {
			if (config.type === 'list') {
				listFilters[config.key] = [];
			} else {
				numberFilters[config.minKey] = undefined;
				numberFilters[config.maxKey] = undefined;
			}
		});
	}

	let hasActiveFilters = $derived(
		Object.values(listFilters).some((arr) => arr?.length) ||
		Object.values(numberFilters).some((v) => v !== undefined) ||
		useDescription
	);
</script>

<form onsubmit={handleSubmit} class="w-full max-w-xl mx-auto">
	<div class="relative">
		<Input
			type="text"
			bind:value={query}
			placeholder={viewType === 'anime' ? 'Search anime...' : 'Search media...'}
			class="w-full h-12 px-5 rounded-full bg-card/80 backdrop-blur border-input pr-12"
		/>
		<Button
			type="button"
			variant="ghost"
			size="icon"
			class="absolute top-1/2 right-3 -translate-y-1/2 text-primary hover:text-primary/70"
			onclick={() => (showFilters = !showFilters)}
			aria-label="Toggle filters"
		>
			<SlidersHorizontal class="w-5 h-5" />
		</Button>
	</div>

	<button type="submit" class="hidden">Submit</button>

	{#if showFilters}
		<Card.Root class="mt-3 bg-card/80 backdrop-blur relative z-10">
			<Card.Content class="space-y-4">
				<div class="flex justify-between items-center mb-2">
					<h2 class="text-lg font-semibold text-card-foreground">Filters</h2>
					{#if hasActiveFilters}
						<Button
							variant="ghost"
							size="sm"
							class="text-destructive hover:text-destructive hover:bg-destructive/10"
							onclick={clearFilters}
						>
							Clear all
						</Button>
					{/if}
				</div>

				<div class="flex items-center gap-2 mb-2">
					<Checkbox
						id="use-description"
						checked={useDescription}
						onCheckedChange={(v) => (useDescription = !!v)}
					/>
					<Label for="use-description" class="text-sm text-card-foreground cursor-pointer select-none">
						Expand search to descriptions
					</Label>
				</div>

				{#each activeFilterConfig as config}
					{#if config.type === 'list'}
						<TagSelect
							placeholder={config.placeholder}
							options={listFilterOptions[config.key] ?? []}
							selectedItems={listFilters[config.key] ?? []}
							onAdd={(item) => (listFilters[config.key] = [...(listFilters[config.key] ?? []), item])}
							onRemove={(item) => (listFilters[config.key] = (listFilters[config.key] ?? []).filter((i) => i !== item))}
						/>
					{:else if config.type === 'range' || config.type === 'timeRange'}
						{@const isLog = config.type === 'range' && config.scale === 'log'}
						{@const minOpt = numberFilterOptions[config.minKey] ?? 1}
						{@const maxOpt = numberFilterOptions[config.maxKey] ?? 1}
						{@const fromVal = numberFilters[config.minKey] ?? minOpt}
						{@const toVal = numberFilters[config.maxKey] ?? maxOpt}

						<DoubleRangeSlider
							label={config.label}
							minValue={isLog ? toLog(minOpt) : minOpt}
							maxValue={isLog ? toLog(maxOpt) : maxOpt}
							step={isLog ? logStep : config.step}
							from={isLog ? toLog(fromVal) : fromVal}
							to={isLog ? toLog(toVal) : toVal}
							onChange={({ from, to }) =>
								handleRangeChange(config.minKey, config.maxKey, from, to, config)
							}
							formatDisplay={(val) => {
								const displayVal = isLog ? fromLog(val) : val;
								return getFormatDisplay(config)(displayVal);
							}}
						/>
					{/if}
				{/each}
			</Card.Content>
		</Card.Root>
	{/if}
</form>
