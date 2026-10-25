<script lang="ts">
	import { Ban } from 'lucide-svelte';
	import * as Card from '$lib/components/ui/card';
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import GrainToggle from '$lib/components/GrainToggle.svelte';
	import ViewToggle from '$lib/components/ViewToggle.svelte';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import { watchlistFilter, type WatchlistFilterState } from '$lib/stores/watchlistFilter';
	import { tags } from '$lib/stores/tags';
	import { contrastText } from '$lib/utils/color';
	import { PRIORITY_ACCENT, PRIORITY_OPTIONS, READY_FILTERS, WATCHTIME_FILTERS } from '$lib/utils/watchlist';
	import * as cls from '$lib/styles/classes';

	// Prune deleted tags from the selection so a filter that pointed at a now-deleted
	// list collapses back to "all" (an empty selection) instead of showing nothing.
	$effect(() => {
		const valid = new Set($tags.map((t) => t.uuid));
		const pruned = $watchlistFilter.tagUuids.filter((u) => valid.has(u));
		if (pruned.length !== $watchlistFilter.tagUuids.length) {
			watchlistFilter.update((f) => ({ ...f, tagUuids: pruned }));
		}
	});

	// Every chip group is a multi-select: an empty array means "all", and clicking flips one
	// value in or out. Named once so "Clear all" and the active-filter check derive from the
	// same list — a group added to the toggles but forgotten in `clearFilters` is a filter
	// the user cannot switch off, and nothing type-checks that omission.
	const UNION_FIELDS = ['tagUuids', 'priorities', 'readiness', 'watchtime'] as const;
	// `satisfies`, not a cast: a group listed above but missing here is a compile error.
	// `tagMode` rides along: alone it filters nothing, so it is never an active filter, but a
	// clear still resets it, like the ratings genre mode.
	const CLEARED = { tagUuids: [], tagMode: 'include', priorities: [], readiness: [], watchtime: [] } satisfies Pick<
		WatchlistFilterState,
		(typeof UNION_FIELDS)[number] | 'tagMode'
	>;

	function toggle<K extends (typeof UNION_FIELDS)[number]>(key: K, value: WatchlistFilterState[K][number]) {
		watchlistFilter.update((f) => {
			const current = f[key] as WatchlistFilterState[K][number][];
			return { ...f, [key]: current.includes(value) ? current.filter((x) => x !== value) : [...current, value] };
		});
	}

	let hasActiveFilters = $derived(UNION_FIELDS.some((k) => $watchlistFilter[k].length > 0));
	function clearFilters() {
		watchlistFilter.update((f) => ({ ...f, ...CLEARED }));
	}

	const labelCls = 'text-muted-foreground text-xs uppercase tracking-wide';
</script>

