<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import type { UpdateSweepCounters } from '$lib/types/api';

	interface Props {
		counters: UpdateSweepCounters;
		// Sweep schema version — gates the step1_failed cell, which only
		// exists from v4 (older rows render "—", not a misleading 0).
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
					{ key: 'anime_touched', label: 'Anime touched' },
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
	const TAIL: Stat[] = [
		{ key: 'media_with_dynamic_changes', label: 'Media w/ dynamic' },
		{ key: 'media_with_static_changes', label: 'Media w/ static' },
		{ key: 'umbrella_reclassed', label: 'Anime reclassed' },
		{ key: 'probe_succeeded', label: 'Probes succeeded' },
		{ key: 'probe_failed', label: 'Probes failed' },
		{ key: 'probe_attached_anime_count', label: 'Anime w/ new attach' },
		{ key: 'orphaned_studios_removed', label: 'Orphaned studios removed' },
		{ key: 'step1_failed', label: 'Failed refresh' },
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
				{@const isStep1 = stat.key === 'step1_failed'}
				{@const notTracked = isStep1 && version < 4}
				{@const value = counters[stat.key] ?? 0}
				{@const warn = isStep1 && !notTracked && value > 0}
				{#snippet card(props: Record<string, unknown>)}
					<div
						{...props}
						class="rounded-md border p-3 {stat.tooltip ? 'cursor-help' : ''} {warn
							? 'border-amber-500/50 bg-amber-500/10'
							: 'border-border/60 bg-muted/10'}"
					>
						<dt class="text-[10px] uppercase tracking-wider text-muted-foreground">{stat.label}</dt>
						<dd
							class="text-xl font-semibold tabular-nums mt-1 {warn
								? 'text-amber-400'
								: 'text-card-foreground'}"
						>
							{notTracked ? '—' : value}
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
