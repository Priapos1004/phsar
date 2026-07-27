/** Pure `AdminJobResponse` → display-string/number helpers for the admin Jobs Log.
 *
 * Extracted from `AdminJobsLogTab.svelte` so the version-dispatching logic is
 * unit-testable (the same reason `mediaChangeSort` and the `adminJobsFilter`
 * sanitizers live outside their components): `payloadSummary` alone branches
 * across 5 job kinds and 3 `update_sweep` schema eras, which is exactly the
 * shape that drifts silently when it can only be exercised by clicking. */

import { SEASON_SWEEP_KINDS, formatBytes } from '$lib/utils/formatString';
import type { AdminJobResponse } from '$lib/types/api';

/** JSONB lookups land as `unknown` per the JobResultSummary index signature;
 * this narrows safely so the formatters don't crash on legacy/malformed rows. */
const num = (v: unknown): number => (typeof v === 'number' ? v : 0);

/** The Detail cell: a one-line, kind- and version-aware précis of the job's
 * `result_summary`. Empty string when the kind carries nothing worth a line
 * (or the job hasn't finished). */
export function payloadSummary(row: AdminJobResponse): string {
	if (row.kind === 'user_scrape') {
		const q = typeof row.payload?.query === 'string' ? `"${row.payload.query}"` : '';
		if (row.status === 'succeeded' && row.result_summary) {
			const a = num(row.result_summary.anime_count);
			const m = num(row.result_summary.media_count);
			return `+${a} anime · +${m} media${q ? ` (${q})` : ''}`;
		}
		return q;
	}
	if (row.kind === 'backup' || row.kind === 'restore') {
		const s = row.result_summary;
		if (typeof s?.filename !== 'string') return '';
		// Only `backup` carries size_bytes — a restore summary holds just the two
		// filenames — so the size is appended when present rather than branched on kind.
		return typeof s.size_bytes === 'number'
			? `${s.filename} · ${formatBytes(s.size_bytes)}`
			: s.filename;
	}
	if (row.kind === 'update_sweep' && row.status === 'succeeded' && row.result_summary) {
		// v2 (post-v0.14.5) nests aggregate counts under `counters` and
		// carries per-media diffs the detail page renders. v1 rows pre-
		// date the rework — fall back to the flat shape.
		if (row.version >= 2) {
			const c = (row.result_summary.counters ?? {}) as Record<string, unknown>;
			// v5 (v0.14.8) went media-grained: anime_refreshed → media_refreshed
			// and the anime_with_dynamic rollup → media_with_dynamic. Earlier
			// versions keep their anime-grained keys so historical rows stay
			// accurate.
			const refreshed = row.version >= 5 ? num(c.media_refreshed) : num(c.anime_refreshed);
			const refreshedLabel = row.version >= 5 ? 'media refreshed' : 'touched';
			const dyn =
				row.version >= 5 ? num(c.media_with_dynamic_changes) : num(c.anime_with_dynamic_changes);
			const dynLabel = row.version >= 5 ? 'media w/ dynamic' : 'anime w/ dynamic';
			const staticMedia = num(c.media_with_static_changes);
			// Anime-changes + probe-attachments deliberately omitted from this
			// one-line summary — they overflowed the cell, and attachments
			// already surface via the blue row subline (v6); the full
			// breakdown lives on the detail page.
			const parts = [`${refreshed} ${refreshedLabel}`];
			if (dyn > 0) parts.push(`${dyn} ${dynLabel}`);
			if (staticMedia > 0) parts.push(`${staticMedia} media w/ static`);
			return parts.join(' · ');
		}
		const refreshed = num(row.result_summary.anime_refreshed);
		const changed = num(row.result_summary.anime_changed);
		const metadataChanged = num(row.result_summary.metadata_changed_media);
		const parts = [`refreshed ${refreshed} anime`, `${changed} changed`];
		if (metadataChanged > 0) parts.push(`${metadataChanged} media updated`);
		return parts.join(' · ');
	}
	// Both season sweeps come off one dispatcher and so write one summary shape — which
	// is what SEASON_SWEEP_KINDS is defined by, hence reading it rather than a kind
	// literal. The literal is what left every upcoming_sweep row with an empty cell.
	if (SEASON_SWEEP_KINDS.has(row.kind) && row.status === 'succeeded' && row.result_summary) {
		const s = row.result_summary;
		// season_name/_year are additive v0.15.3 keys (no version bump), so an older
		// row drops the prefix instead of rendering "undefined NaN".
		const season =
			typeof s.season_name === 'string' && typeof s.season_year === 'number'
				? `${s.season_name} ${s.season_year} · `
				: '';
		return `${season}${num(s.season_entries)} season entries · ${num(s.new_entries_enqueued)} new scrapes enqueued · ${num(s.dedup_skipped)} already known`;
	}
	return '';
}

/** v3+ sweeps expose a deduplicated list of MAL genre tags the seeder
 * doesn't know yet. Surfaced at the row level so the admin can spot which
 * sweeps need a seeder update without drilling in. */
export function unknownGenreTags(row: AdminJobResponse): string[] {
	const tags = row.result_summary?.unknown_genre_tags;
	return Array.isArray(tags) ? (tags as string[]) : [];
}

/** v6+ sweeps report how many media the relations probe attached. Surfaced
 * at the row level (blue, informational) so the admin spots which sweeps grew
 * the catalog without drilling in — sibling to the amber unknown-genre-tags
 * treatment. Media-grained, so pre-v6 rows (which only carried an
 * anime-grained count) stay un-tinted. */
export function probeAttachedMedia(row: AdminJobResponse): number {
	const counters = row.result_summary?.counters as Record<string, unknown> | undefined;
	return num(counters?.probe_attached_media_count);
}

/** v7+ sweeps report how many anime were deleted for flipping to Hentai — a
 * notable destructive event, so it outranks the amber/blue tints (rose).
 * Pre-v7 rows omit the counter → 0 → no tint. */
export function hentaiRemoved(row: AdminJobResponse): number {
	const counters = row.result_summary?.counters as Record<string, unknown> | undefined;
	return num(counters?.hentai_removed_count);
}

/** Mutually-exclusive row tint in priority order: hentai-removal (rose,
 * destructive) > unknown-genre-tags (amber, needs seeding) > probe-attach
 * (blue, informational). The row sublines are additive (each renders
 * independently); only the background tint is single-winner. */
export function rowTintClass(hentaiCount: number, unknownTagCount: number, probeMedia: number): string {
	if (hentaiCount > 0) return 'bg-rose-500/15 border-l-2 border-l-rose-400';
	if (unknownTagCount > 0) return 'bg-amber-500/15 border-l-2 border-l-amber-400';
	if (probeMedia > 0) return 'bg-blue-500/10 border-l-2 border-l-blue-400';
	return '';
}
