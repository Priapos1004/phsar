import { describe, it, expect } from 'vitest';
import { compareAttribute, hasAnyAttribute, QUALITY_ATTR_KEYS } from '$lib/utils/ratingAttributes';
import type { RatingOut } from '$lib/types/api';

// Only the attribute keys are read, so a partial cast keeps the fixtures readable.
const withAttrs = (o: Partial<RatingOut>) => [o as RatingOut];

describe('hasAnyAttribute', () => {
	it('is false for a rating with no attributes set', () => {
		expect(hasAnyAttribute(withAttrs({ pace: null, story_quality: null }))).toBe(false);
	});

	it('is true when any single attribute carries a real value', () => {
		expect(hasAnyAttribute(withAttrs({ pace: 'fast' }))).toBe(true);
		expect(hasAnyAttribute(withAttrs({ story_quality: 'good' }))).toBe(true);
	});

	// The sentinel is auto-set on on-hold/dropped ratings, never chosen — so a rating
	// carrying only it must not open an otherwise-empty attribute section.
	it('does not count the auto-set not_applicable sentinel', () => {
		expect(
			hasAnyAttribute(withAttrs({ ending_type: 'not_applicable', ending_quality: 'not_applicable' })),
		).toBe(false);
	});

	it('is true when any rating in the set has one, not only the first', () => {
		expect(hasAnyAttribute([{} as RatingOut, { pace: 'slow' } as RatingOut])).toBe(true);
	});

	it('is false for an empty set', () => {
		expect(hasAnyAttribute([])).toBe(false);
	});
});

describe('compareAttribute', () => {
	it('returns neutral when the user has not set the attribute', () => {
		expect(compareAttribute('animation_quality', 'good', null)).toBe('neutral');
	});

	it('treats the not_applicable sentinel as unset (neutral)', () => {
		expect(compareAttribute('ending_quality', 'satisfying', 'not_applicable')).toBe('neutral');
	});

	it('returns match when the neighbor agrees with the current pick (distinct from unset)', () => {
		expect(compareAttribute('animation_quality', 'good', 'good')).toBe('match');
		expect(compareAttribute('watched_format', 'sub', 'sub')).toBe('match');
	});

	it('compares quality attributes by ordinal position (higher/lower)', () => {
		// animation_quality order: bad < normal < good < very_good
		expect(compareAttribute('animation_quality', 'very_good', 'good')).toBe('higher');
		expect(compareAttribute('animation_quality', 'bad', 'good')).toBe('lower');
		// ending_quality order: unsatisfying < neutral < satisfying < very_satisfying
		expect(compareAttribute('ending_quality', 'very_satisfying', 'neutral')).toBe('higher');
		expect(compareAttribute('ending_quality', 'unsatisfying', 'satisfying')).toBe('lower');
	});

	it('returns differs for categorical attributes that do not match', () => {
		// watched_format / pace / has_3d_animation are categorical → differs, never higher/lower
		expect(compareAttribute('watched_format', 'dub', 'sub')).toBe('differs');
		expect(compareAttribute('pace', 'fast', 'slow')).toBe('differs');
		expect(compareAttribute('has_3d_animation', 'heavy', 'none')).toBe('differs');
	});

	it('classifies exactly the five quality attributes', () => {
		expect([...QUALITY_ATTR_KEYS].sort()).toEqual(
			['animation_quality', 'character_depth', 'dialogue_quality', 'ending_quality', 'story_quality'],
		);
	});
});
