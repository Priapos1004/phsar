<script lang="ts">
	import { LayoutGrid, Table as TableIcon } from 'lucide-svelte';
	import { Label } from '$lib/components/ui/label';
	import TagSelect from '$lib/components/TagSelect.svelte';
	import DoubleRangeSlider from '$lib/components/DoubleRangeSlider.svelte';
	import { ratingsFilter } from '$lib/stores/ratingsFilter';
	import type { SortKey } from '$lib/utils/ratingStats';
	import { WATCH_STATUS_OPTIONS, type WatchStatus } from '$lib/types/api';
	import { formatDecimalDigits } from '$lib/utils/formatString';

	interface Props {
		genreOptions: string[];
		step: number;
	}

	let { genreOptions, step }: Props = $props();

	// One combined sort control (key + direction) — no separate direction toggle.
	const SORT_OPTIONS: { value: string; label: string; sort: SortKey; dir: 'asc' | 'desc' }[] = [
		{ value: 'score|desc', label: 'Score: high → low', sort: 'score', dir: 'desc' },
		{ value: 'score|asc', label: 'Score: low → high', sort: 'score', dir: 'asc' },
		{ value: 'title|asc', label: 'Title: A → Z', sort: 'title', dir: 'asc' },
		{ value: 'date|desc', label: 'Recently rated', sort: 'date', dir: 'desc' },
		{ value: 'malDelta|desc', label: 'Most above MAL', sort: 'malDelta', dir: 'desc' },
		{ value: 'malDelta|asc', label: 'Most below MAL', sort: 'malDelta', dir: 'asc' },
	];
	let sortValue = $derived(`${$ratingsFilter.sort}|${$ratingsFilter.sortDir}`);

	const PILL = 'px-3 py-1 rounded-full text-sm border transition-colors';
	const PILL_ON = 'border-primary bg-primary/15 text-primary';
	const PILL_OFF = 'border-white/15 text-white/60 hover:text-white hover:border-white/30';

	function toggleStatus(s: WatchStatus) {
		ratingsFilter.update((f) => ({
			...f,
			statuses: f.statuses.includes(s) ? f.statuses.filter((x) => x !== s) : [...f.statuses, s],
		}));
	}
</script>

<div class="space-y-3 mb-6">
	<div class="flex flex-wrap items-center gap-x-6 gap-y-3">
		<!-- View -->
		<div class="flex items-center gap-2">
			<Label class="text-white/50 text-xs uppercase tracking-wide">View</Label>
			<div class="flex gap-1.5">
				<button class="{PILL} inline-flex items-center gap-1.5 {$ratingsFilter.view === 'grid' ? PILL_ON : PILL_OFF}" onclick={() => ratingsFilter.update((f) => ({ ...f, view: 'grid' }))}>
					<LayoutGrid class="size-3.5" /> Grid
				</button>
				<button class="{PILL} inline-flex items-center gap-1.5 {$ratingsFilter.view === 'table' ? PILL_ON : PILL_OFF}" onclick={() => ratingsFilter.update((f) => ({ ...f, view: 'table' }))}>
					<TableIcon class="size-3.5" /> Table
				</button>
			</div>
		</div>

		<!-- Sort -->
		<div class="flex items-center gap-2">
			<Label class="text-white/50 text-xs uppercase tracking-wide">Sort</Label>
			<select
				class="rounded-md border border-white/15 bg-black/20 text-white/80 text-sm px-2.5 py-1.5 hover:border-white/30 focus:outline-none focus:border-primary"
				value={sortValue}
				onchange={(e) => {
					const opt = SORT_OPTIONS.find((o) => o.value === e.currentTarget.value);
					if (opt) ratingsFilter.update((f) => ({ ...f, sort: opt.sort, sortDir: opt.dir }));
				}}
			>
				{#each SORT_OPTIONS as opt}
					<option value={opt.value} class="bg-background text-foreground">{opt.label}</option>
				{/each}
			</select>
		</div>

		<!-- Status -->
		<div class="flex items-center gap-2">
			<Label class="text-white/50 text-xs uppercase tracking-wide">Status</Label>
			<div class="flex gap-1.5">
				{#each WATCH_STATUS_OPTIONS as opt}
					<button class="{PILL} {$ratingsFilter.statuses.includes(opt.value) ? PILL_ON : PILL_OFF}" onclick={() => toggleStatus(opt.value)}>
						{opt.label}
					</button>
				{/each}
			</div>
		</div>
	</div>

	<div class="flex flex-wrap items-start gap-x-6 gap-y-3">
		<!-- Genre filter -->
		<div class="space-y-1 min-w-[16rem] flex-grow max-w-md">
			<div class="flex items-center justify-between">
				<Label class="text-white/50 text-xs uppercase tracking-wide">Genres</Label>
				<div class="flex gap-1">
					<button class="px-2 py-0.5 rounded-full text-xs border transition-colors {$ratingsFilter.genreMode === 'any' ? PILL_ON : PILL_OFF}" onclick={() => ratingsFilter.update((f) => ({ ...f, genreMode: 'any' }))}>Any</button>
					<button class="px-2 py-0.5 rounded-full text-xs border transition-colors {$ratingsFilter.genreMode === 'all' ? PILL_ON : PILL_OFF}" onclick={() => ratingsFilter.update((f) => ({ ...f, genreMode: 'all' }))}>All</button>
				</div>
			</div>
			<TagSelect
				placeholder="Filter by genre…"
				options={genreOptions}
				selectedItems={$ratingsFilter.genres}
				onAdd={(g) => ratingsFilter.update((f) => ({ ...f, genres: [...f.genres, g] }))}
				onRemove={(g) => ratingsFilter.update((f) => ({ ...f, genres: f.genres.filter((x) => x !== g) }))}
			/>
		</div>

		<!-- Score range -->
		<div class="min-w-[15rem] flex-grow max-w-xs">
			<DoubleRangeSlider
				label="Score range"
				minValue={0}
				maxValue={10}
				step={step}
				from={$ratingsFilter.scoreMin}
				to={$ratingsFilter.scoreMax}
				onChange={({ from, to }) => ratingsFilter.update((f) => ({ ...f, scoreMin: from, scoreMax: to }))}
				formatDisplay={(v) => formatDecimalDigits(v, 1)}
			/>
		</div>
	</div>
</div>
