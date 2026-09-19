import { describe, it, expect } from 'vitest';
import {
	CHANGE_TONE_ORDER,
	TONE_RANK,
	sortMediaChanges,
	type ChangeTone,
} from '../lib/utils/mediaChangeSort';
import type {
	NameLanguage,
	UpdateSweepMediaChange,
	UpdateSweepFieldChange,
	UpdateSweepM2MDrift,
} from '../lib/types/api';

function change(over: Partial<UpdateSweepMediaChange> = {}): UpdateSweepMediaChange {
	return {
		anime_id: 1,
		anime_uuid: 'a',
		anime_title: 'A',
		media_id: 1,
		media_uuid: Math.random().toString(36).slice(2),
		media_mal_id: 1,
		media_title: 'M',
		media_relation_type: 'main',
		dynamic: [],
		static: [],
		genre_drift: null,
		studio_drift: null,
		...over,
	};
}

const fc = (field: string, old: unknown, neu: unknown): UpdateSweepFieldChange => ({ field, old, new: neu });
const drift = (field: 'genres' | 'studios' = 'genres'): UpdateSweepM2MDrift => ({
	field, media_mal_id: 1, media_title: 'M', kind: 'applied', old: [], new: ['x'], unknown_tags: [],
});
// n distinct static edits — the "many bronze" side of the medal comparison.
const statics = (n: number): UpdateSweepFieldChange[] =>
	Array.from({ length: n }, (_, i) => fc(`static_${i}`, 'a', 'b'));

const sorted = (rows: UpdateSweepMediaChange[], lang: NameLanguage = 'english') =>
	sortMediaChanges(rows, lang);

// `n` changes of the given tone, for the rank test to pit against the tones
// below it. `genre` and `studio` ignore it — those medals are 0/1 by
// construction — and `rating` uses both its fields, its own maximum.
function withTone(tone: ChangeTone, n: number): Partial<UpdateSweepMediaChange> {
	switch (tone) {
		case 'dynamic':
			return { dynamic: Array.from({ length: n }, (_, i) => fc(`dyn_${i}`, i, i + 1)) };
		case 'genre':
			return { genre_drift: drift() };
		case 'studio':
			return { studio_drift: drift('studios') };
		case 'static':
			return { static: statics(n) };
		case 'rating':
			return { dynamic: [fc('score', 7, 8), fc('scored_by', 100, 200)] };
	}
}

type MergedParts = Partial<UpdateSweepMediaChange> & {
	dynamic: UpdateSweepFieldChange[];
	static: UpdateSweepFieldChange[];
};

function merge(parts: Partial<UpdateSweepMediaChange>[]): MergedParts {
	const out: MergedParts = { dynamic: [], static: [] };
	for (const p of parts) {
		out.dynamic.push(...(p.dynamic ?? []));
		out.static.push(...(p.static ?? []));
		if (p.genre_drift) out.genre_drift = p.genre_drift;
		if (p.studio_drift) out.studio_drift = p.studio_drift;
	}
	return out;
}

describe('CHANGE_TONE_ORDER is the comparator, not a comment about it', () => {
	// Walks the exported order and, for each tone, pits ONE change of it
	// against five of every tone ranked below it. Reordering the constant
	// without reordering the comparator (or vice versa) fails here — which
	// is what keeps `MediaChangeCard`'s row order, keyed off TONE_RANK,
	// honest about the list order it claims to mirror.
	it.each(CHANGE_TONE_ORDER.slice(0, -1).map((t, i) => [t, i] as [ChangeTone, number]))(
		'%s outranks every tone below it, combined',
		(tone, i) => {
			const lower = CHANGE_TONE_ORDER.slice(i + 1) as readonly ChangeTone[];
			const winner = change(withTone(tone, 1));
			const loser = change(merge(lower.map((t) => withTone(t, 5))));
			expect(sorted([loser, winner])).toEqual([winner, loser]);
		},
	);

	// The comparator is pinned to CHANGE_TONE_ORDER above; the card reaches
	// the same order through TONE_RANK, and nothing else covers that hop.
	it('TONE_RANK ranks by position, so the card cannot disagree with the list', () => {
		CHANGE_TONE_ORDER.forEach((tone, i) => expect(TONE_RANK[tone]).toBe(i));
	});
});

