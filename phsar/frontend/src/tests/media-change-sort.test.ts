import { describe, it, expect } from 'vitest';
import { sortMediaChanges } from '../lib/utils/mediaChangeSort';
import type { UpdateSweepMediaChange, UpdateSweepFieldChange, UpdateSweepM2MDrift } from '../lib/types/api';

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
const drift = (): UpdateSweepM2MDrift => ({
	field: 'genres', media_mal_id: 1, media_title: 'M', kind: 'applied', old: [], new: ['x'], unknown_tags: [],
});

function sorted(rows: UpdateSweepMediaChange[]): UpdateSweepMediaChange[] {
	return sortMediaChanges(rows);
}

describe('sortMediaChanges', () => {
	it('orders groups static > genre/studio > dynamic(non-rating) > rating-only', () => {
		const rating = change({ dynamic: [fc('score', 7, 8)] });
		const dynamic = change({ dynamic: [fc('episodes', 12, 13)] });
		const genre = change({ genre_drift: drift() });
		const stat = change({ static: [fc('title', 'a', 'b')] });
		const out = sorted([rating, dynamic, genre, stat]);
		expect(out).toEqual([stat, genre, dynamic, rating]);
	});

	it('within a group, more total changes first', () => {
		const few = change({ static: [fc('title', 'a', 'b')] });
		const many = change({ static: [fc('title', 'a', 'b')], dynamic: [fc('episodes', 1, 2)], genre_drift: drift() });
		expect(sorted([few, many])).toEqual([many, few]);
	});

	it('rating group: both-changed > score-only > scored_by-only', () => {
		const both = change({ dynamic: [fc('score', 7, 8), fc('scored_by', 100, 200)] });
		const scoreOnly = change({ dynamic: [fc('score', 7, 9)] });
		const sbOnly = change({ dynamic: [fc('scored_by', 100, 5000)] });
		expect(sorted([sbOnly, scoreOnly, both])).toEqual([both, scoreOnly, sbOnly]);
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
});
