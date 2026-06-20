<script lang="ts">
	import { Badge } from '$lib/components/ui/badge';
	import { ExternalLink } from 'lucide-svelte';
	import { formatRelationType, isRatingField, resolveTitle } from '$lib/utils/formatString';
	import { buildDetailHref } from '$lib/utils/navigation';
	import { userSettings } from '$lib/stores/userSettings';
	import type { UpdateSweepMediaChange, UpdateSweepFieldChange, UpdateSweepM2MDrift } from '$lib/types/api';

	interface Props {
		change: UpdateSweepMediaChange;
	}
	let { change }: Props = $props();

	let nameLanguage = $derived($userSettings?.name_language ?? 'english');
	// Media's own name fields only — falling back to the parent anime's
	// alt-title (e.g. for sub-episode rows MAL didn't give a name_eng)
	// loses season-specific suffix information ("Dr. Stone: New World"
	// would render as just "Dr. Stone"). When media.name_eng is null,
	// resolveTitle falls back to media's romaji `title`, which always
	// carries the season suffix.
	let mediaTitleDisplay = $derived(
		resolveTitle(
			change.media_title,
			change.media_name_eng,
			change.media_name_jap,
			nameLanguage,
		),
	);

	// Five tones for visual differentiation among field categories.
	// `rating` is split out from the rest of the dynamic bucket because
	// score / scored_by churn hourly on popular anime — keeping them in
	// the same amber band as episodes/airing_status would drown the
	// genuine signal under vote-count noise.
	type Tone = 'rating' | 'dynamic' | 'static' | 'genre' | 'studio';

	const TONE_BORDER: Record<Tone, string> = {
		rating: 'border-l-zinc-500/60',
		dynamic: 'border-l-amber-400/60',
		static: 'border-l-sky-400/60',
		genre: 'border-l-fuchsia-400/60',
		studio: 'border-l-indigo-400/60',
	};

	function dynamicTone(field: string): Tone {
		return isRatingField(field) ? 'rating' : 'dynamic';
	}

	function fmtScalar(v: unknown): string {
		if (v === null || v === undefined) return '—';
		if (typeof v === 'string') return v;
		if (typeof v === 'number' || typeof v === 'boolean') return String(v);
		try {
			return JSON.stringify(v);
		} catch {
			return String(v);
		}
	}

	function delta(old: unknown, next: unknown): string | null {
		if (typeof old !== 'number' || typeof next !== 'number') return null;
		const d = next - old;
		if (!Number.isFinite(d) || d === 0) return null;
		const sign = d > 0 ? '+' : '';
		const display = Number.isInteger(d) ? d.toString() : d.toFixed(2);
		return `${sign}${display}`;
	}

	type ScalarRow = {
		kind: 'scalar';
		tone: Tone;
		field: string;
		old: string;
		new: string;
		delta: string | null;
	};
	type TagsetRow = {
		kind: 'tagset';
		tone: 'genre' | 'studio';
		field: string;
		old_tags: string[];
		new_tags: string[];
		added: Set<string>;
		removed: Set<string>;
		unknown_tags: string[];
		drift_kind: UpdateSweepM2MDrift['kind'];
	};
	type DiffRow = ScalarRow | TagsetRow;

	function scalarRow(field: UpdateSweepFieldChange, tone: Tone): ScalarRow {
		return {
			kind: 'scalar',
			tone,
			field: field.field,
			old: fmtScalar(field.old),
			new: fmtScalar(field.new),
			delta: delta(field.old, field.new),
		};
	}

	function tagsetRow(drift: UpdateSweepM2MDrift): TagsetRow {
		const oldSet = new Set(drift.old);
		const newSet = new Set(drift.new);
		return {
			kind: 'tagset',
			tone: drift.field === 'genres' ? 'genre' : 'studio',
			field: drift.field,
			old_tags: drift.old,
			new_tags: drift.new,
			added: new Set(drift.new.filter((t) => !oldSet.has(t))),
			removed: new Set(drift.old.filter((t) => !newSet.has(t))),
			unknown_tags: drift.unknown_tags,
			drift_kind: drift.kind,
		};
	}

	// Drift kinds annotate what the dispatcher did with the change. The
	// table is keyed on every value the backend has ever emitted so
	// historical rows render with the right semantics:
	// - v3+ (post-v0.14.5): `applied` (clean) or `applied_with_unknowns`
	//   (known parts landed; unknown genre tags reported pending seeder).
	// - v2 (pre-v0.14.5): the previous conservative kinds meant the
	//   change was logged but NOT applied — the media page would still
	//   show the pre-sweep tags. Kept here so old job rows render
	//   accurate "Not auto-applied" context.
	const NOT_APPLIED_REASON: Record<UpdateSweepM2MDrift['kind'], string | null> = {
		applied: null,
		applied_with_unknowns: 'Known additions applied. Unknown tags skipped pending seeder update.',
		additions_applied: null,
		additions_unknown: 'Not auto-applied — unknown tag, seeder review needed.',
		removal_or_replacement: 'Not auto-applied — removals require human review.',
		any_change: 'Not auto-applied — studio drift never auto-applies.',
	};

	// Sort tone groups so the noteworthy buckets (dynamic / static /
	// genre / studio) surface first; the noisy `rating` bucket lands at
	// the bottom of every card so the eye doesn't get drawn there first.
	const TONE_ORDER: Record<Tone, number> = {
		dynamic: 0,
		static: 1,
		genre: 2,
		studio: 3,
		rating: 4,
	};

	let rows = $derived.by<DiffRow[]>(() => {
		const out: DiffRow[] = [];
		for (const f of change.dynamic) out.push(scalarRow(f, dynamicTone(f.field)));
		for (const f of change.static) out.push(scalarRow(f, 'static'));
		if (change.genre_drift) out.push(tagsetRow(change.genre_drift));
		if (change.studio_drift) out.push(tagsetRow(change.studio_drift));
		return out.sort((a, b) => TONE_ORDER[a.tone] - TONE_ORDER[b.tone]);
	});
