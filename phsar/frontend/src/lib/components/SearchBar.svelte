<script lang="ts" module>
	import type { MediaSearchFilters } from '$lib/utils/search';

	const NO_SEARCH: MediaSearchFilters = { query: '', search_type: 'title' };
</script>

<script lang="ts">
	// The query box, its mode, and the filter sheet. Everything here starts from `applied`,
	// the search on screen, and nothing writes back to it: typing, a mode and the sheet's
	// edits are local until `onSearch` sends a new search, which comes back as the next
	// `applied`. One source and one direction is what keeps a reload, a view switch and an
	// open sheet from racing each other.
	import { getContext } from 'svelte';
	import { SlidersHorizontal, Search } from 'lucide-svelte';
	import { ensureFilterOptions } from '$lib/stores/filterOptions';
	import TagSelect from '$lib/components/TagSelect.svelte';
	import DoubleRangeSlider from '$lib/components/DoubleRangeSlider.svelte';
	import PillToggle from '$lib/components/PillToggle.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { Input } from '$lib/components/ui/input';
	import { Button } from '$lib/components/ui/button';
	import { Checkbox } from '$lib/components/ui/checkbox';
	import { Label } from '$lib/components/ui/label';
	import * as Sheet from '$lib/components/ui/sheet';
	import {
		DEFAULT_MODE,
		LIST_FILTERS,
		RANGE_FILTERS,
		RATED_STATES,
		filterChips,
		normalizeRated,
		omitKeys,
		rangeParams,
		withQuery,
		type ListFilterKey,
		type RangeKey,
		type RatedState,
		type SearchType,
		type ViewType,
	} from '$lib/utils/search';
	import type { FilterOptions } from '$lib/types/api';
	import * as cls from '$lib/styles/classes';

	interface Props {
		viewType?: ViewType;
		onSearch?: (params: MediaSearchFilters) => void;
		/** The search on screen; the home page has none. */
		applied?: MediaSearchFilters;
		filtersOpen?: boolean;
	}

	let { viewType = 'anime', onSearch = () => {}, applied = NO_SEARCH, filtersOpen = $bindable(false) }: Props = $props();

	const getUserRole = getContext<(() => string | null) | undefined>('userRole');
	let isGuest = $derived(getUserRole?.() === 'restricted_user');

	// Follow the applied search; typing or picking a mode overrides them until the next one.
	let query = $derived(applied.query ?? '');
	let mode = $derived<SearchType>(applied.search_type ?? 'title');

	// The sheet edits a copy of the applied filters, taken afresh each time it opens, so
	// dismissing it throws the edits away and "Show results" applies them.
	let staged = $derived.by(() => {
		void filtersOpen;
		return $state.snapshot(applied) as MediaSearchFilters;
	});
	function stage(patch: Partial<MediaSearchFilters>) {
		staged = { ...staged, ...patch };
	}

	let appliedCount = $derived(filterChips(applied, viewType).length);
	let stagedChips = $derived(filterChips(staged, viewType));

	let modes = $derived([
		{ value: 'title' as const, label: 'Title' },
		{ value: 'description' as const, label: 'Description' },
		{
			value: 'rating_notes' as const, label: 'My notes',
			disabled: isGuest, hint: isGuest ? 'Guest accounts have no notes to search' : undefined,
		},
	]);
	let placeholder = $derived(
		mode === 'description' ? 'Describe a story, a character, a theme...'
			: mode === 'rating_notes' ? 'Search your notes...'
			: viewType === 'anime' ? 'Search anime...' : 'Search media...',
	);

	function submit() {
		onSearch(withQuery($state.snapshot(applied) as MediaSearchFilters, query, mode));
	}

	function handleSubmit(e: Event) {
		e.preventDefault();
		submit();
	}

	// A mode switches how the typed query is read, so it re-runs it; with nothing typed
	// there is nothing to re-run, and the mode waits for the query.
	function selectMode(next: SearchType) {
		mode = next;
		if (query.trim()) submit();
	}

	function showResults() {
		onSearch(normalizeRated(withQuery(staged, query, mode), viewType));
		filtersOpen = false;
	}

	// Like the chips' Clear all: every filter goes, the sort stays (it isn't in the sheet).
	function clearStaged() {
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

	// Preset cut-offs, 75 among them for "everything but the weak ones". A shared link may
	// carry another value, which joins the list rather than reading as "Any".
	const TOP_PRESETS = [5, 10, 20, 50, 75];
	let topOptions = $derived.by(() => {
		const current = staged.top_percent;
		const values = current != null && !TOP_PRESETS.includes(current)
			? [...TOP_PRESETS, current].sort((a, b) => a - b)
			: TOP_PRESETS;
		return [{ value: 0, label: 'Any' }, ...values.map((v) => ({ value: v, label: `${v}%` }))];
	});

	const MATCH_MODES = [{ value: 'any' as const, label: 'Any' }, { value: 'all' as const, label: 'All' }];

	const RELEASE_LISTS: ListFilterKey[] = ['airing_status', 'anime_season'];
	const CONTENT_LISTS: ListFilterKey[] = ['genre_name', 'studio_name', 'original_source', 'media_type', 'relation_type', 'age_rating'];
	const LENGTH_RANGES: RangeKey[] = ['episodes', 'duration_per_episode', 'total_watch_time'];

	const sectionCls = 'space-y-4 py-6 first:pt-0';
	const headingCls = 'text-sm font-semibold uppercase tracking-wide text-primary';
	const fieldLabelCls = 'text-sm font-medium text-card-foreground';
</script>

{#snippet listField(key: ListFilterKey, options: FilterOptions)}
	{@const field = LIST_FILTERS[key]}
	{#if !field.mediaOnly || viewType === 'media'}
		<div class="space-y-1.5">
			<div class="flex h-6 items-center justify-between">
				<span class={fieldLabelCls}>{field.label}</span>
				{#if field.mode}
					{@const modeKey = field.mode}
					<SegmentedControl
						ariaLabel="{field.label} match mode"
						options={MATCH_MODES}
						value={staged[modeKey] ?? DEFAULT_MODE[modeKey]}
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

<form onsubmit={handleSubmit} class="w-full max-w-xl mx-auto space-y-3">
	<div class="relative">
		<!-- Filter button on the left; search trigger on the right so mobile users can
		     tap to search instead of having to focus the field and press Enter.
		     z-10 is load-bearing: the input's backdrop-blur makes it a stacking context
		     painted in tree order, so without it the input would paint over the filter
		     button that precedes it in source and hide it. -->
		<Button
			type="button"
			variant="ghost"
			size="icon"
			class="absolute top-1/2 left-2 -translate-y-1/2 z-10 text-primary hover:text-primary/70"
			onclick={() => (filtersOpen = true)}
			aria-label="Filters"
		>
			<SlidersHorizontal class="w-5 h-5" />
			{#if appliedCount}
				<span class={cls.countBadge}>{appliedCount}</span>
			{/if}
		</Button>
		<Input
			type="text"
			bind:value={() => query, (v) => (query = v)}
			{placeholder}
			class="w-full h-12 pl-12 pr-12 rounded-full bg-card/80 backdrop-blur border-input"
		/>
		<Button
			type="submit"
			variant="ghost"
			size="icon"
			class="absolute top-1/2 right-2 -translate-y-1/2 z-10 text-primary hover:text-primary/70"
			aria-label="Search"
		>
			<Search class="w-5 h-5" />
		</Button>
	</div>

	<div class="flex justify-center">
		<PillToggle options={modes} value={mode} onSelect={selectMode} ariaLabel="What to search" />
	</div>
</form>

<!-- Outside the form: the sheet's buttons must never submit the query. -->
<Sheet.Root bind:open={filtersOpen}>
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
							<span class={fieldLabelCls}>Rated</span>
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
						<div class="flex items-center justify-between gap-2">
							<span class={fieldLabelCls}>Watchlist</span>
							<SegmentedControl
								ariaLabel="Watchlist"
								size="md"
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
					<div class="flex items-center justify-between gap-2">
						<span class={fieldLabelCls}>Top</span>
						<SegmentedControl
							ariaLabel="Top percent"
							size="md"
							options={topOptions}
							value={staged.top_percent ?? 0}
							onSelect={(v) => stage({ top_percent: v || undefined })}
						/>
					</div>
					{@render rangeField('scored_by', options)}
				</section>

				<section class={sectionCls}>
					<h3 class={headingCls}>Content</h3>
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
			<Button class="ml-auto" onclick={showResults}>Show results</Button>
		</Sheet.Footer>
	</Sheet.Content>
</Sheet.Root>
