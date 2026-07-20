<script lang="ts">
	import { LayoutGrid, Table as TableIcon, ArrowDown, ArrowUp } from 'lucide-svelte';
	import * as Card from '$lib/components/ui/card';
	import { Button } from '$lib/components/ui/button';
	import { Label } from '$lib/components/ui/label';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import { watchlistFilter } from '$lib/stores/watchlistFilter';
	import { tags } from '$lib/stores/tags';
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

	let hasActiveFilters = $derived($watchlistFilter.tagUuids.length > 0);
	function clearFilters() {
		watchlistFilter.update((f) => ({ ...f, tagUuids: [] }));
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
		<div class="inline-flex rounded-full border border-white/15 overflow-hidden">
			<button class="px-3 py-1.5 text-sm transition-colors {$watchlistFilter.grain === 'anime' ? 'bg-primary/15 text-primary font-medium' : 'text-white/60 hover:text-white'}" onclick={() => watchlistFilter.update((f) => ({ ...f, grain: 'anime' }))}>
				Anime
			</button>
			<button class="px-3 py-1.5 text-sm transition-colors border-l border-white/15 {$watchlistFilter.grain === 'media' ? 'bg-primary/15 text-primary font-medium' : 'text-white/60 hover:text-white'}" onclick={() => watchlistFilter.update((f) => ({ ...f, grain: 'media' }))}>
				Media
			</button>
		</div>
	</div>

	<Card.Root class="{cls.cardGlass} overflow-visible relative">
		{#if hasActiveFilters}
			<Button variant="ghost" size="sm" class="absolute top-2 right-2 z-10 text-destructive hover:text-destructive hover:bg-destructive/10" onclick={clearFilters}>
				Clear all
			</Button>
		{/if}
		<Card.Content class="flex flex-wrap items-start gap-x-6 gap-y-4 py-4">
			{#if $watchlistFilter.view === 'grid'}
				<div class="space-y-1.5">
					<div class="flex h-7 items-center"><Label class={labelCls}>Order</Label></div>
					<Tooltip text={$watchlistFilter.bandDir === 'desc' ? 'High priority first (click for low)' : 'Low priority first (click for high)'}>
						{#snippet trigger(props)}
							<button
								{...props}
								class="size-12 rounded-xl bg-card/80 backdrop-blur border border-input flex items-center justify-center text-card-foreground hover:bg-muted transition-colors"
								aria-label="Toggle priority order"
								onclick={() => watchlistFilter.update((f) => ({ ...f, bandDir: f.bandDir === 'desc' ? 'asc' : 'desc' }))}
							>
								{#if $watchlistFilter.bandDir === 'desc'}<ArrowDown class="size-4" />{:else}<ArrowUp class="size-4" />{/if}
							</button>
						{/snippet}
					</Tooltip>
				</div>
			{/if}

			<!-- Lists (tags): multi-select union — pick several to see them combined. -->
			<div class="space-y-1.5 flex-grow min-w-[14rem]">
				<div class="flex h-7 items-center"><Label class={labelCls}>Lists</Label></div>
				<div class="bg-card/80 backdrop-blur border border-input rounded-xl px-2 min-h-[48px] flex flex-wrap items-center gap-1.5 py-1.5">
					{#each $tags as tag (tag.uuid)}
						{@const on = $watchlistFilter.tagUuids.includes(tag.uuid)}
						<button
							class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors inline-flex items-center gap-1.5 border {on ? 'text-white shadow-sm' : 'bg-muted text-card-foreground/70 border-transparent hover:bg-muted/70'}"
							style={on ? `background:${tag.color}; border-color:${tag.color}` : ''}
							onclick={() => toggleTag(tag.uuid)}
						>
							<span class="size-2.5 rounded-full {on ? 'bg-white/80' : ''}" style={on ? '' : `background:${tag.color}`}></span>
							{tag.name}
						</button>
					{/each}
				</div>
			</div>
		</Card.Content>
	</Card.Root>
</div>
