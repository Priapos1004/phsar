<script lang="ts">
	import { Badge } from '$lib/components/ui/badge';
	import { ExternalLink } from 'lucide-svelte';
	import { formatRelationType, resolveTitle } from '$lib/utils/formatString';
	import { buildDetailHref } from '$lib/utils/navigation';
	import { userSettings } from '$lib/stores/userSettings';
	import type { UpdateSweepMediaChange, UpdateSweepFieldChange, UpdateSweepM2MDrift } from '$lib/types/api';

	interface Props {
		change: UpdateSweepMediaChange;
	}
	let { change }: Props = $props();

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');
	let animeTitleDisplay = $derived(
		resolveTitle(change.anime_title, change.anime_name_eng, change.anime_name_jap, nameLanguage),
	);
	let mediaTitleDisplay = $derived(
		resolveTitle(change.media_title, change.media_name_eng, change.media_name_jap, nameLanguage),
	);

	// Numeric deltas get a signed +Δ / -Δ suffix so the admin spots
	// direction at a glance. Non-numeric fields render the values
	// verbatim (truncate long text in the cell, not here).
	function delta(old: unknown, next: unknown): string | null {
		if (typeof old !== 'number' || typeof next !== 'number') return null;
		const d = next - old;
		if (!Number.isFinite(d) || d === 0) return null;
		const sign = d > 0 ? '+' : '';
		const display = Number.isInteger(d) ? d.toString() : d.toFixed(2);
		return `${sign}${display}`;
	}

	function fmt(v: unknown): string {
		if (v === null || v === undefined) return '—';
		if (typeof v === 'string') return v;
		if (typeof v === 'number' || typeof v === 'boolean') return String(v);
		try {
			return JSON.stringify(v);
		} catch {
			return String(v);
		}
	}

	function rowFor(field: UpdateSweepFieldChange, tone: 'dynamic' | 'static'): {
		field: string;
		old: string;
		new: string;
		delta: string | null;
		tone: 'dynamic' | 'static';
	} {
		return {
			field: field.field,
			old: fmt(field.old),
			new: fmt(field.new),
			delta: delta(field.old, field.new),
			tone,
		};
	}

	let rows = $derived([
		...change.dynamic.map((f) => rowFor(f, 'dynamic')),
		...change.static.map((f) => rowFor(f, 'static')),
	]);

	const TONE_BORDER: Record<'dynamic' | 'static', string> = {
		// Warm accent for volatile/dynamic data (score, episodes…) —
		// signals "moves often, watch for trends".
		dynamic: 'border-l-amber-400/60',
		// Cool accent for static metadata (descriptions, titles…) —
		// signals "rare structural shift, MAL editor moved a string".
		static: 'border-l-sky-400/60',
	};
	const TONE_LABEL: Record<'dynamic' | 'static', string> = {
		dynamic: 'bg-amber-400/15 text-amber-400',
		static: 'bg-sky-400/15 text-sky-400',
	};

	// Map the backend's _emit_drift_report `kind` strings to a one-line
	// label. Keeps the structured drift rendering compact without
	// dropping the diagnostic signal.
	const DRIFT_KIND_LABEL: Record<UpdateSweepM2MDrift['kind'], string> = {
		additions_applied: 'Tags added (auto-applied)',
		additions_unknown: 'Tags added (unknown — review needed)',
		removal_or_replacement: 'Tags removed or replaced',
		any_change: 'Tags changed',
	};

	function driftSets(drift: UpdateSweepM2MDrift): { added: string[]; removed: string[] } {
		const oldSet = new Set(drift.old);
		const newSet = new Set(drift.new);
		return {
			added: drift.new.filter((t) => !oldSet.has(t)),
			removed: drift.old.filter((t) => !newSet.has(t)),
		};
	}
</script>

