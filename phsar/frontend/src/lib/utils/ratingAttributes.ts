import { RATING_ATTRIBUTE_OPTIONS, getRatingAttr, isAttrRated } from '$lib/types/api';
import type { AnimeMediaItem, RatingOut, RatingScoreItem } from '$lib/types/api';
import { MAIN_RELATIONS } from '$lib/utils/relations';

/**
 * Build the label/value badges for a rating's filled attributes (the filter+map
 * shape over the 11 attributes, skipping unset + the `not_applicable` sentinel).
 * Shared by the RatingCard filled-attribute display and the RatingNeighbors rows
 * so the two can't drift. `key` is included so the neighbor color-coding can map a
 * badge back to its attribute (quality vs categorical comparison).
 */
export function attributeBadges(item: RatingOut | RatingScoreItem): { key: string; label: string; value: string }[] {
	return Object.entries(RATING_ATTRIBUTE_OPTIONS)
		.filter(([key]) => isAttrRated(getRatingAttr(item, key)))
		.map(([key, config]) => ({
			key,
			label: config.label,
			value: optionLabel(key, getRatingAttr(item, key)!),
		}));
}

const ATTR_KEYS = Object.keys(RATING_ATTRIBUTE_OPTIONS);

/** True when some rating carries a real attribute value — the auto-set `not_applicable`
 * doesn't count, so an empty attribute section can never render. */
export function hasAnyAttribute(ratings: (RatingOut | RatingScoreItem)[]): boolean {
	return ratings.some((r) => ATTR_KEYS.some((k) => isAttrRated(getRatingAttr(r, k))));
}

// The 5 attributes with a clear better/worse order — compared by ordinal position
// (higher/lower) in the neighbor color-coding. The other 6 are categorical (differ/match).
export const QUALITY_ATTR_KEYS = new Set([
	'animation_quality', 'story_quality', 'dialogue_quality', 'character_depth', 'ending_quality',
]);

export type AttributeComparison = 'higher' | 'lower' | 'differs' | 'neutral' | 'match';

/**
 * Compare a neighbor's attribute value against the user's current selection, for the
 * "How you rated similar titles" color-coding. `neutral` (grey) is "you haven't set this";
 * `match` (warm cream) is "the neighbor agrees with your pick" — kept distinct so a real
 * agreement reads differently from an unset attribute. Quality attrs (QUALITY_ATTR_KEYS)
 * compare by ordinal position → higher/lower; the rest are categorical → differs.
 * `neighborValue` is always a real rated value (the caller only colors badges
 * attributeBadges emitted, which skip unset + not_applicable).
 */
export function compareAttribute(
	key: string,
	neighborValue: string,
	currentValue: string | null,
): AttributeComparison {
	if (!isAttrRated(currentValue)) return 'neutral'; // you haven't set this
	if (neighborValue === currentValue) return 'match'; // neighbor matches your pick
	if (!QUALITY_ATTR_KEYS.has(key)) return 'differs';
	const opts = RATING_ATTRIBUTE_OPTIONS[key]?.options ?? [];
	const ni = opts.findIndex((o) => o.value === neighborValue);
	const ci = opts.findIndex((o) => o.value === currentValue);
	if (ni < 0 || ci < 0) return 'differs'; // unknown value — fall back to a plain "differs"
	return ni > ci ? 'higher' : 'lower';
}

// ---------------------------------------------------------------------------
// Anime-grain aggregation for the descriptive pills
// ---------------------------------------------------------------------------
//
// Each pill answers a different question, so no single shared vote can be right for all
// of them. Each rule below states the question it answers; the shape of the answer
// follows from that.
//
// The aggregate-only labels ("Slow-ish", "Mixed", "Distinctive", …) live here and must
// NOT join RATING_ATTRIBUTE_OPTIONS: that map is the rating form's selectable options
// and supplies the Spearman rank order in ratingStats.ts, so a value no user can pick
// does not belong in it.

/** Render order for the pills; their geometry is keyed by attribute in `PILL_STYLES`. */
export const BADGE_KEYS = [
	'pace',
	'has_3d_animation',
	'watched_format',
	'fan_service',
	'ending_type',
	'originality',
] as const;

type AnyRating = RatingOut | RatingScoreItem;

// A quarter of the pool is substantial enough to name rather than average away — every
// "is the minority big enough to name" cutoff below. Compared as integers so no share
// ever lands on a floating-point boundary, the same reason originality's 30% cutoff is
// written `* 10 >= n * 3`.
const isSubstantial = (count: number, n: number) => count * 4 >= n;

