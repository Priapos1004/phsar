import { RATING_ATTRIBUTE_OPTIONS, getRatingAttr, isAttrRated } from '$lib/types/api';
import type { RatingScoreItem } from '$lib/types/api';

/** Context of the media being rated — drives exclusion + tiebreak. */
export interface NeighborContext {
	/** Anime of the media being rated; excluded so comparisons come from OTHER anime. */
	animeUuid?: string;
	genres?: string[];
	studios?: string[];
	ageRatingNumeric?: number | null;
}

const ATTR_KEYS = Object.keys(RATING_ATTRIBUTE_OPTIONS);

function attrCount(item: RatingScoreItem): number {
	return ATTR_KEYS.filter((k) => isAttrRated(getRatingAttr(item, k))).length;
}

function sharedCount(a: string[] | undefined, b: string[] | undefined): number {
	if (!a?.length || !b?.length) return 0;
	const set = new Set(a);
	return b.filter((x) => set.has(x)).length;
}

function ageDistance(item: RatingScoreItem, ctx: NeighborContext): number {
	if (ctx.ageRatingNumeric == null || item.age_rating_numeric == null) return Infinity;
	return Math.abs(item.age_rating_numeric - ctx.ageRatingNumeric);
}

// Lexicographic tiebreak when two ratings are equally close in score: more
// attributes rated (richest comparison) → more shared genres → shared studio →
// closer age rating → most recently rated (deterministic final).
function tiebreak(a: RatingScoreItem, b: RatingScoreItem, ctx: NeighborContext): number {
	const ac = attrCount(a);
	const bc = attrCount(b);
	if (ac !== bc) return bc - ac;

	const ag = sharedCount(a.genres, ctx.genres);
	const bg = sharedCount(b.genres, ctx.genres);
	if (ag !== bg) return bg - ag;

	const as = sharedCount(a.studios, ctx.studios) > 0;
	const bs = sharedCount(b.studios, ctx.studios) > 0;
	if (as !== bs) return as ? -1 : 1;

	const ad = ageDistance(a, ctx);
	const bd = ageDistance(b, ctx);
	if (ad !== bd) return ad - bd;

	return b.modified_at.localeCompare(a.modified_at);
}

function distanceCompare(
	a: RatingScoreItem,
	b: RatingScoreItem,
	score: number,
	ctx: NeighborContext,
	below: boolean,
): number {
	const da = below ? score - a.rating : a.rating - score;
	const db = below ? score - b.rating : b.rating - score;
	if (da !== db) return da - db;
	return tiebreak(a, b, ctx);
}

// <0 when `candidate` is the better representative of its anime than `current`.
function closerToScore(
	candidate: RatingScoreItem,
	current: RatingScoreItem,
	score: number,
	ctx: NeighborContext,
): number {
	const dc = Math.abs(candidate.rating - score);
	const dk = Math.abs(current.rating - score);
	if (dc !== dk) return dc - dk;
	return tiebreak(candidate, current, ctx);
}

// Ratings carry float noise (see formatScore), so "same score as the slider" is an
// epsilon band, not ===. Half the 0.01 smallest step → distinct 0.01-apart scores stay
// in separate (lower/higher) groups while float dust on an equal value reads as equal.
const EQ = 0.005;

/**
 * Pick up to 4 ratings from distinct OTHER anime that straddle `score`, to help the user
 * rate consistently: up to 2 at the SAME score (capped — 3+ identical scores is redundant),
 * then the leftover slots split as evenly as possible between strictly-lower and strictly-higher,
 * with the odd extra going to higher. So a dense library shows a lower row for sanity-checking
 * instead of only equals + one step up. Shapes: ≥2 equal → 2 eq / 1 lo / 1 hi; 1 equal →
 * 1 lo / 1 eq / 2 hi; 0 equal → 2 lo / 2 hi; a short side backfills the other (higher first).
 * Pure so it recomputes instantly as the score slider moves (no refetch) and is testable.
 */
export function selectRatingNeighbors(
	items: RatingScoreItem[],
	score: number,
	ctx: NeighborContext,
): RatingScoreItem[] {
	// 1. Pool = completed ratings from OTHER anime. Completed only because a
	//    dropped score is often deflated and an on-hold one provisional — mixing
	//    them in would bias the very scale this helper is meant to steady.
	const pool = items.filter(
		(i) => i.watch_status === 'completed' && i.anime_uuid !== ctx.animeUuid,
	);

	// 2. One rating per anime (its closest-to-score member), so the rows are
	//    distinct anime rather than several seasons of the same show.
	const byAnime = new Map<string, RatingScoreItem>();
	for (const item of pool) {
		const cur = byAnime.get(item.anime_uuid);
		if (!cur || closerToScore(item, cur, score, ctx) < 0) {
			byAnime.set(item.anime_uuid, item);
		}
	}
	const deduped = [...byAnime.values()];

	// 3. Partition into three disjoint groups around the score.
	const equalGroup = deduped
		.filter((i) => Math.abs(i.rating - score) < EQ)
		.sort((a, b) => tiebreak(a, b, ctx));
	const lowerGroup = deduped
		.filter((i) => i.rating < score - EQ)
		.sort((a, b) => distanceCompare(a, b, score, ctx, true));
	const higherGroup = deduped
		.filter((i) => i.rating > score + EQ)
		.sort((a, b) => distanceCompare(a, b, score, ctx, false));

	// 4. Fill 4 slots: equal capped at 2, the rest split evenly (odd extra → higher).
	const equal = equalGroup.slice(0, 2);
	const remaining = 4 - equal.length;
	const lowerTarget = Math.floor(remaining / 2);
	let lower = lowerGroup.slice(0, lowerTarget);
	let higher = higherGroup.slice(0, remaining - lowerTarget);
	// Two-way backfill: a short side hands its unused slots to the other (higher first).
	let need = 4 - equal.length - lower.length - higher.length;
	if (need > 0) {
		higher = higherGroup.slice(0, higher.length + need);
		need = 4 - equal.length - lower.length - higher.length;
	}
	if (need > 0) {
		lower = lowerGroup.slice(0, lower.length + need);
	}

	return [...equal, ...lower, ...higher];
}
