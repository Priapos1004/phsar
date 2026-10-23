/**
 * The wheel's drawing maths: whatever the start and the nudge, the drawn mood stops under
 * the pointer after the whole turns asked for; and long labels split to fit.
 */
import { describe, it, expect } from 'vitest';
import { labelLines, landingRotation } from '$lib/utils/discoverMoods';

// The segment under the pointer once the wheel has turned by `rotation`.
const underPointer = (rotation: number, count: number) =>
	Math.floor((((-rotation % 360) + 360) % 360) / (360 / count));

describe('landingRotation', () => {
	it('stops every segment under the pointer, from anywhere, nudged either way', () => {
		for (const count of [7, 10]) {
			for (let index = 0; index < count; index++) {
				for (const from of [0, 123.4, 2161, -40]) {
					for (const nudge of [-0.5, 0, 0.49]) {
						const to = landingRotation(from, index, count, 6, nudge);
						expect(underPointer(to, count), `${count}/${index} from ${from} nudge ${nudge}`).toBe(index);
						expect(to - from).toBeGreaterThanOrEqual(6 * 360);
						expect(to - from).toBeLessThan(7 * 360);
					}
				}
			}
		}
	});
});

describe('labelLines', () => {
	it('keeps a short title whole and splits a long one nearest its middle', () => {
		expect(labelLines('Power Up')).toEqual(['Power Up']);
		expect(labelLines('Off the Beaten Path')).toEqual(['Off the', 'Beaten Path']);
		expect(labelLines('Beasts & Legends')).toEqual(['Beasts &', 'Legends']);
	});

	it('takes the later space on a tie', () => {
		expect(labelLines('Twists & Turns')).toEqual(['Twists &', 'Turns']);
	});
});
