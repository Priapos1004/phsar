<script lang="ts">
	import { LayoutGrid, Table as TableIcon } from 'lucide-svelte';
	import * as Card from '$lib/components/ui/card';
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import GrainToggle from '$lib/components/GrainToggle.svelte';
	import { watchlistFilter } from '$lib/stores/watchlistFilter';
	import { tags } from '$lib/stores/tags';
	import { contrastText } from '$lib/utils/color';
	import { PRIORITY_ACCENT, PRIORITY_OPTIONS } from '$lib/utils/watchlist';
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

	function toggleTag(uuid: string) {
		watchlistFilter.update((f) => ({
			...f,
			tagUuids: f.tagUuids.includes(uuid) ? f.tagUuids.filter((t) => t !== uuid) : [...f.tagUuids, uuid],
		}));
	}

	function togglePriority(p: number) {
		watchlistFilter.update((f) => ({
			...f,
			priorities: f.priorities.includes(p) ? f.priorities.filter((x) => x !== p) : [...f.priorities, p],
		}));
	}

	let hasActiveFilters = $derived($watchlistFilter.tagUuids.length > 0 || $watchlistFilter.priorities.length > 0);
	function clearFilters() {
		watchlistFilter.update((f) => ({ ...f, tagUuids: [], priorities: [] }));
	}

	const PILL_ON = 'border-primary bg-primary/15 text-primary font-medium';
	const PILL_OFF = 'border-white/15 text-white/60 hover:text-white hover:border-white/30';
	const pill = 'px-3.5 py-1.5 rounded-full text-sm border transition-colors inline-flex items-center gap-1.5';
	const labelCls = 'text-muted-foreground text-xs uppercase tracking-wide';
</script>

<div class="space-y-3 mb-4 relative z-20">
	<!-- View (left) + grain toggle (right) -->
	<div class="flex flex-wrap items-center gap-2">
		<button class="{pill} {$watchlistFilter.view === 'grid' ? PILL_ON : PILL_OFF}" onclick={() => watchlistFilter.update((f) => ({ ...f, view: 'grid' }))}>
			<LayoutGrid class="size-3.5" /> Grid
		</button>
		<button class="{pill} {$watchlistFilter.view === 'table' ? PILL_ON : PILL_OFF}" onclick={() => watchlistFilter.update((f) => ({ ...f, view: 'table' }))}>
			<TableIcon class="size-3.5" /> Table
		</button>

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
				<div class="bg-card/80 backdrop-blur border border-input rounded-xl px-2 min-h-[48px] flex flex-wrap items-center gap-1.5 py-1.5">
					{#each PRIORITY_OPTIONS as opt (opt.value)}
						{@const on = $watchlistFilter.priorities.includes(opt.value)}
						{@const acc = PRIORITY_ACCENT[opt.value]}
						<button
							class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors inline-flex items-center gap-1.5 border border-transparent {on ? `${acc.dot} text-white shadow-sm` : 'bg-muted text-card-foreground/70 hover:bg-muted/70'}"
							onclick={() => togglePriority(opt.value)}
						>
							<!-- Dot stays visible and switches color (white on the selected accent-filled
							     chip, the accent color when unselected) — mirrors the Lists filter chips. -->
							<span class="size-2.5 rounded-full {on ? 'bg-white' : acc.dot}"></span>
							{opt.label}
						</button>
					{/each}
				</div>
			</div>

			<!-- Lists (tags): multi-select union — pick several to see them combined. -->
			<div class="space-y-1.5 flex-grow min-w-[14rem]">
				<div class="flex h-7 items-center"><Label class={labelCls}>Lists</Label></div>
				<div class="bg-card/80 backdrop-blur border border-input rounded-xl px-2 min-h-[48px] flex flex-wrap items-center gap-1.5 py-1.5">
					{#each $tags as tag (tag.uuid)}
						{@const on = $watchlistFilter.tagUuids.includes(tag.uuid)}
						{@const contrast = contrastText(tag.color)}
						<button
							class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors inline-flex items-center gap-1.5 border {on ? 'shadow-sm' : 'bg-muted text-card-foreground/70 border-transparent hover:bg-muted/70'}"
							style={on ? `background:${tag.color}; border-color:${tag.color}; color:${contrast}` : ''}
							onclick={() => toggleTag(tag.uuid)}
						>
							<!-- Selected: dot uses the pill's contrast color so a white/yellow list stays
								 visible; unselected: the list color with a faint border. -->
							<span class="size-2.5 rounded-full {on ? '' : 'border border-border'}" style="background:{on ? contrast : tag.color}"></span>
							{tag.name}
						</button>
					{/each}
				</div>
			</div>
		</Card.Content>
	</Card.Root>
</div>
