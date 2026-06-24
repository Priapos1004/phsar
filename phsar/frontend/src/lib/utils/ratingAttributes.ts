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