// Read out of the shared map rather than retyped: the ordinal positions ARE the enum
// order, so a copy that drifts would mis-band the pills while every other reader of the
// map — which uses it as a set of options rather than as an order — stayed right.
// Pinned in the test.
const ORIGINALITY_CORNERS = RATING_ATTRIBUTE_OPTIONS.originality.options.map((o) => o.value);

// Which corners of the originality triangle are present -> what the pill says. A pool
// occupying a single corner falls through to the enum's own label instead.
const ORIGINALITY_EDGES: Record<string, string> = {
	'conventional+unique': 'Distinctive',
	'unique+experimental': 'Unconventional', // the edge opposite the conventional vertex
	'conventional+experimental': 'Exploratory',
	'conventional+unique+experimental': 'Mixed',
};

export function optionLabel(key: string, value: string): string {
	return RATING_ATTRIBUTE_OPTIONS[key]?.options.find((o) => o.value === value)?.label ?? value;
}

/** Counts per value for one attribute. Only rated values count, so `n` is per-attribute:
 *  a medium that never answered this question must not dilute the ones that did.
 *  Shared with `AttributeDetailBars`, so the pills and the distribution bars cannot
 *  disagree about what counts as an answer. */
export function tally(pool: AnyRating[], key: string): { counts: Map<string, number>; n: number } {
	const counts = new Map<string, number>();
	let n = 0;
	for (const r of pool) {
		const v = getRatingAttr(r, key);
		if (isAttrRated(v)) {
			counts.set(v, (counts.get(v) ?? 0) + 1);
			n++;
		}
	}
	return { counts, n };
}

/**
 * "What did I watch this in?" — the one pill read over two pools.
 *
 * A rating whose own value is `both` counts toward each tally, so it needs no special
 * case. Within a pool, Both means the smaller side is substantial; otherwise the larger
 * side wins. Returns null when nothing in the pool answered.
 */
function formatInPool(pool: AnyRating[]): string | null {
	const { counts, n } = tally(pool, 'watched_format');
	if (!n) return null;
	const both = counts.get('both') ?? 0;
	const sub = (counts.get('sub') ?? 0) + both;
	const dub = (counts.get('dub') ?? 0) + both;
	if (isSubstantial(Math.min(sub, dub), n)) return 'both';
	return sub > dub ? 'sub' : 'dub';
}

/**
 * "How does it move?" — a sustained quality, so the mean is honest, except when the
 * pace genuinely swings: slow and fast both substantial averages to dead centre and
 * would report "Normal" when nothing about the watch was normal.
 *
 * The bands are thirds of the gap between anchors, in integer form (`3*sum` vs `n`), so
 * 1 slow + 3 normal lands on Normal rather than a boundary.
 */
function paceValue(pool: AnyRating[]): string | null {
	const { counts, n } = tally(pool, 'pace');
	if (!n) return null;
	const slow = counts.get('slow') ?? 0;
	const fast = counts.get('fast') ?? 0;
	if (isSubstantial(slow, n) && isSubstantial(fast, n)) return 'Mixed';
	const sum = (counts.get('normal') ?? 0) + 2 * fast;
	if (3 * sum <= n) return optionLabel('pace', 'slow');
	if (3 * sum < 2 * n) return 'Slow-ish';
	if (3 * sum <= 4 * n) return optionLabel('pace', 'normal');
	if (3 * sum < 5 * n) return 'Fast-ish';
	return optionLabel('pace', 'fast');
}

/**
 * "How much of it will I run into?" — 3D animation and fan service share a scale and a
 * rule. The mean, rounded, except for the same swing case pace has: entries with none
 * alongside entries with a real amount is a split, not a middling average.
 *
 * `rare` is deliberately not on the high side — "some none, some rare" is not a split
 * worth flagging, it is just "a little".
 *
 * The floor is the point: "None" claims an absence, so it may only be said when the
 * whole pool said none.
 */
function amountValue(pool: AnyRating[], key: string): string | null {
	const { counts, n } = tally(pool, key);
	if (!n) return null;
	const none = counts.get('none') ?? 0;
	const high = (counts.get('medium') ?? 0) + (counts.get('heavy') ?? 0);
	if (isSubstantial(none, n) && isSubstantial(high, n)) return 'Mixed';
	const sum = (counts.get('rare') ?? 0) + 2 * (counts.get('medium') ?? 0) + 3 * (counts.get('heavy') ?? 0);
	let index = Math.round(sum / n);
	if (index === 0 && none < n) index = 1; // something is present — never claim none
	// The rounded mean IS an index into the enum's own order, so read the label straight
	// out rather than keeping a second copy of that order in this module.
	return RATING_ATTRIBUTE_OPTIONS[key].options[index].label;
}