</script>

<div class="rounded-md border border-border/60 bg-muted/10 p-4 space-y-3">
	<div class="flex items-center gap-2 flex-wrap">
		<!-- Design decision: Media/Anime *change* cards open in a NEW TAB (no
		     back-to-job origin). The media-changes list runs 300+ rows, so an
		     admin verifying one row wants to peek and return without losing
		     their scroll position in the original tab. The failure / attached
		     cards take the opposite tack — same-tab with a "Back to job" button
		     (short lists, no scroll to preserve). See the job-detail page. -->
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

	{#if rows.length > 0}
		<table class="w-full text-sm table-fixed">
			<colgroup>
				<col class="w-40" />
				<col />
				<col />
			</colgroup>
			<thead>
				<tr class="text-left text-[10px] uppercase tracking-wider text-muted-foreground">
					<th class="py-1.5 pl-3 pr-3 font-medium">Field</th>
					<th class="py-1.5 pr-3 font-medium">Was</th>
					<th class="py-1.5 pr-3 font-medium">Now</th>
				</tr>
			</thead>
			<tbody>
				{#each rows as row (row.tone + ':' + row.field)}
					<tr class="border-t border-border/30 border-l-2 align-top {TONE_BORDER[row.tone]}">
						<td class="py-1.5 pl-3 pr-3 font-mono text-xs text-card-foreground">{row.field}</td>
						{#if row.kind === 'scalar'}
							<td class="py-1.5 pr-3 text-card-foreground/80 truncate" title={row.old}>{row.old}</td>
							<td class="py-1.5 pr-3 text-card-foreground tabular-nums truncate" title={row.new}>
								{row.new}
								{#if row.delta}
									<span class="ml-1 text-xs {row.delta.startsWith('+') ? 'text-emerald-400' : 'text-destructive'}">({row.delta})</span>
								{/if}
							</td>
						{:else}
							{@const notAppliedReason = NOT_APPLIED_REASON[row.drift_kind]}
							<td class="py-1.5 pr-3">
								<div class="flex flex-wrap gap-1">
									{#each row.old_tags as tag (tag)}
										<Badge variant={row.removed.has(tag) ? 'destructive' : 'secondary'} class="text-[10px]">{tag}</Badge>
									{/each}
									{#if row.old_tags.length === 0}
										<span class="text-xs text-muted-foreground">—</span>
									{/if}
								</div>
							</td>
							<td class="py-1.5 pr-3">
								<div class="flex flex-wrap gap-1">
									{#each row.new_tags as tag (tag)}
										<Badge variant="secondary" class="text-[10px] {row.added.has(tag) ? 'bg-emerald-500/15 text-emerald-400' : ''}">{tag}</Badge>
									{/each}
									{#if row.new_tags.length === 0}
										<span class="text-xs text-muted-foreground">—</span>
									{/if}
								</div>
								{#if notAppliedReason}
									<p class="mt-1 text-xs text-amber-400">⚠ {notAppliedReason}</p>
								{/if}
								{#if row.unknown_tags.length > 0}
									<p class="mt-1 text-xs text-amber-400">Unknown: {row.unknown_tags.join(', ')}</p>
								{/if}
							</td>
						{/if}
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>
