import type { UpdateSweepMediaChange } from '$lib/types/api';
import { isRatingField } from '$lib/utils/formatString';

// Ordering for the job-detail "Media changes" list: surface the most
// substantial edits first instead of the raw sweep-due order. A row is
// grouped by the highest-priority change category it contains, then sorted
// within that group by how much changed:
//
//   static  >  genre/studio  >  dynamic (excl. rating)  >  rating-only
//
// — non-rating groups sort by total changed-field count (desc); rating-only
// rows (pure vote churn) sort last and among themselves by search-relevance
// impact. JS sort is stable, so the backend sweep-due order is the final
// tiebreak.

function groupPriority(m: UpdateSweepMediaChange): number {
	if (m.static.length > 0) return 0;
	if (m.genre_drift || m.studio_drift) return 1;
	if (m.dynamic.some((d) => !isRatingField(d.field))) return 2;
	return 3; // rating-only
}

function totalChanges(m: UpdateSweepMediaChange): number {
	return (
		m.static.length +
		m.dynamic.length +
		(m.genre_drift ? 1 : 0) +
		(m.studio_drift ? 1 : 0)
	);
}

const toNum = (v: unknown): number => (typeof v === 'number' ? v : Number(v) || 0);
// Same weighting search ranking uses: score * log10(scored_by + 1).
const weighted = (score: number, scoredBy: number): number => score * Math.log10(scoredBy + 1);

// Rating-only sub-key `[subrank, magnitude]`, subrank ascending then
// magnitude descending in the comparator. Both fields moved → exact
// weighted-score delta (a new vote moves both, the common case); only score
// → |Δscore|; only scored_by → log-scale increase. A score move outranks
// vote-count churn, so score-only (1) sorts ahead of scored_by-only (2).
//
// Magnitudes are search-relevance, not raw delta: score enters the weighted
// product linearly so |Δscore| IS its contribution, but scored_by enters via
// log10 — so +500 on 5k (Δlog ≈ 0.04) outranks +1000 on 1M (Δlog ≈ 0.0004).
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
	group: number;
	total: number; // group < 3: changed-field count (more first)
	sub: number; // group 3: rating subrank (both > score > scored_by)
	mag: number; // group 3: magnitude (bigger first)
}

function sortKey(m: UpdateSweepMediaChange): SortKey {
	const group = groupPriority(m);
	if (group < 3) return { group, total: totalChanges(m), sub: 0, mag: 0 };
	const [sub, mag] = ratingKey(m);
	return { group, total: 0, sub, mag };
}

/**
 * Sort the job-detail media-change list most-substantial-first (see module
 * doc). Decorate-sort-undecorate: the per-row key is computed once instead of
 * on every comparison, since the list (up to ~1 row per changed media — can be
 * hundreds) is re-sorted in a Svelte `$derived` on every filter/search
 * keystroke. JS sort is stable, so the backend sweep-due order is the final
 * tiebreak.
 */
export function sortMediaChanges(rows: UpdateSweepMediaChange[]): UpdateSweepMediaChange[] {
	return rows
		.map((row) => ({ row, k: sortKey(row) }))
		.sort((a, b) => {
			if (a.k.group !== b.k.group) return a.k.group - b.k.group;
			if (a.k.group < 3) return b.k.total - a.k.total; // more changes first
			if (a.k.sub !== b.k.sub) return a.k.sub - b.k.sub; // both > score > scored_by
			return b.k.mag - a.k.mag; // bigger magnitude first
		})
		.map((d) => d.row);
}
