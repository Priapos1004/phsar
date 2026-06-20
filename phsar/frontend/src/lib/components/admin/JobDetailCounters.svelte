<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import type { UpdateSweepCounters } from '$lib/types/api';

	interface Props {
		counters: UpdateSweepCounters;
		// Sweep schema version — selects the media-grained HEAD (v5+) vs the
		// anime-grained one (v2–v4).
		version: number;
		merge_detect_failed?: boolean;
		cache_recompute_failed?: boolean;
	}
	let { counters, version, merge_detect_failed, cache_recompute_failed }: Props = $props();

	type Stat = { key: keyof UpdateSweepCounters; label: string; tooltip?: string };

	// Only the leading refresh/rollup rows differ by version. v5 (v0.14.8)
	// went media-grained: anime_refreshed → media_refreshed, and the
	// anime_with_* rollups were replaced by anime_touched + media_skipped.
	// The trailing rows are identical across v2–v5, so they live once below.
	const HEAD: Stat[] = $derived(
		version >= 5
			? [
					{ key: 'media_refreshed', label: 'Media refreshed' },
					{
						key: 'anime_touched',
						label: 'Anime touched',
						tooltip: 'Distinct anime with at least one media refreshed this run.',
					},
					{
						key: 'media_skipped_fresh',
						label: 'Media skipped',
						tooltip:
							'Media belonging to the touched anime that were not refreshed this run — already fresh (or, at the cap boundary, due but deferred to the next sweep).',
					},
				]
			: [
					{ key: 'anime_refreshed', label: 'Anime touched' },
					{ key: 'anime_with_dynamic_changes', label: 'Anime w/ dynamic' },
					{ key: 'anime_with_static_changes', label: 'Anime w/ static' },
				],
	);
	// Failure counts (step1_failed / probe_failed) intentionally NOT here —
	// the amber "Failed refresh" / "Failed probe" cards below carry the count
	// in their headings, so a grid cell would just duplicate the signal.
	const TAIL: Stat[] = [
		{
			key: 'media_with_dynamic_changes',
			label: 'Media w/ dynamic',
			tooltip:
				'Media whose volatile fields changed: episodes, airing_status, aired_to, score, scored_by.',
		},
		{
			key: 'media_with_static_changes',
			label: 'Media w/ static',
			tooltip:
				'Media whose rarely-changing metadata changed: title, names, description, cover, age rating, original source.',
		},
		{
			key: 'umbrella_reclassed',
			label: 'Anime changed',
			tooltip:
				"Anime whose top-level fields drifted (title, names, description, cover, mal_id) — often just a cover-image refresh, not a re-classification.",
		},
		{
			key: 'probe_succeeded',
			label: 'Probes succeeded',
			tooltip: 'Anime whose step-2 relations probe ran cleanly.',
		},
		{
			key: 'probe_attached_anime_count',
			label: 'Anime w/ new media',
			tooltip:
				'Anime where the step-2 relations probe attached newly-discovered media this run.',
		},
		{
			key: 'orphaned_studios_removed',
			label: 'Orphaned studios removed',
			tooltip: 'Studios removed because they no longer link to any media.',
		},
	];
	const STATS: Stat[] = $derived([...HEAD, ...TAIL]);
</script>

<Card.Root>
	<Card.Header>
		<h2 class="text-lg font-semibold text-card-foreground">Sweep counters</h2>
	</Card.Header>
	<Card.Content>
		<dl class="grid grid-cols-3 md:grid-cols-5 gap-4">
			{#each STATS as stat (stat.key)}
				{@const value = counters[stat.key] ?? 0}
				{#snippet card(props: Record<string, unknown>)}
					<div
						{...props}
						class="rounded-md border border-border/60 bg-muted/10 p-3 {stat.tooltip
							? 'cursor-help'
							: ''}"
					>
						<dt class="text-[10px] uppercase tracking-wider text-muted-foreground">{stat.label}</dt>
						<dd class="text-xl font-semibold tabular-nums mt-1 text-card-foreground">
							{value}
						</dd>
					</div>
				{/snippet}
				{#if stat.tooltip}
					<Tooltip text={stat.tooltip}>
						{#snippet trigger(props)}{@render card(props)}{/snippet}
					</Tooltip>
				{:else}
					{@render card({})}
				{/if}
			{/each}
		</dl>
		{#if merge_detect_failed || cache_recompute_failed}
			<ul class="mt-4 space-y-1 text-xs text-amber-400">
				{#if merge_detect_failed}
					<li>· Post-sweep merge detection failed (catalog work still committed).</li>
				{/if}
				{#if cache_recompute_failed}
					<li>· Spoiler cache recompute failed (catalog work still committed).</li>
				{/if}
			</ul>
		{/if}
	</Card.Content>
</Card.Root>
