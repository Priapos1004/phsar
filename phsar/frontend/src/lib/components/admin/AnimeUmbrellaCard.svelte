<script lang="ts">
	import { Badge } from '$lib/components/ui/badge';
	import { ExternalLink } from 'lucide-svelte';
	import { resolveTitle } from '$lib/utils/formatString';
	import { buildDetailHref } from '$lib/utils/navigation';
	import { userSettings } from '$lib/stores/userSettings';
	import type { UpdateSweepUmbrellaChange } from '$lib/types/api';

	interface Props {
		change: UpdateSweepUmbrellaChange;
	}
	let { change }: Props = $props();

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');
	let animeTitleDisplay = $derived(
		resolveTitle(change.anime_title, change.anime_name_eng, change.anime_name_jap, nameLanguage),
	);

	function fmt(v: unknown): string {
		if (v === null || v === undefined) return '—';
		if (typeof v === 'string') return v;
		if (Array.isArray(v)) return v.join(', ') || '—';
		try {
			return JSON.stringify(v);
		} catch {
			return String(v);
		}
	}
</script>

<div class="rounded-md border border-border/60 bg-muted/10 p-4 space-y-3">
	<div class="flex items-center justify-between gap-3 flex-wrap">
		<!-- New tab (no back-to-job origin) — verify-and-return without losing
		     scroll in the long changes list. Opposite of the failure/attached
		     cards' same-tab "Back to job" flow. See MediaChangeCard / job page. -->
		<a
			href={buildDetailHref('anime', change.anime_uuid)}
			target="_blank"
			rel="noopener noreferrer"
			class="text-base font-semibold text-card-foreground hover:underline inline-flex items-center gap-1"
		>
			{animeTitleDisplay}
			<ExternalLink class="size-3.5" />
		</a>
		<div class="flex items-center gap-2 text-xs">
			{#if change.anchor_changed}
				<Badge class="text-[10px] bg-amber-400/15 text-amber-400">anchor moved</Badge>
				<span class="text-muted-foreground tabular-nums">
					mal_id {change.old_anchor_mal_id} → {change.new_anchor_mal_id}
				</span>
			{/if}
			{#if change.embedding_regenerated}
				<Badge class="text-[10px] bg-primary/15 text-primary">embedding regen</Badge>
			{/if}
		</div>
	</div>

	{#if change.fields.length > 0}
		<table class="w-full text-sm">
			<thead>
				<tr class="text-left text-[10px] uppercase tracking-wider text-muted-foreground">
					<th class="py-1.5 pr-3 font-medium">Field</th>
					<th class="py-1.5 pr-3 font-medium">Was</th>
					<th class="py-1.5 pr-3 font-medium">Now</th>
				</tr>
			</thead>
			<tbody>
				{#each change.fields as f (f.field)}
					<tr class="border-t border-border/30 align-top">
						<td class="py-1.5 pr-3 font-mono text-xs text-card-foreground">{f.field}</td>
						<td class="py-1.5 pr-3 text-card-foreground/80 max-w-sm truncate" title={fmt(f.old)}>{fmt(f.old)}</td>
						<td class="py-1.5 pr-3 text-card-foreground max-w-sm truncate" title={fmt(f.new)}>{fmt(f.new)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}

	{#if change.reclassified.length > 0}
		<div class="rounded border border-border/40 bg-background/40 p-2 text-xs space-y-1">
			<p class="font-medium text-card-foreground/80">Per-media relation reclassifications:</p>
			<ul class="space-y-0.5 text-muted-foreground">
				{#each change.reclassified as r (r.mal_id)}
					<li class="font-mono tabular-nums">mal_id={r.mal_id}: {r.old} → {r.new}</li>
				{/each}
			</ul>
		</div>
	{/if}
</div>