<div class="rounded-md border border-border/60 bg-muted/10 p-4 space-y-3">
	<div class="flex items-start justify-between gap-3 flex-wrap">
		<div class="space-y-1">
			<a
				href={buildDetailHref('anime', change.anime_uuid)}
				target="_blank"
				rel="noopener noreferrer"
				class="text-sm text-muted-foreground hover:text-card-foreground transition-colors inline-flex items-center gap-1"
			>
				{animeTitleDisplay}
				<ExternalLink class="size-3" />
			</a>
			<div class="flex items-center gap-2 flex-wrap">
				<a
					href={buildDetailHref('media', change.media_uuid)}
					target="_blank"
					rel="noopener noreferrer"
					class="text-base font-semibold text-card-foreground hover:underline inline-flex items-center gap-1"
				>
					{mediaTitleDisplay}
					<ExternalLink class="size-3" />
				</a>
				<Badge variant="secondary" class="text-[10px]">{formatRelationType(change.media_relation_type)}</Badge>
				<span class="text-xs text-muted-foreground">mal_id={change.media_mal_id}</span>
			</div>
		</div>
	</div>

	{#if rows.length > 0}
		<table class="w-full text-sm">
			<thead>
				<tr class="text-left text-[10px] uppercase tracking-wider text-muted-foreground">
					<th class="py-1.5 pr-3 font-medium w-32"></th>
					<th class="py-1.5 pr-3 font-medium">Field</th>
					<th class="py-1.5 pr-3 font-medium">Was</th>
					<th class="py-1.5 pr-3 font-medium">Now</th>
				</tr>
			</thead>
			<tbody>
				{#each rows as row (row.tone + ':' + row.field)}
					<tr class="border-t border-border/30 border-l-2 pl-2 align-top {TONE_BORDER[row.tone]}">
						<td class="py-1.5 pr-3">
							<Badge class="text-[10px] {TONE_LABEL[row.tone]}">{row.tone}</Badge>
						</td>
						<td class="py-1.5 pr-3 font-mono text-xs text-card-foreground">{row.field}</td>
						<td class="py-1.5 pr-3 text-card-foreground/80 max-w-xs truncate" title={row.old}>{row.old}</td>
						<td class="py-1.5 pr-3 text-card-foreground max-w-xs truncate" title={row.new}>
							{row.new}
							{#if row.delta}
								<span class="ml-1 text-xs {row.delta.startsWith('+') ? 'text-emerald-400' : 'text-destructive'}">({row.delta})</span>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}

	{#each [change.genre_drift, change.studio_drift].filter((d): d is UpdateSweepM2MDrift => d !== null) as drift (drift.field)}
		{@const sets = driftSets(drift)}
		<div class="rounded border border-border/40 bg-background/40 p-3 text-xs space-y-2">
			<div class="flex items-center gap-2">
				<span class="font-medium text-card-foreground capitalize">{drift.field}</span>
				<span class="text-muted-foreground">— {DRIFT_KIND_LABEL[drift.kind]}</span>
			</div>
			{#if sets.added.length > 0}
				<div class="flex items-start gap-2">
					<span class="text-emerald-400 font-medium tabular-nums">+{sets.added.length}</span>
					<div class="flex flex-wrap gap-1">
						{#each sets.added as tag (tag)}
							<Badge class="text-[10px] bg-emerald-500/15 text-emerald-400">{tag}</Badge>
						{/each}
					</div>
				</div>
			{/if}
			{#if sets.removed.length > 0}
				<div class="flex items-start gap-2">
					<span class="text-destructive font-medium tabular-nums">−{sets.removed.length}</span>
					<div class="flex flex-wrap gap-1">
						{#each sets.removed as tag (tag)}
							<Badge class="text-[10px] bg-destructive/15 text-destructive line-through">{tag}</Badge>
						{/each}
					</div>
				</div>
			{/if}
			{#if drift.unknown_tags.length > 0}
				<p class="text-amber-400">
					Unknown tags: {drift.unknown_tags.join(', ')} — seeder update needed before auto-apply.
				</p>
			{/if}
		</div>
	{/each}
</div>