describe('sortMediaChanges — medal table', () => {
	it('one gold beats five bronze: a single dynamic flip outranks five static edits', () => {
		const oneDynamic = change({ dynamic: [fc('airing_status', 'airing', 'finished')] });
		const fiveStatic = change({ static: statics(5) });
		expect(sorted([fiveStatic, oneDynamic])).toEqual([oneDynamic, fiveStatic]);
	});

	it('cascades down the medals: each rank decides only when every rank above it ties', () => {
		// Every row below carries exactly one dynamic field, so `dynamic` always
		// ties and the cascade has to run past it. Each pair then loads the
		// LOSING row with everything from the ranks beneath the deciding one, so
		// the assertion flips if that rank stops counting.
		const oneDynamic = { dynamic: [fc('episodes', 12, 13)] };

		// genre decides, against a row carrying studio + five statics.
		const withGenre = change({ ...oneDynamic, genre_drift: drift() });
		const withStudioStatic = change({
			...oneDynamic, studio_drift: drift('studios'), static: statics(5),
		});
		expect(sorted([withStudioStatic, withGenre])).toEqual([withGenre, withStudioStatic]);

		// Tie genre, and studio decides against a row carrying five statics.
		const base = { ...oneDynamic, genre_drift: drift() };
		const withStudio = change({ ...base, studio_drift: drift('studios') });
		const withStatic = change({ ...base, static: statics(5) });
		expect(sorted([withStatic, withStudio])).toEqual([withStudio, withStatic]);

		// Tie studio too, and static decides — despite the loser carrying more
		// rating churn, which sits below it.
		const moreStatic = change({ ...base, studio_drift: drift('studios'), static: statics(2) });
		const lessStatic = change({
			...base,
			studio_drift: drift('studios'),
			static: statics(1),
			dynamic: [fc('episodes', 12, 13), fc('score', 7, 8), fc('scored_by', 1, 2)],
		});
		expect(sorted([lessStatic, moreStatic])).toEqual([moreStatic, lessStatic]);
	});

	it('rating rows: both-changed outranks either alone', () => {
		// Magnitudes deliberately point the other way — a 0.001 nudge on both
		// fields against a 9-point score swing — so this fails if subrank
		// stops being compared before magnitude.
		const both = change({ dynamic: [fc('score', 7, 7.001), fc('scored_by', 100, 101)] });
		const scoreOnly = change({ dynamic: [fc('score', 1, 10)] });
		expect(sorted([scoreOnly, both])).toEqual([both, scoreOnly]);
	});

	it('rating sub-key survives: subrank is compared BEFORE magnitude', () => {
		// Both rows are a single rating field, so every medal ties and only
		// the sub-key can separate them. Magnitudes again point the other way
		// — a 0.01 score nudge against a 10,000× vote increase.
		const scoreOnly = change({ dynamic: [fc('score', 7, 7.01)] }); // mag 0.01
		const sbOnly = change({ dynamic: [fc('scored_by', 100, 1_000_000)] }); // Δlog10 ≈ 4
		expect(sorted([sbOnly, scoreOnly])).toEqual([scoreOnly, sbOnly]);
	});

	it('scored_by-only rows rank by log-scale (search-relevance) increase, not raw delta', () => {
		// +500 on 5k (Δlog10 ≈ 0.041) is more search-relevant than +1000 on 1M
		// (Δlog10 ≈ 0.0004), even though the raw delta is larger.
		const smallBase = change({ dynamic: [fc('scored_by', 5000, 5500)] });
		const hugeBase = change({ dynamic: [fc('scored_by', 1_000_000, 1_001_000)] });
		expect(sorted([hugeBase, smallBase])).toEqual([smallBase, hugeBase]);
	});

	it('both-changed rating rows: bigger weighted (score*log10(scored_by+1)) delta first', () => {
		// big: 5*log10(1001)≈15.0 → 9*log10(10001)≈36.0, Δ≈21
		const big = change({ dynamic: [fc('score', 5, 9), fc('scored_by', 1000, 10000)] });
		// small: 7*log10(101)≈14.04 → 7.1*log10(151)≈15.45, Δ≈1.4
		const small = change({ dynamic: [fc('score', 7, 7.1), fc('scored_by', 100, 150)] });
		expect(sorted([small, big])).toEqual([big, small]);
	});

	it('falls back to the displayed title A→Z when every medal and the rating key tie', () => {
		const zebra = change({ media_title: 'Zebra', static: statics(1) });
		const apple = change({ media_title: 'Apple', static: statics(1) });
		const mango = change({ media_title: 'Mango', static: statics(1) });
		expect(sorted([zebra, mango, apple])).toEqual([apple, mango, zebra]);
	});

	it('the A→Z key is the DISPLAYED title, so nameLanguage reverses the order', () => {
		// Romaji sorts one way, English the other — so the same two rows must
		// come back in opposite orders under the two settings.
		const zulu = change({ media_title: 'Zulu', media_name_eng: 'Alpha', static: statics(1) });
		const alpha = change({ media_title: 'Alpha', media_name_eng: 'Zulu', static: statics(1) });
		expect(sorted([alpha, zulu], 'english')).toEqual([zulu, alpha]);
		expect(sorted([alpha, zulu], 'romaji')).toEqual([alpha, zulu]);
	});

	it('title A→Z ranks below the medals, never above them', () => {
		// 'Apple' would win an alphabetical sort; the dynamic medal outranks it.
		const apple = change({ media_title: 'Apple', static: statics(1) });
		const zebra = change({ media_title: 'Zebra', dynamic: [fc('episodes', 12, 13)] });
		expect(sorted([apple, zebra])).toEqual([zebra, apple]);
	});
});
