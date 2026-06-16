<script lang="ts">
	import * as Card from '$lib/components/ui/card';
	import type { UpdateSweepCounters } from '$lib/types/api';

	interface Props {
		counters: UpdateSweepCounters;
		merge_detect_failed?: boolean;
		cache_recompute_failed?: boolean;
	}
	let { counters, merge_detect_failed, cache_recompute_failed }: Props = $props();

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
	];
</script>

<Card.Root>
	<Card.Header>
		<h2 class="text-lg font-semibold text-card-foreground">Sweep counters</h2>
	</Card.Header>
	<Card.Content>
		<dl class="grid grid-cols-3 md:grid-cols-5 gap-4">
			{#each STATS as stat (stat.key)}
				<div class="rounded-md border border-border/60 bg-muted/10 p-3">
					<dt class="text-[10px] uppercase tracking-wider text-muted-foreground">{stat.label}</dt>
					<dd class="text-xl font-semibold text-card-foreground tabular-nums mt-1">
						{counters[stat.key] ?? 0}
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
