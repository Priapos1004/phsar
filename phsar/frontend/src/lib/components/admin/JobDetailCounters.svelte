<script lang="ts">
	import * as Card from '$lib/components/ui/card';
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

	const STATS: { key: keyof UpdateSweepCounters; label: string }[] = [
		{ key: 'anime_refreshed', label: 'Anime touched' },
		{ key: 'anime_with_dynamic_changes', label: 'Anime w/ dynamic' },
		{ key: 'anime_with_static_changes', label: 'Anime w/ static' },
		{ key: 'media_with_dynamic_changes', label: 'Media w/ dynamic' },
		{ key: 'media_with_static_changes', label: 'Media w/ static' },
		{ key: 'umbrella_reclassed', label: 'Umbrellas reclassed' },
		{ key: 'probe_succeeded', label: 'Probes succeeded' },
		{ key: 'probe_failed', label: 'Probes failed' },
		{ key: 'probe_attached_anime_count', label: 'Anime w/ new attach' },
		{ key: 'orphaned_studios_removed', label: 'Orphaned studios removed' },
		{ key: 'step1_failed', label: 'Failed refresh' },
	];
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
				<div
					class="rounded-md border p-3 {warn
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
