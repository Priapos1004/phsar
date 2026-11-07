<script lang="ts">
	// The search's filter sheet. It edits a copy of `applied`, taken afresh each time it
	// opens, so dismissing it throws the edits away and "Show results" hands them to
	// `onApply`, which comes back as the next `applied`. `SearchBar` wraps it with the query
	// box; the galaxy map opens it alone, with no query to carry.
	import { getContext } from 'svelte';
	import { ensureFilterOptions } from '$lib/stores/filterOptions';
	import { userSettings } from '$lib/stores/userSettings';
	import { formatScoreWithStep } from '$lib/utils/formatString';
	import TagSelect from '$lib/components/TagSelect.svelte';
	import GenreFilterField from '$lib/components/GenreFilterField.svelte';
	import DoubleRangeSlider from '$lib/components/DoubleRangeSlider.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { Button } from '$lib/components/ui/button';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Label } from '$lib/components/ui/label';
	import * as Sheet from '$lib/components/ui/sheet';
	import {
		LIST_FILTERS,
		MATCH_MODES,
		RANGE_FILTERS,
		RATED_STATES,
		TOP_PRESETS,
		filterChips,
		listMode,
		normalizeFilters,
		omitKeys,
		rangeParams,
		type ListFilterKey,
		type MediaSearchFilters,
		type RangeKey,
		type RatedState,
		type ViewType,
	} from '$lib/utils/search';
	import type { FilterOptions } from '$lib/types/api';
	import * as cls from '$lib/styles/classes';

	interface Props {
		viewType: ViewType;
		/** The filters on screen. */
		applied: MediaSearchFilters;
		open?: boolean;
		onApply: (filters: MediaSearchFilters) => void;
	}

	let { viewType, applied, open = $bindable(false), onApply }: Props = $props();

	const getUserRole = getContext<(() => string | null) | undefined>('userRole');
	let isGuest = $derived(getUserRole?.() === 'restricted_user');
	// Your score steps as you rate, so every stop is a score you could have given.
	let ratingStep = $derived(Number($userSettings?.rating_step ?? '0.5'));

	let staged = $derived.by(() => {
		void open;
		return $state.snapshot(applied) as MediaSearchFilters;
	});
	function stage(patch: Partial<MediaSearchFilters>) {
		staged = { ...staged, ...patch };
	}

	let stagedChips = $derived(filterChips(staged, viewType));

	// The options are what "every option" is measured against; the sheet has already
	// loaded them, so the await resolves from the cache. Without them only the lists go
	// un-normalised — the search still runs.
	async function showResults() {
		const offered = await ensureFilterOptions(viewType).catch(() => ({}));
		onApply(normalizeFilters(staged, viewType, offered));
		open = false;
	}

	// Like the chips' Clear all: every filter goes, the sort stays (it isn't in the sheet).
	// The button goes with them, so focus moves to Show results first
	// (rules/frontend.md, "A control that removes itself hands focus on first").
	let showResultsButton = $state<HTMLElement | null>(null);
	function clearStaged() {
		showResultsButton?.focus();
		staged = omitKeys(staged, stagedChips.flatMap((c) => c.keys));
	}

	function toggleRated(state: RatedState) {
		const rated = staged.rated ?? [];
		stage({ rated: rated.includes(state) ? rated.filter((s) => s !== state) : [...rated, state] });
	}

	const WATCHLIST = [
		{ value: 'any', label: 'Any' },
		{ value: 'in', label: 'In list' },
		{ value: 'out', label: 'Not in list' },
	] as const;
	type WatchlistChoice = (typeof WATCHLIST)[number]['value'];
	let watchlistChoice = $derived<WatchlistChoice>(
		staged.watchlisted == null ? 'any' : staged.watchlisted ? 'in' : 'out',
	);

	// `TOP_PRESETS`, 75 among them for "everything but the weak ones". A shared link may
	// carry another value, which joins the list rather than reading as "Any".
	function topOptions(current: number | null | undefined) {
		const values = current != null && !TOP_PRESETS.includes(current)
			? [...TOP_PRESETS, current].sort((a, b) => a - b)
			: TOP_PRESETS;
		return [{ value: 0, label: 'Any' }, ...values.map((v) => ({ value: v, label: `${v}%` }))];
	}

	const RELEASE_LISTS: ListFilterKey[] = ['airing_status', 'anime_season'];
	const CONTENT_LISTS: ListFilterKey[] = ['studio_name', 'original_source', 'media_type', 'relation_type', 'age_rating'];
	const LENGTH_RANGES: RangeKey[] = ['episodes', 'duration_per_episode', 'total_watch_time'];

	const sectionCls = 'space-y-4 py-6 first:pt-0';
	const headingCls = 'text-sm font-semibold uppercase tracking-wide text-primary';
</script>

