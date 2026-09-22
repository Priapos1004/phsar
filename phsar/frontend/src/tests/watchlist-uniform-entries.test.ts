import { describe, it, expect } from 'vitest';
import { uniformEntryFields } from '$lib/utils/watchlist';

/** The two fields the bulk dialog prefills from — `WatchlistOut`'s wider shape is
 *  irrelevant to the decision, so the helper takes only what it reads. */
const entry = (priority: number, tagUuid: string) => ({ priority, tag: { uuid: tagUuid } });

describe('uniformEntryFields', () => {
	it('prefills both fields when every entry agrees', () => {
		const out = uniformEntryFields([entry(1, 'a'), entry(1, 'a'), entry(1, 'a')]);
		expect(out).toEqual({ tagUuid: 'a', priority: 1, tagCount: 1, priorityCount: 1 });
	});

	it('leaves a field unset when the entries disagree on it', () => {
		// A split priority must not resolve to a winner: a bulk write applies one value
		// to all, so picking silently is how a High entry gets downgraded.
		const out = uniformEntryFields([entry(1, 'a'), entry(3, 'a')]);
		expect(out.priority).toBeUndefined();
		expect(out.priorityCount).toBe(2);
		expect(out.tagUuid).toBe('a'); // the agreeing field still prefills
	});

	it('counts each dimension separately', () => {
		const out = uniformEntryFields([entry(1, 'a'), entry(1, 'b'), entry(1, 'c')]);
		expect(out.tagUuid).toBeUndefined();
		expect(out.tagCount).toBe(3);
		expect(out.priority).toBe(1);
		expect(out.priorityCount).toBe(1);
	});

	it('reports nothing to prefill for an empty set', () => {
		// The add case: no existing entries, so the dialog falls back to its defaults
		// rather than reading undefined as "they disagree".
		expect(uniformEntryFields([])).toEqual({
			tagUuid: undefined,
			priority: undefined,
			tagCount: 0,
			priorityCount: 0,
		});
	});
});
