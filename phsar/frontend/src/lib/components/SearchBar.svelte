<script lang="ts" module>
	import type { MediaSearchFilters } from '$lib/utils/search';

	const NO_SEARCH: MediaSearchFilters = { query: '', search_type: 'title' };
</script>

<script lang="ts">
	// The query box, its mode, and the filter sheet (`FilterSheet`, which stages its own
	// edits). Everything here starts from `applied`, the search on screen, and nothing writes
	// back to it: typing and a mode are local until `onSearch` sends a new search, which
	// comes back as the next `applied`. One source and one direction is what keeps a reload,
	// a view switch and an open sheet from racing each other.
	import { getContext } from 'svelte';
	import { MediaQuery } from 'svelte/reactivity';
	import { SlidersHorizontal, Search } from 'lucide-svelte';
	import FilterSheet from '$lib/components/FilterSheet.svelte';
	import PillToggle from '$lib/components/PillToggle.svelte';
	import { Input } from '$lib/components/ui/input';
	import { Button } from '$lib/components/ui/button';
	import { SEARCH_MODE_LABELS, filterChips, withQuery, type SearchType, type ViewType } from '$lib/utils/search';
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

	let appliedCount = $derived(filterChips(applied, viewType).length);

	let modes = $derived([
		{ value: 'title' as const, label: SEARCH_MODE_LABELS.title },
		{ value: 'description' as const, label: SEARCH_MODE_LABELS.description },
		{
			value: 'rating_notes' as const, label: SEARCH_MODE_LABELS.rating_notes,
			disabled: isGuest, hint: isGuest ? 'Guest accounts have no notes to search' : undefined,
		},
	]);
	// A placeholder is text CSS cannot swap, so the width is read here; on a phone the
	// long one is cut off mid-word.
	const wide = new MediaQuery(cls.smUp);
	let placeholder = $derived(
		mode === 'description' ? (wide.current ? 'Describe a story, a character, a theme...' : 'Describe a story...')
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
</script>

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
<FilterSheet {viewType} {applied} bind:open={filtersOpen} onApply={(filters) => onSearch(withQuery(filters, query, mode))} />