{#snippet listField(key: ListFilterKey, options: FilterOptions)}
	{@const field = LIST_FILTERS[key]}
	{#if !field.mediaOnly || viewType === 'media'}
		<div class="space-y-1.5">
			<div class="flex h-6 items-center justify-between">
				<span class={cls.fieldLabel}>{field.label}</span>
				{#if field.mode}
					{@const modeKey = field.mode}
					<SegmentedControl
						ariaLabel="{field.label} match mode"
						options={MATCH_MODES}
						value={listMode(staged, key)}
						onSelect={(v) => stage({ [modeKey]: v })}
					/>
				{/if}
			</div>
			<TagSelect
				placeholder="Add {field.label.toLowerCase()}..."
				options={options[key] ?? []}
				selectedItems={staged[key] ?? []}
				labelFor={field.format}
				onAdd={(item) => stage({ [key]: [...(staged[key] ?? []), item] })}
				onRemove={(item) => stage({ [key]: (staged[key] ?? []).filter((i) => i !== item) })}
			/>
		</div>
	{/if}
{/snippet}

{#snippet topField(key: 'top_percent' | 'your_top_percent', label: string)}
	<div class="flex items-center justify-between gap-2">
		<span class={cls.fieldLabel}>{label}</span>
		<SegmentedControl
			ariaLabel="{label} percent"
			size="md"
			stretchOnPhone
			options={topOptions(staged[key])}
			value={staged[key] ?? 0}
			onSelect={(v) => stage({ [key]: v || undefined })}
		/>
	</div>
{/snippet}

{#snippet rangeField(key: RangeKey, options: FilterOptions)}
	{@const range = RANGE_FILTERS[key]}
	{@const [minKey, maxKey] = rangeParams(key)}
	{@const min = options[minKey]}
	{@const max = options[maxKey]}
	{#if (!range.mediaOnly || viewType === 'media') && min != null && max != null}
		<DoubleRangeSlider
			label={range.label}
			bounds={[min, max]}
			value={[staged[minKey] ?? undefined, staged[maxKey] ?? undefined]}
			step={range.step}
			log={range.log}
			format={range.format}
			onCommit={([from, to]) => stage({ [minKey]: from, [maxKey]: to })}
		/>
	{/if}
{/snippet}

<Sheet.Root bind:open>
	<Sheet.Content side="right" class="w-full sm:max-w-md bg-card text-card-foreground gap-0">
		<Sheet.Header class="border-b border-border">
			<Sheet.Title class="text-card-foreground">Filters</Sheet.Title>
		</Sheet.Header>

		<div class="flex-1 overflow-y-auto px-4 pt-5 divide-y divide-border">
			{#await ensureFilterOptions(viewType)}
				<p class="text-sm text-muted-foreground">Loading filters...</p>
			{:then options}
				<section class={sectionCls}>
					<h3 class={headingCls}>Yours</h3>
					{#if isGuest}
						<p class="text-sm text-muted-foreground">
							Guest accounts have no ratings or watchlist to filter by.
						</p>
					{:else}
						<div class="space-y-1.5">
							<span class={cls.fieldLabel}>Rated</span>
							<!-- Columns set so each grain's states fill two even rows. -->
							<div class="grid gap-1.5 {viewType === 'anime' ? 'grid-cols-3' : 'grid-cols-2'}">
								{#each RATED_STATES[viewType] as state (state.value)}
									{@const on = staged.rated?.includes(state.value) ?? false}
									<button
										type="button"
										class="{cls.chip} justify-center {on ? cls.chipOn : cls.chipOff}"
										aria-pressed={on}
										onclick={() => toggleRated(state.value)}
									>{state.label}</button>
								{/each}
							</div>
						</div>
						<DoubleRangeSlider
							label="Your score"
							bounds={[0, 10]}
							value={[staged.your_score_min ?? undefined, staged.your_score_max ?? undefined]}
							step={ratingStep}
							format={(v) => formatScoreWithStep(v, ratingStep)}
							onCommit={([from, to]) => stage({ your_score_min: from, your_score_max: to })}
						/>
						{@render topField('your_top_percent', 'Your top')}
						<div class="flex items-center justify-between gap-2">
							<span class={cls.fieldLabel}>Watchlist</span>
							<SegmentedControl
								ariaLabel="Watchlist"
								size="md"
								stretchOnPhone
								options={[...WATCHLIST]}
								value={watchlistChoice}
								onSelect={(v) => stage({ watchlisted: v === 'any' ? undefined : v === 'in' })}
							/>
						</div>
					{/if}
				</section>

				<section class={sectionCls}>
					<h3 class={headingCls}>Release</h3>
					{#each RELEASE_LISTS as key (key)}{@render listField(key, options)}{/each}
					<div class="flex items-center gap-2">
						<Checkbox
							id="upcoming-main"
							checked={staged.upcoming_main ?? false}
							onCheckedChange={(v) => stage({ upcoming_main: v || undefined })}
						/>
						<Label for="upcoming-main" class="text-sm text-card-foreground cursor-pointer select-none">
							Upcoming main story
						</Label>
					</div>
				</section>

				<section class={sectionCls}>
					<h3 class={headingCls}>Score</h3>
					{@render rangeField('score', options)}
					{@render topField('top_percent', 'Top')}
					{@render rangeField('scored_by', options)}
				</section>

				<section class={sectionCls}>
					<h3 class={headingCls}>Content</h3>
					<GenreFilterField
						value={staged.genres}
						options={options.genre_name ?? []}
						onChange={(genres) => stage({ genres })}
					/>
					{#each CONTENT_LISTS as key (key)}{@render listField(key, options)}{/each}
				</section>

				<section class={sectionCls}>
					<h3 class={headingCls}>Length</h3>
					{#each LENGTH_RANGES as key (key)}{@render rangeField(key, options)}{/each}
				</section>
			{:catch}
				<p class="text-sm text-destructive">The filters could not be loaded.</p>
			{/await}
		</div>

		<Sheet.Footer class="border-t border-border flex-row items-center justify-between">
			{#if stagedChips.length}
				<Button variant="ghost" size="sm" class={cls.btnGhostDestructive} onclick={clearStaged}>
					Clear all
				</Button>
			{/if}
			<Button bind:ref={showResultsButton} class="ml-auto" onclick={showResults}>Show results</Button>
		</Sheet.Footer>
	</Sheet.Content>
</Sheet.Root>
