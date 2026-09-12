<script lang="ts">
	import * as cls from '$lib/styles/classes';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import SpoilerGuard from '$lib/components/SpoilerGuard.svelte';
	import { StickyNote } from 'lucide-svelte';
	import { visibleMediaSet } from '$lib/stores/spoilerVisibility';
	import { tagGradient, joinNoteTexts, READY_BADGE } from '$lib/utils/watchlist';
	import type { WatchlistRow } from '$lib/utils/watchlistStats';

	interface Props {
		row: WatchlistRow;
	}

	let { row }: Props = $props();

	let imgFailed = $state(false);
	// One tag → solid dot; several (an anime spanning lists) → a crisp banded gradient.
	let dotBg = $derived(tagGradient(row.colors));
	// Undefined for a plainly-ready anime (`READY_BADGE.ready`) and for every media row
	// (no verdict at that grain), so most cards stay unbadged.
	let badge = $derived(row.readyStatus ? READY_BADGE[row.readyStatus] : undefined);
</script>

<a href={row.href} data-focus-uuid={row.detailUuid} class="group block transition duration-200 hover:-translate-y-0.5">
	<div class="{cls.cardGlass} rounded-xl overflow-hidden border border-border h-full flex flex-col shadow-sm group-hover:shadow-md group-hover:ring-1 group-hover:ring-primary/40 transition">
		<div class="relative">
			{#snippet cover()}
				{#if row.coverImage && !imgFailed}
					<img src={row.coverImage} alt={`Cover of ${row.title}`} class="w-full aspect-[2/3] object-cover" loading="lazy" onerror={() => (imgFailed = true)} />
				{:else}
					<div class="w-full aspect-[2/3] bg-muted flex items-center justify-center text-muted-foreground text-sm italic">No image</div>
				{/if}
			{/snippet}
			<!-- Media covers are spoiler-guarded; anime covers (anime grain) never are. -->
			{#if row.spoilerMediaUuid}
				<SpoilerGuard visible={$visibleMediaSet.has(row.spoilerMediaUuid)} mode="image">{@render cover()}</SpoilerGuard>
			{:else}
				{@render cover()}
			{/if}

			<!-- Tag color (top-left) — absolute wraps the Tooltip so the popup anchors to the dot -->
			<div class="absolute top-1.5 left-1.5">
				<Tooltip text={row.tagLabel}>
					<span class="block size-4 rounded-full ring-2 ring-white/60 shadow" style="background:{dotBg}"></span>
				</Tooltip>
			</div>

			{#if row.note}
				<!-- "Has a note" — hover shows the note text -->
				<div class="absolute top-1.5 right-1.5">
					<Tooltip text={row.note}>
						<span class="block rounded-md bg-black/45 p-1 backdrop-blur-sm">
							<StickyNote class="size-3.5 text-white" />
						</span>
					</Tooltip>
				</div>
			{:else if row.noteCount > 0}
				<!-- Anime grain: hover shows each noted media's note (media-table order) -->
				<div class="absolute top-1.5 right-1.5">
					<Tooltip text={joinNoteTexts(row.noteTexts)} contentClass="whitespace-pre-line">
						<span class="flex items-center gap-0.5 rounded-md bg-black/45 px-1.5 py-1 text-[11px] font-medium text-white backdrop-blur-sm">
							<StickyNote class="size-3" />{row.noteCount}
						</span>
					</Tooltip>
				</div>
			{/if}
		</div>

		<div class="p-2.5 flex flex-col gap-1.5 flex-grow">
			<h3 class="text-sm font-medium text-card-foreground line-clamp-2 leading-snug" title={row.title}>{row.title}</h3>
			{#if row.subtitle}<span class="text-xs text-muted-foreground line-clamp-1" title={row.subtitle}>{row.subtitle}</span>{/if}
			<!-- Anime grain shows the main/side breakdown; media grain the relation type (mutually
			     exclusive). The readiness badge sits beside it rather than over the cover, where
			     it competes with the tag dot and the note icon and is easy to miss. -->
			{#if row.mainSide || row.relationLabel || badge}
				<div class="mt-auto flex flex-wrap items-center gap-1.5">
					{#if row.mainSide || row.relationLabel}
						<span class={cls.mutedPill}>{row.mainSide ?? row.relationLabel}</span>
					{/if}
					{#if badge}
						<!-- Pill classes go on the Tooltip's own trigger span, not a span inside
						     it: nested, the pill is an inline box whose vertical padding adds no
						     height, so it renders shorter than the mutedPill beside it. -->
						<Tooltip text={badge.title} class="{cls.readyPill} {badge.class}">{badge.label}</Tooltip>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</a>
