import type { NameLanguage, UpdateSweepMediaChange } from '$lib/types/api';
import { isRatingField, resolveTitle } from '$lib/utils/formatString';

// Ordering for the job-detail "Media changes" list: surface the most
// substantial edits first instead of the raw sweep-due order. A medal
// table, ranked by `CHANGE_TONE_ORDER` below.

/**
 * The rank order, and the single source of truth for it. Each row is
 * scored as one count per change category and the counts are compared in
 * this sequence, so the first to differ decides and one gold beats any
 * number of bronze — a single `airing_status` flip outranks five static
 * metadata edits. `MediaChangeCard` keys its row order off `TONE_RANK`.
 *
 * `rating` is last and is the one rank with no medal of its own —
 * `ratingKey` already orders both-changed > score-only > scored_by-only >
 * neither, which is strictly finer than a count, so a rating medal could
 * never change an outcome. `media-change-sort.test.ts` walks this array to
 * pin the comparator against it, `rating` included.
 */
export const CHANGE_TONE_ORDER = ['dynamic', 'genre', 'studio', 'static', 'rating'] as const;
export type ChangeTone = (typeof CHANGE_TONE_ORDER)[number];
export const TONE_RANK = Object.fromEntries(
	CHANGE_TONE_ORDER.map((tone, i) => [tone, i]),
) as Record<ChangeTone, number>;

/**
 * The media title as the card prints it in its heading — which is what
 * makes the A→Z tiebreak read as alphabetical down the page, so the sort
 * and the card must resolve it identically.
 *
 * Media's own name fields only. Falling back to the parent anime's
 * alt-title (e.g. for sub-episode rows MAL didn't give a `name_eng`)
 * loses season-specific suffix information — "Dr. Stone: New World" would
 * render as just "Dr. Stone". When `media.name_eng` is null, `resolveTitle`
 * falls back to media's romaji `title`, which always carries the suffix.
 */
export function mediaChangeTitle(
	m: UpdateSweepMediaChange,
	nameLanguage: NameLanguage,
): string {
	return resolveTitle(m.media_title, m.media_name_eng, m.media_name_jap, nameLanguage);
}

const toNum = (v: unknown): number => (typeof v === 'number' ? v : Number(v) || 0);
// Same weighting search ranking uses: score * log10(scored_by + 1).
const weighted = (score: number, scoredBy: number): number => score * Math.log10(scoredBy + 1);

// Rating sub-key `[subrank, magnitude]`, subrank ascending then magnitude
// descending in the comparator. Both fields moved → exact weighted-score
// delta (a new vote moves both, the common case); only score → |Δscore|;
// only scored_by → log-scale increase. A score move outranks vote-count
// churn, so score-only (1) sorts ahead of scored_by-only (2).
//
// Magnitudes are search-relevance, not raw delta: score enters the weighted
// product linearly so |Δscore| IS its contribution, but scored_by enters via
// log10 — so +500 on 5k (Δlog ≈ 0.04) outranks +1000 on 1M (Δlog ≈ 0.0004).
// They are therefore in three different units and comparable only within a
// subrank, which is why the comparator takes subrank first.
function ratingKey(m: UpdateSweepMediaChange): [number, number] {
	const score = m.dynamic.find((d) => d.field === 'score');
	const scoredBy = m.dynamic.find((d) => d.field === 'scored_by');
	if (score && scoredBy) {
		const diff = Math.abs(
			weighted(toNum(score.new), toNum(scoredBy.new)) -
				weighted(toNum(score.old), toNum(scoredBy.old)),
		);
		return [0, diff];
	}
	if (score) return [1, Math.abs(toNum(score.new) - toNum(score.old))];
	if (scoredBy) {
		const logIncrease = Math.abs(
			Math.log10(toNum(scoredBy.new) + 1) - Math.log10(toNum(scoredBy.old) + 1),
		);
		return [2, logIncrease];
	}
	return [3, 0];
}

interface SortKey {
	// One slot per medal-bearing entry of CHANGE_TONE_ORDER, in that order,
	// each compared descending. Fixed-length so a slot cannot go missing.
	medals: [dynamic: number, genre: number, studio: number, staticFields: number];
	sub: number; // rating subrank (both > score > scored_by)
	mag: number; // rating magnitude (bigger first)
	title: string; // displayed media title, for the A→Z tiebreak
}

function sortKey(m: UpdateSweepMediaChange, nameLanguage: NameLanguage): SortKey {
	const [sub, mag] = ratingKey(m);
	return {
		medals: [
			m.dynamic.filter((d) => !isRatingField(d.field)).length,
			m.genre_drift ? 1 : 0,
			m.studio_drift ? 1 : 0,
			m.static.length,
		],
		sub,
		mag,
		title: mediaChangeTitle(m, nameLanguage),
	};
}

/**
 * Sort the job-detail media-change list most-substantial-first (see module
 * doc). Decorate-sort-undecorate: the per-row key is computed once instead of
 * on every comparison, since the list (up to ~1 row per changed media — can be
 * hundreds) is re-sorted in a Svelte `$derived` on every filter/search
 * keystroke. That is also why the title resolves in the decorate step rather
 * than in the comparator. JS sort is stable, so the backend sweep-due order is
 * the final tiebreak.
 */
export function sortMediaChanges(
	rows: UpdateSweepMediaChange[],
	nameLanguage: NameLanguage,
): UpdateSweepMediaChange[] {
	return rows
		.map((row) => ({ row, k: sortKey(row, nameLanguage) }))
		.sort((a, b) => {
			for (let i = 0; i < a.k.medals.length; i++) {
				if (a.k.medals[i] !== b.k.medals[i]) return b.k.medals[i] - a.k.medals[i];
			}
			if (a.k.sub !== b.k.sub) return a.k.sub - b.k.sub; // both > score > scored_by
			if (a.k.mag !== b.k.mag) return b.k.mag - a.k.mag; // bigger magnitude first
			return a.k.title.localeCompare(b.k.title);
		})
		.map((d) => d.row);
}
