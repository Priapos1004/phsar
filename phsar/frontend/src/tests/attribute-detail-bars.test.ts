import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/svelte';
import AttributeDetailBars from '$lib/components/AttributeDetailBars.svelte';
import { QUALITY_COLORS } from '$lib/utils/chartColors';
import type { RatingOut } from '$lib/types/api';

// Only the attribute keys are read off a rating, so a bare object stands in for one.
const rating = (attrs: Record<string, string>) => attrs as unknown as RatingOut;

// The legend dot of a value, by its label.
const dot = (container: HTMLElement, label: string) =>
	[...container.querySelectorAll('span')]
		.find((s) => s.textContent?.trim().startsWith(`${label} (`))
		?.querySelector('span');

describe('AttributeDetailBars', () => {
	it('gives a value one colour, whichever other values are present', () => {
		const withNone = render(AttributeDetailBars, {
			props: { ratings: [rating({ fan_service: 'none' }), rating({ fan_service: 'rare' })] },
		});
		const rareBesideNone = dot(withNone.container, 'Rare')?.getAttribute('style');
		withNone.unmount();

		const alone = render(AttributeDetailBars, {
			props: { ratings: [rating({ fan_service: 'rare' }), rating({ fan_service: 'heavy' })] },
		});
		expect(dot(alone.container, 'Rare')?.getAttribute('style')).toBe(rareBesideNone);
	});

	it('paints a quality attribute worst to best, whatever else is present', () => {
		const { container } = render(AttributeDetailBars, {
			props: { ratings: [rating({ story_quality: 'weak' }), rating({ story_quality: 'outstanding' })] },
		});
		expect(dot(container, 'Weak')).toHaveStyle({ backgroundColor: QUALITY_COLORS[0] });
		expect(dot(container, 'Outstanding')).toHaveStyle({ backgroundColor: QUALITY_COLORS[3] });
	});
});
