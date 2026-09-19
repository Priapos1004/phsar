import { describe, it, expect } from 'vitest';
import { aggregateBadges, BADGE_KEYS } from '$lib/utils/ratingAttributes';
import { PER_CHOICE_KEYS } from '$lib/utils/ratingStats';
import { RATING_ATTRIBUTE_OPTIONS } from '$lib/types/api';
import type { AnimeMediaItem, RatingOut } from '$lib/types/api';

// Each fixture is a run of media carrying one attribute, so a test reads as the
// distribution it is asserting. `main`/`side` build a media list in the chronological
// order the backend hands back, and the matching ratings.
let seq = 0;
type Entry = { uuid: string; relation_type: string; attrs: Partial<RatingOut> };

const entries = (relation: string, attrs: Partial<RatingOut>, count = 1): Entry[] =>
	Array.from({ length: count }, () => ({
		uuid: `m${seq++}`,
		relation_type: relation,
		attrs,
	}));
const main = (attrs: Partial<RatingOut>, count = 1) => entries('main', attrs, count);
const side = (attrs: Partial<RatingOut>, count = 1) => entries('side_story', attrs, count);

/** The pill value for `key` over these entries, or null when nothing answered. */
function pill(key: (typeof BADGE_KEYS)[number], ...groups: Entry[][]): string | null {
	const flat = groups.flat();
	const media = flat.map((e) => ({ uuid: e.uuid, relation_type: e.relation_type }) as AnimeMediaItem);
	const ratings = flat.map((e) => ({ media_uuid: e.uuid, ...e.attrs }) as RatingOut);
	const index = BADGE_KEYS.indexOf(key);
	return aggregateBadges(ratings, media)[index].value;
}

describe('aggregateBadges — shape', () => {
	it('returns one pill per BADGE_KEY, in that order', () => {
		const pills = aggregateBadges([], []);
		expect(pills).toHaveLength(BADGE_KEYS.length);
		expect(pills.map((p) => p.label)).toEqual([
			'Pace',
			'3D Animation',
			'Watched Format',
			'Fan Service',
			'Ending Type',
			'Originality',
		]);
	});

	it('leaves every pill unset when nothing is rated', () => {
		expect(aggregateBadges([{} as RatingOut], []).every((p) => p.value === null)).toBe(true);
	});

	// A seventh descriptive attribute would otherwise get a stats chart and no pill, since
	// the two lists are maintained by hand in different modules. Order differs by design:
	// BADGE_KEYS drives the orbit's placement.
	it('covers exactly the descriptive attributes the stats page charts', () => {
		expect([...BADGE_KEYS].sort()).toEqual([...PER_CHOICE_KEYS].sort());
	});

	// The aggregation indexes into the enum's own order — the rounded mean IS the index
	// for 3D/fan service, and pace's band arithmetic assumes a 3-point scale. Every other
	// reader treats the map as a set of options, so reordering or extending an enum would
	// mis-band the pills alone. Pin the shapes the maths relies on.
	it.each([
		['pace', ['slow', 'normal', 'fast']],
		['has_3d_animation', ['none', 'rare', 'medium', 'heavy']],
		['fan_service', ['none', 'rare', 'medium', 'heavy']],
		['originality', ['conventional', 'unique', 'experimental']],
	])('%s keeps the value order the aggregation assumes', (key, expected) => {
		expect(RATING_ATTRIBUTE_OPTIONS[key].options.map((o) => o.value)).toEqual(expected);
	});
});

