<script lang="ts">
	import { LayoutGrid, Table as TableIcon, ArrowDown, ArrowUp } from 'lucide-svelte';
	import * as Card from '$lib/components/ui/card';
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import TagSelect from '$lib/components/TagSelect.svelte';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { ratingsFilter } from '$lib/stores/ratingsFilter';
	import { AGE_RATING_LABELS } from '$lib/utils/formatString';
	import * as cls from '$lib/styles/classes';

	interface Props {
		genreOptions: string[];
		ageOptions: number[];
		seasonOptions: string[];
	}

	let { genreOptions, ageOptions, seasonOptions }: Props = $props();

	function toggleAge(age: number) {
		ratingsFilter.update((f) => ({
			...f,
			ageRatings: f.ageRatings.includes(age) ? f.ageRatings.filter((a) => a !== age) : [...f.ageRatings, age],
		}));
	}

	// Only the value filters (not view / sort / order, which are display prefs).
	let hasActiveFilters = $derived(
		$ratingsFilter.genres.length > 0 || $ratingsFilter.ageRatings.length > 0 || $ratingsFilter.seasons.length > 0,
	);
	function clearFilters() {
		ratingsFilter.update((f) => ({ ...f, genres: [], genreMode: 'any', ageRatings: [], seasons: [] }));
	}

	// View pills — identical sizing to the Statistics inner-nav (px-3.5 py-1.5) so the
	// control row doesn't jump when switching top-level tabs. On the dark page bg.
	const VIEW_ON = 'border-primary bg-primary/15 text-primary font-medium';
	const VIEW_OFF = 'border-white/15 text-white/60 hover:text-white hover:border-white/30';
	// In-card controls sit on the WHITE card, so inactive text is card-foreground (dark),
	// never the light page `foreground` token. Selected = solid primary; resting = muted.
	const CHIP_ON = 'bg-primary text-white shadow-sm';
	const CHIP_OFF = 'bg-muted text-card-foreground/70 hover:bg-muted/70';
	const labelCls = 'text-muted-foreground text-xs uppercase tracking-wide';
</script>

<!-- relative z-20 lifts the filter (and its genre dropdown) above the results card,
     which creates its own stacking context via backdrop-blur and would otherwise
     paint over the dropdown. -->
<div class="space-y-3 mb-4 relative z-20">
	<!-- View selection -->
	<div class="flex gap-2">
		<button
			class="px-3.5 py-1.5 rounded-full text-sm border transition-colors inline-flex items-center gap-1.5 {$ratingsFilter.view === 'grid' ? VIEW_ON : VIEW_OFF}"
			onclick={() => ratingsFilter.update((f) => ({ ...f, view: 'grid' }))}
		>
			<LayoutGrid class="size-3.5" /> Grid
		</button>
		<button
			class="px-3.5 py-1.5 rounded-full text-sm border transition-colors inline-flex items-center gap-1.5 {$ratingsFilter.view === 'table' ? VIEW_ON : VIEW_OFF}"
			onclick={() => ratingsFilter.update((f) => ({ ...f, view: 'table' }))}
		>
			<TableIcon class="size-3.5" /> Table
		</button>
	</div>

	<!-- Filter / order card. overflow-visible so the genre/season dropdowns can extend
	     past the card edge (shadcn Card.Root is overflow-hidden by default). items-start
	     + an h-7 header per block keeps all the titles on one line. -->
	<Card.Root class="{cls.cardGlass} overflow-visible relative">
		<!-- Clear button matches the search-bar filter clear (ghost + destructive +
		     hover bg). Absolutely positioned so toggling it never reflows the filters
		     below — it sits in the empty top-right corner above them. -->
		{#if hasActiveFilters}
			<Button
				variant="ghost"
				size="sm"
				class="absolute top-2 right-2 z-10 text-destructive hover:text-destructive hover:bg-destructive/10"
				onclick={clearFilters}
			>
				Clear all
			</Button>
		{/if}
		<Card.Content class="flex flex-wrap items-start gap-x-6 gap-y-4 py-4">
			{#if $ratingsFilter.view === 'grid'}
				<!-- Grid order: the score bands are fixed; this arrow just flips whether 10 or
				     0 sits on top. Within each band the order (rating, then title) never changes. -->
				<div class="space-y-1.5">
					<div class="flex h-7 items-center"><Label class={labelCls}>Order</Label></div>
					<Tooltip text={$ratingsFilter.bandDir === 'desc' ? 'Highest score first (click for lowest)' : 'Lowest score first (click for highest)'}>
						{#snippet trigger(props)}
							<button
								{...props}
								class="size-12 rounded-xl bg-card/80 backdrop-blur border border-input flex items-center justify-center text-card-foreground hover:bg-muted transition-colors"
								aria-label="Toggle score order"
								onclick={() => ratingsFilter.update((f) => ({ ...f, bandDir: f.bandDir === 'desc' ? 'asc' : 'desc' }))}
							>
								{#if $ratingsFilter.bandDir === 'desc'}<ArrowDown class="size-4" />{:else}<ArrowUp class="size-4" />{/if}
							</button>
						{/snippet}
					</Tooltip>
				</div>
			{/if}

			<div class="space-y-1.5 flex-grow min-w-[14rem] max-w-md">
				<div class="flex h-7 items-center justify-between">
					<Label class={labelCls}>Genres</Label>
					<SegmentedControl
						ariaLabel="Genre match mode"
						options={[{ value: 'any', label: 'Any' }, { value: 'all', label: 'All' }]}
						value={$ratingsFilter.genreMode}
						onSelect={(v) => ratingsFilter.update((f) => ({ ...f, genreMode: v }))}
					/>
				</div>
				<TagSelect
					placeholder="Filter by genre…"
					options={genreOptions}
					selectedItems={$ratingsFilter.genres}
					onAdd={(g) => ratingsFilter.update((f) => ({ ...f, genres: [...f.genres, g] }))}
					onRemove={(g) => ratingsFilter.update((f) => ({ ...f, genres: f.genres.filter((x) => x !== g) }))}
				/>
			</div>

			{#if seasonOptions.length}
				<div class="space-y-1.5 flex-grow min-w-[12rem] max-w-xs">
					<div class="flex h-7 items-center"><Label class={labelCls}>Season</Label></div>
					<TagSelect
						placeholder="Filter by season…"
						options={seasonOptions}
						selectedItems={$ratingsFilter.seasons}
						onAdd={(s) => ratingsFilter.update((f) => ({ ...f, seasons: [...f.seasons, s] }))}
						onRemove={(s) => ratingsFilter.update((f) => ({ ...f, seasons: f.seasons.filter((x) => x !== s) }))}
					/>
				</div>
			{/if}

			{#if ageOptions.length}
				<div class="space-y-1.5">
					<div class="flex h-7 items-center"><Label class={labelCls}>Age rating</Label></div>
					<!-- Chips live in a box mirroring the TagSelect (same border / radius /
					     min-height) so the filters line up; filled-chip toggle reads cleanly. -->
					<div class="bg-card/80 backdrop-blur border border-input rounded-xl px-2 min-h-[48px] flex flex-wrap items-center gap-1.5">
						{#each ageOptions as age (age)}
							<button
								class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors {$ratingsFilter.ageRatings.includes(age) ? CHIP_ON : CHIP_OFF}"
								onclick={() => toggleAge(age)}
							>{AGE_RATING_LABELS[age] ?? age}</button>
						{/each}
					</div>
				</div>
			{/if}
		</Card.Content>
	</Card.Root>
</div>
