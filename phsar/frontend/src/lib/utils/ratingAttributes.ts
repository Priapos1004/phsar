import { RATING_ATTRIBUTE_OPTIONS, getRatingAttr, isAttrRated } from '$lib/types/api';
import type { RatingOut, RatingScoreItem } from '$lib/types/api';

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
			value: config.options.find((o) => o.value === getRatingAttr(item, key))?.label
				?? String(getRatingAttr(item, key)),
		}));
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
