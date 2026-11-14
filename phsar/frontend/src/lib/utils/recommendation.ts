import type { RecommendationKind } from '$lib/types/api';
import { formatAirDate } from '$lib/utils/formatString';
import { priorityLabel, RESERVED_DEFAULT_TAG_COLOR } from '$lib/utils/watchlist';

/** A reason's sentence and the name it ends on, which the tooltip keeps on one line; `label`
 *  where the reason's own heading depends on what it names. */
export interface Because {
	text: string;
	name?: string;
	label?: string;
}

/** A name in a reason — an anime, a list, a region — set off as one. */
const quoted = (name: string) => `“${name}”`;

const named = (text: string, fallback: string) => (name: string | null): Because =>
	name ? { text, name: quoted(name) } : { text: fallback };

/** How long ago a fresh pick started or finished airing, by the tier
 *  `recommender_compute.fresh_detail` names, and the heading each tier reads under: past two
 *  years it is no longer fresh, and only the far end has a word of its own. */
const TIER: Record<string, { when: string; label: string }> = {
	month: { when: 'in the last month', label: 'Fresh' },
	year: { when: 'in the past year', label: 'Fresh' },
	'2y': { when: 'in the last two years', label: 'Fresh' },
	'5y': { when: 'two to five years ago', label: 'Era' },
	'10y': { when: 'five to ten years ago', label: 'Era' },
	old: { when: 'over ten years ago', label: 'Classic' },
};

/** The fresh details that are no tier: what is airing, and finales due this week. */
const NOW: Record<string, string> = {
	airing: "it's airing now",
	soon: 'its finale is days away',
	expected: 'its finale is estimated to be days away',
};

/** A fresh pick's sentence. One verb per signal: release age reads as when it started airing,
 *  the finale as when it finished, a movie included, so a franchise mixing both reads alike. A
 *  dated finale in the last month names its day, which needs no year. */
function fresh(name: string | null): Because {
	if (name?.startsWith('finished:')) return { text: `Because it finished airing on ${formatAirDate(name.slice(9), null)}` };
	if (name && NOW[name]) return { text: `Because ${NOW[name]}` };
	const [verb, tier] = name?.split('-') ?? [];
	if (!TIER[tier]) return { text: "Because it's as fresh as what you usually pick" };
	return { text: `Because it ${verb} airing ${TIER[tier].when}`, label: TIER[tier].label };
}

/**
 * How each recommendation reason marks a tile: its dot's colour, and the tooltip's one-word
 * label over the sentence saying why. `name` is what the reason names
 * (docs/features/recommender.md, "The row"). `lists` are the lists the anime is on, which the watchlist store knows and the ranking doesn't keep.
 *
 * Literal colours, as `COVERAGE_STYLE`'s are: a reason has to read the same under every
 * theme, and every one has to stay apart from the rest, which no theme's tokens promise.
 */
export const REASON_STYLE: Record<
	RecommendationKind,
	{ colour: string; label: string; because: (name: string | null, lists: string[]) => Because }
> = {
	continue: { colour: '#22c55e', label: 'Continuation', because: () => ({ text: 'Pick up where you left off' }) },
	watchlist: {
		colour: RESERVED_DEFAULT_TAG_COLOR,
		label: 'Watchlist',
		because: (name, lists) => {
			const priority = name ? `${priorityLabel(Number(name.slice(1))).toLowerCase()} priority` : 'listed';
			return lists.length
				? { text: `Because it's ${priority} on `, name: lists.map(quoted).join(' & ') }
				: { text: `Because it's ${priority} on your watchlist` };
		},
	},
	// Fresh, Era or Classic: one colour for every reason about when it aired.
	fresh: { colour: '#06b6d4', label: 'Fresh', because: fresh },
	recent: {
		colour: '#a855f7',
		label: 'Recent',
		because: named('Because you recently watched ', 'Because of what you watched recently'),
	},
	favourite: { colour: '#ec4899', label: 'Favourite', because: named('Because you loved ', 'Because of your favourites') },
	popular: { colour: '#eab308', label: 'Popular', because: () => ({ text: 'Because many people rated it on MAL' }) },
	explore: {
		colour: '#3b82f6',
		label: 'Explore',
		// The least-covered regions feed the slots, untouched ones included, so what is left, not
		// what was seen.
		because: named("Because there's a lot left to discover in ", "Because there's a lot left to discover in its region"),
	},
};