<div class="space-y-3 mb-4 relative z-20">
	<!-- View (left) + grain toggle (right) -->
	<div class="flex flex-wrap items-center gap-2">
		<ViewToggle view={$watchlistFilter.view} onSelect={(v) => watchlistFilter.update((f) => ({ ...f, view: v }))} />

		<div class="flex-grow"></div>

		<!-- Grain: group by anime (default) or show every media entry -->
		<GrainToggle grain={$watchlistFilter.grain} onSelect={(g) => watchlistFilter.update((f) => ({ ...f, grain: g }))} />
	</div>

	<Card.Root class="{cls.cardGlass} overflow-visible relative">
		{#if hasActiveFilters}
			<Button variant="ghost" size="sm" class="absolute top-2 right-2 z-10 {cls.btnGhostDestructive}" onclick={clearFilters}>
				Clear all
			</Button>
		{/if}
		<Card.Content class="flex flex-wrap items-start gap-x-6 gap-y-4 py-4">
			<!-- Priority: multi-select union filter (replaces the old band-order arrow — filtering
			     to the bands you care about is more useful than flipping their order). Selected chip
			     takes the band's accent color so it matches the grid band headers. -->
			<div class="space-y-1.5">
				<div class="flex h-7 items-center"><Label class={labelCls}>Priority</Label></div>
				<div class={cls.chipGroup}>
					{#each PRIORITY_OPTIONS as opt (opt.value)}
						{@const on = $watchlistFilter.priorities.includes(opt.value)}
						{@const acc = PRIORITY_ACCENT[opt.value]}
						<button
							class="{cls.chip} {on ? `${acc.dot} text-white shadow-sm` : cls.chipOff}"
							aria-pressed={on}
							onclick={() => toggle('priorities', opt.value)}
						>
							<!-- Dot stays visible and switches color (white on the selected accent-filled
							     chip, the accent color when unselected) — mirrors the Lists filter chips. -->
							<span class="size-2.5 rounded-full {on ? 'bg-white' : acc.dot}"></span>
							{opt.label}
						</button>
					{/each}
				</div>
			</div>

			<!-- Readiness: a multi-select union like Priority and Lists, over the same verdicts
			     the anime-grain badges show. The Lists chips beside it SCOPE these verdicts
			     while Priority and Watchtime cannot; the order in
			     utils/watchlistStats.buildWatchlistView decides which. -->
			<div class="space-y-1.5">
				<div class="flex h-7 items-center"><Label class={labelCls}>Status</Label></div>
				<div class={cls.chipGroup}>
					{#each READY_FILTERS as opt (opt.key)}
						{@const on = $watchlistFilter.readiness.includes(opt.key)}
						<Tooltip text={opt.title}>
							{#snippet trigger(props)}
								<button
									{...props}
									class="{cls.chip} {on ? `${opt.class} shadow-sm` : cls.chipOff}"
									aria-pressed={on}
									onclick={() => toggle('readiness', opt.key)}
								>
									{opt.label}
								</button>
							{/snippet}
						</Tooltip>
					{/each}
				</div>
			</div>

			<!-- Watchtime: a union like the rest, over the size band each row's badge shows. -->
			<div class="space-y-1.5">
				<div class="flex h-7 items-center"><Label class={labelCls}>Watchtime</Label></div>
				<div class={cls.chipGroup}>
					{#each WATCHTIME_FILTERS as opt (opt.key)}
						{@const on = $watchlistFilter.watchtime.includes(opt.key)}
						<Tooltip text={opt.title}>
							{#snippet trigger(props)}
								<button
									{...props}
									class="{cls.chip} {on ? `${opt.fill} shadow-sm` : cls.chipOff}"
									aria-pressed={on}
									onclick={() => toggle('watchtime', opt.key)}
								>
									{opt.label}
								</button>
							{/snippet}
						</Tooltip>
					{/each}
				</div>
			</div>

			<!-- Lists: always a row of its own, because its mode toggle is right-aligned like the
			     ratings genre toggle, and on the first row it would sit under the pinned "Clear all". -->
			<div class="space-y-1.5 basis-full min-w-0">
				<div class="flex h-7 items-center justify-between">
					<Label class={labelCls}>Lists</Label>
					<SegmentedControl
						ariaLabel="List match mode"
						options={[{ value: 'include', label: 'In' }, { value: 'exclude', label: 'Not in' }]}
						value={$watchlistFilter.tagMode}
						onSelect={(v) => watchlistFilter.update((f) => ({ ...f, tagMode: v }))}
					/>
				</div>
				<div class={cls.chipGroup}>
					{#each $tags as tag (tag.uuid)}
						{@const on = $watchlistFilter.tagUuids.includes(tag.uuid)}
						{@const excluded = on && $watchlistFilter.tagMode === 'exclude'}
						{@const contrast = contrastText(tag.color)}
						<!-- A picked list under "Not in" is switched off rather than lit: the off chip, tinted
						     by its list and ringed in the theme, so it reads apart from an unpicked one. -->
						{@const chipStyle = excluded
							? `background:color-mix(in oklab, ${tag.color} 20%, var(--color-muted)); border-color:var(--primary); box-shadow:0 0 10px -2px var(--primary)`
							: on
								? `background:${tag.color}; border-color:${tag.color}; color:${contrast}`
								: ''}
						<!-- max-w-full + a truncating name: a list name in a control (rules/frontend.md, "A user's string can be one long word"). -->
						<button
							class="{cls.chip} max-w-full {on && !excluded ? 'shadow-sm' : cls.chipOff}"
							aria-pressed={on}
							title={tag.name}
							style={chipStyle}
							onclick={() => toggle('tagUuids', tag.uuid)}
						>
							{#if excluded}
								<!-- The icon overflows a slot the dot's size, so switching a chip off never
								     resizes it or reflows the chips after it. -->
								<span class="flex size-2.5 shrink-0 items-center justify-center">
									<Ban class="size-3.5 shrink-0 {cls.glassTint} drop-shadow-[0_0_3px_var(--primary)]" aria-hidden="true" />
								</span>
							{:else}
								<!-- Selected: dot uses the pill's contrast color so a white/yellow list stays
									 visible; unselected: the list color with a faint border. -->
								<span class="size-2.5 shrink-0 rounded-full {on ? '' : 'border border-border'}" style="background:{on ? contrast : tag.color}"></span>
							{/if}
							<span class="truncate">{tag.name}</span>
						</button>
					{/each}
				</div>
			</div>
		</Card.Content>
	</Card.Root>
</div>
