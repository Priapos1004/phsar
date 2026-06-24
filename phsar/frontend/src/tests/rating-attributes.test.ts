import { describe, it, expect } from 'vitest';
import { compareAttribute, QUALITY_ATTR_KEYS } from '$lib/utils/ratingAttributes';

describe('compareAttribute', () => {
	it('returns neutral when the user has not set the attribute', () => {
		expect(compareAttribute('animation_quality', 'good', null)).toBe('neutral');
	});

	it('treats the not_applicable sentinel as unset (neutral)', () => {
		expect(compareAttribute('ending_quality', 'satisfying', 'not_applicable')).toBe('neutral');
	});

	it('returns neutral when the neighbor matches the current pick', () => {
		expect(compareAttribute('animation_quality', 'good', 'good')).toBe('neutral');
		expect(compareAttribute('watched_format', 'sub', 'sub')).toBe('neutral');
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
