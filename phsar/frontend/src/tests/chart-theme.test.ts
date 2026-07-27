import { describe, it, expect } from 'vitest';
import { paddedAxisMin } from '$lib/utils/chartTheme';

describe('paddedAxisMin', () => {
	it('pads below the observed minimum so a narrow span fills the axis', () => {
		// 112d → 115d cumulative watch time: the floor lands just under 112d, not at 0.
		const min = 112 * 86400;
		const max = 115 * 86400;
		const floor = paddedAxisMin({ min, max });
		expect(floor).toBeLessThan(min);
		expect(floor).toBeCloseTo(min - (max - min) * 0.1, 6);
	});

	it('still opens a window when the series is flat (nothing watched in range)', () => {
		const v = 100 * 86400;
		const floor = paddedAxisMin({ min: v, max: v });
		expect(floor).toBeGreaterThan(0);
		expect(floor).toBeLessThan(v); // a zero-height axis would render nothing
	});

	it('is 0 for an empty range and never negative', () => {
		expect(paddedAxisMin({ min: 0, max: 0 })).toBe(0);
		// A series starting at 0 pads below it, so the clamp is what keeps a duration
		// axis off negative ticks.
		expect(paddedAxisMin({ min: 0, max: 3600 })).toBe(0);
	});
});