describe('pace — banded mean, with Mixed for a genuine swing', () => {
	it.each([
		['1 slow + 3 normal', main({ pace: 'slow' }), main({ pace: 'normal' }, 3), 'Normal'],
		['2 slow + 1 normal', main({ pace: 'slow' }, 2), main({ pace: 'normal' }), 'Slow'],
		['1 slow + 1 normal', main({ pace: 'slow' }), main({ pace: 'normal' }), 'Slow-ish'],
		['3 slow + 2 normal', main({ pace: 'slow' }, 3), main({ pace: 'normal' }, 2), 'Slow-ish'],
		['1 normal + 1 fast', main({ pace: 'normal' }), main({ pace: 'fast' }), 'Fast-ish'],
		['2 fast', main({ pace: 'fast' }, 2), [], 'Fast'],
	])('%s -> %s', (_label, a, b, expected) => {
		expect(pill('pace', a, b)).toBe(expected);
	});

	// The mean is dead centre in both, so only the share of each extreme separates them.
	it('calls 1 slow + 1 fast Mixed rather than averaging it to Normal', () => {
		expect(pill('pace', main({ pace: 'slow' }), main({ pace: 'fast' }))).toBe('Mixed');
	});

	it('calls 2 slow + 4 normal + 2 fast Mixed (each extreme is a quarter)', () => {
		expect(
			pill('pace', main({ pace: 'slow' }, 2), main({ pace: 'normal' }, 4), main({ pace: 'fast' }, 2)),
		).toBe('Mixed');
	});

	it('leaves 1 slow + 4 normal + 1 fast Normal — a lone outlier each way is not a swing', () => {
		expect(
			pill('pace', main({ pace: 'slow' }), main({ pace: 'normal' }, 4), main({ pace: 'fast' })),
		).toBe('Normal');
	});
});

describe.each(['has_3d_animation', 'fan_service'] as const)('%s — rounded mean + floor', (key) => {
	const at = (value: string, n = 1) => main({ [key]: value }, n);

	it.each([
		['4 rare + 2 heavy', [at('rare', 4), at('heavy', 2)], 'Medium'],
		['6 rare', [at('rare', 6)], 'Rare'],
		['6 heavy', [at('heavy', 6)], 'Heavy'],
		['6 none', [at('none', 6)], 'None'],
	])('%s -> %s', (_label, groups, expected) => {
		expect(pill(key, ...groups)).toBe(expected);
	});

	it('never reports None while anything is present', () => {
		expect(pill(key, main({ [key]: 'none' }, 5), main({ [key]: 'rare' }))).toBe('Rare');
		expect(pill(key, main({ [key]: 'none' }, 7), main({ [key]: 'heavy' }))).toBe('Rare');
		expect(pill(key, main({ [key]: 'none' }, 5), main({ [key]: 'medium' }))).toBe('Rare');
	});

	it('calls a none/heavy split Mixed rather than averaging it', () => {
		expect(pill(key, main({ [key]: 'none' }, 4), main({ [key]: 'heavy' }, 2))).toBe('Mixed');
		expect(pill(key, main({ [key]: 'none' }), main({ [key]: 'heavy' }))).toBe('Mixed');
	});

	it('does not call a none/rare mix Mixed', () => {
		expect(pill(key, main({ [key]: 'none' }, 3), main({ [key]: 'rare' }, 3))).toBe('Rare');
	});
});

describe('originality — the triangle', () => {
	const C = (n = 1) => main({ originality: 'conventional' }, n);
	const U = (n = 1) => main({ originality: 'unique' }, n);
	const E = (n = 1) => main({ originality: 'experimental' }, n);

	it.each([
		['6C 2E', [C(6), E(2)], 'Conventional'],
		['5C 2U', [C(5), U(2)], 'Conventional'],
		['4C 2U 1E', [C(4), U(2), E(1)], 'Conventional'],
		['3C 1U', [C(3), U(1)], 'Conventional'],
		['4C 2U', [C(4), U(2)], 'Distinctive'],
		['7C 3U', [C(7), U(3)], 'Distinctive'],
		['2C 2U 1E', [C(2), U(2), E(1)], 'Distinctive'],
		['3U 1C', [U(3), C(1)], 'Unique'],
		['2U 2E', [U(2), E(2)], 'Unconventional'],
		['2C 2E', [C(2), E(2)], 'Exploratory'],
		['4C 3U 3E', [C(4), U(3), E(3)], 'Mixed'],
	])('%s -> %s', (_label, groups, expected) => {
		expect(pill('originality', ...groups)).toBe(expected);
	});

	it('promotes a leader that falls short of a majority', () => {
		expect(pill('originality', C(3), U(2), E(2))).toBe('Mixed');
		expect(pill('originality', C(5), U(3), E(3))).toBe('Mixed');
	});

	// The boundary the strict majority buys: exactly half is not more than half.
	it('separates a leader on exactly half from one just over it', () => {
		expect(pill('originality', C(4), U(2), E(2))).toBe('Mixed');
		expect(pill('originality', C(5), U(2), E(2))).toBe('Conventional');
	});
});