/**
 * "How far from the norm?" — three corners of a triangle, not a line. A franchise with
 * conventional AND experimental entries is bimodal, and averaging it to "unique" is a
 * lie, so the answer is which corners the pool occupies.
 *
 * The cutoff sits below `1 / corners`, so shares summing to 1 always leave at least one
 * corner present and this never falls through — re-derive it if a corner is ever added,
 * or `present` empties and `present[0]` goes undefined. Then the floor, the same shape
 * as amountValue's: a corner may only speak alone with an outright majority — otherwise
 * the runner-up joins it, and both runners-up when they tie.
 */
function originalityValue(pool: AnyRating[]): string | null {
	const { counts, n } = tally(pool, 'originality');
	if (!n) return null;
	const c = ORIGINALITY_CORNERS.map((v) => counts.get(v) ?? 0);
	let present = ORIGINALITY_CORNERS.filter((_, i) => c[i] * 10 >= n * 3);
	if (present.length === 1 && Math.max(...c) * 2 <= n) {
		// `>= runnerUp` picks up the third corner too when it ties the second, which is
		// what makes a 3-2-2 split read Mixed rather than an arbitrary edge.
		const runnerUp = [...c].sort((a, b) => b - a)[1];
		present = ORIGINALITY_CORNERS.filter((_, i) => c[i] >= runnerUp);
	}
	return ORIGINALITY_EDGES[present.join('+')] ?? optionLabel('originality', present[0]);
}

/**
 * Split the ratings into the two pools the rules read.
 *
 * `main` is the story spine (MAIN_RELATIONS), in `media` order — the backend hands
 * `anime.media` back sorted by `chronological_media_key`, which is what lets ending_type
 * just take the last one. It falls back to every rating when no main entry is rated, so
 * a side-stories-only library still gets pills.
 *
 * Without `media` (the media-grain share card, which has one rating and no anime around
 * it) both pools are simply the ratings given.
 */
function buildPools(ratings: AnyRating[], media?: AnimeMediaItem[]) {
	if (!media?.length) return { main: ratings, all: ratings };
	// Walking `media` forwards inherits its order instead of re-deriving one by sorting.
	const byUuid = new Map(ratings.map((r) => [r.media_uuid, r]));
	const all: AnyRating[] = [];
	const main: AnyRating[] = [];
	for (const m of media) {
		const rating = byUuid.get(m.uuid);
		if (!rating) continue;
		all.push(rating);
		if (MAIN_RELATIONS.has(m.relation_type)) main.push(rating);
	}
	return { main: main.length ? main : all, all };
}

/**
 * One pill per `BADGE_KEY`, in that order. `value` is null when nothing in the pool
 * answered that question — the caller renders those as "--".
 *
 * Pure, so every rule above is asserted directly in `tests/attribute-aggregate.test.ts`.
 */
export function aggregateBadges(
	ratings: AnyRating[],
	media?: AnimeMediaItem[],
): { key: string; label: string; value: string | null }[] {
	const { main, all } = buildPools(ratings, media);

	// The main pool holds a veto on format: the all-media pool alone drowns the main story
	// in a franchise shaped like One Piece (one main entry against fifty specials), while
	// the main pool alone cannot see a side library watched the other way round. The two
	// are the same array when nothing distinguishes them, so only scan once.
	const mainFormat = formatInPool(main);
	const allFormat = main === all ? mainFormat : formatInPool(all);
	const format =
		mainFormat && allFormat && mainFormat !== allFormat ? 'both' : (mainFormat ?? allFormat);

	// "Where does it leave you?" — the ending you would actually reach, not the one that
	// recurs. `not_applicable` is excluded upstream, so an unfinished latest season falls
	// through to the one before it for free.
	const lastEnded = main.findLast((r) => isAttrRated(getRatingAttr(r, 'ending_type')));
	const endingType = lastEnded ? getRatingAttr(lastEnded, 'ending_type') : null;

	const values: Record<(typeof BADGE_KEYS)[number], string | null> = {
		pace: paceValue(main),
		has_3d_animation: amountValue(main, 'has_3d_animation'),
		watched_format: format && optionLabel('watched_format', format),
		fan_service: amountValue(main, 'fan_service'),
		ending_type: endingType && optionLabel('ending_type', endingType),
		originality: originalityValue(main),
	};

	return BADGE_KEYS.map((key) => ({
		key,
		label: RATING_ATTRIBUTE_OPTIONS[key].label,
		value: values[key],
	}));
}