describe('ending_type — the ending you would actually reach', () => {
	it('takes the last main entry, not the value that recurs', () => {
		expect(pill('ending_type', main({ ending_type: 'cliffhanger' }, 3), main({ ending_type: 'closed' }))).toBe(
			'Closed',
		);
	});

	// The sentinel is auto-set on an unfinished watch, so it must fall through rather
	// than blanking the pill for someone mid-season.
	it('skips an in-progress latest season and reports the one before it', () => {
		expect(
			pill('ending_type', main({ ending_type: 'closed' }), main({ ending_type: 'not_applicable' })),
		).toBe('Closed');
	});

	it('ignores a side story released after the main story ended', () => {
		expect(pill('ending_type', main({ ending_type: 'closed' }), side({ ending_type: 'open' }))).toBe('Closed');
	});
});

describe('watched_format — the main story holds a veto', () => {
	const sub = (n: number, rel = main) => rel({ watched_format: 'sub' }, n);
	const dub = (n: number, rel = main) => rel({ watched_format: 'dub' }, n);

	it.each([
		['1 sub + 8 dub', [sub(1), dub(8)], 'Dub'],
		['2 sub + 8 dub', [sub(2), dub(8)], 'Dub'],
		['9 dub', [dub(9)], 'Dub'],
		['1 sub + 3 dub', [sub(1), dub(3)], 'Both'],
		['2 sub + 6 dub', [sub(2), dub(6)], 'Both'],
		['4 sub + 8 dub', [sub(4), dub(8)], 'Both'],
	])('%s -> %s', (_label, groups, expected) => {
		expect(pill('watched_format', ...groups)).toBe(expected);
	});

	it('counts a both rating toward each tally', () => {
		expect(pill('watched_format', dub(8), main({ watched_format: 'both' }))).toBe('Dub');
		expect(pill('watched_format', sub(1), main({ watched_format: 'both' }))).toBe('Both');
	});

	it('lets a side library outvoted by nothing stay a single format', () => {
		expect(pill('watched_format', dub(6), dub(2, side), sub(1, side))).toBe('Dub');
	});

	it('reports Both when one main entry disagrees with a large side library', () => {
		expect(pill('watched_format', dub(1), sub(50, side))).toBe('Both');
		expect(pill('watched_format', sub(1), dub(50, side))).toBe('Both');
	});

	it('reports Both when the side library is substantial on its own', () => {
		expect(pill('watched_format', dub(8), sub(4, side))).toBe('Both');
	});

	it('reports Both when the main story is itself split', () => {
		expect(pill('watched_format', sub(1), dub(1), dub(20, side))).toBe('Both');
	});
});

describe('the media pool', () => {
	it('reads the main story only, ignoring side entries', () => {
		// Side stories alone would drag the mean to Slow-ish; main-only keeps it Normal.
		expect(pill('pace', main({ pace: 'normal' }, 3), side({ pace: 'slow' }, 3))).toBe('Normal');
	});

	it('falls back to every rating when no main entry is rated', () => {
		expect(pill('pace', side({ pace: 'fast' }, 2))).toBe('Fast');
	});

	it('orders by the media list, not by the order ratings arrive', () => {
		const first = main({ ending_type: 'cliffhanger' })[0];
		const last = main({ ending_type: 'closed' })[0];
		const media = [first, last].map((e) => ({ uuid: e.uuid, relation_type: 'main' }) as AnimeMediaItem);
		// Ratings reversed relative to the media list — the media list is what decides.
		const ratings = [last, first].map((e) => ({ media_uuid: e.uuid, ...e.attrs }) as RatingOut);
		const index = BADGE_KEYS.indexOf('ending_type');
		expect(aggregateBadges(ratings, media)[index].value).toBe('Closed');
	});

	it('works with no media at all', () => {
		const rating = {
			pace: 'slow',
			watched_format: 'sub',
			ending_type: 'open',
			originality: 'experimental',
			fan_service: 'heavy',
			has_3d_animation: 'none',
		} as RatingOut;
		expect(aggregateBadges([rating]).map((p) => p.value)).toEqual([
			'Slow',
			'None',
			'Sub',
			'Heavy',
			'Open',
			'Experimental',
		]);
	});
});
