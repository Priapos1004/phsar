import { describe, it, expect } from 'vitest';
import { formatNumber, formatDuration, formatDecimalDigits, clampAndSnapScore } from '$lib/utils/formatString';

describe('formatNumber', () => {
	it('formats integers with commas', () => {
		expect(formatNumber(1234242)).toBe('1,234,242');
	});

	it('preserves decimals', () => {
		expect(formatNumber(1234.12)).toBe('1,234.12');
	});

	it('handles small numbers', () => {
		expect(formatNumber(42)).toBe('42');
	});

	it('handles zero', () => {
		expect(formatNumber(0)).toBe('0');
	});

	it('accepts string input', () => {
		expect(formatNumber('1234567')).toBe('1,234,567');
	});
});

describe('formatDuration', () => {
	it('formats seconds only', () => {
		expect(formatDuration(45)).toBe('45s');
	});

	it('formats minutes and seconds', () => {
		expect(formatDuration(125)).toBe('2m 5s');
	});

	it('formats hours, minutes, seconds', () => {
		expect(formatDuration(3661)).toBe('1h 1m 1s');
	});

	it('formats days', () => {
		expect(formatDuration(90000)).toBe('1d 1h');
	});

	it('returns 0s for zero', () => {
		expect(formatDuration(0)).toBe('0s');
	});

	it('returns 0s for negative', () => {
		expect(formatDuration(-5)).toBe('0s');
	});
});

describe('formatDecimalDigits', () => {
	it('pads with trailing zeros', () => {
		expect(formatDecimalDigits(5, 2)).toBe('5.00');
	});

	it('rounds to specified digits', () => {
		expect(formatDecimalDigits(3.14159, 2)).toBe('3.14');
	});

	it('extends decimal places', () => {
		expect(formatDecimalDigits(7.8, 4)).toBe('7.8000');
	});
});

describe('clampAndSnapScore', () => {
	describe('step 0.5', () => {
		const step = 0.5;

		it('rounds down to nearest 0.5', () => {
			expect(clampAndSnapScore(6.6, step)).toBe(6.5);
		});

		it('rounds up to nearest 0.5', () => {
			expect(clampAndSnapScore(6.8, step)).toBe(7.0);
		});

		it('snaps 9.656 to 9.5', () => {
			expect(clampAndSnapScore(9.656, step)).toBe(9.5);
		});

		it('keeps exact 0.5 values unchanged', () => {
			expect(clampAndSnapScore(7.5, step)).toBe(7.5);
		});

		it('keeps exact integers unchanged', () => {
			expect(clampAndSnapScore(8.0, step)).toBe(8.0);
		});

		it('clamps values above 10 to 10', () => {
			expect(clampAndSnapScore(15, step)).toBe(10.0);
			expect(clampAndSnapScore(10.3, step)).toBe(10.0);
		});

		it('clamps negative values to 0', () => {
			expect(clampAndSnapScore(-1, step)).toBe(0.0);
			expect(clampAndSnapScore(-0.5, step)).toBe(0.0);
		});

		it('handles zero', () => {
			expect(clampAndSnapScore(0, step)).toBe(0.0);
		});

		it('handles NaN as 0', () => {
			expect(clampAndSnapScore(NaN, step)).toBeNaN();
		});

		it('snaps 0.1 to 0', () => {
			expect(clampAndSnapScore(0.1, step)).toBe(0.0);
		});

		it('snaps 0.3 to 0.5', () => {
			expect(clampAndSnapScore(0.3, step)).toBe(0.5);
		});

		it('snaps 9.9 to 10', () => {
			expect(clampAndSnapScore(9.9, step)).toBe(10.0);
		});
	});

	describe('step 1', () => {
		const step = 1;

		it('rounds to nearest integer', () => {
			expect(clampAndSnapScore(6.6, step)).toBe(7);
			expect(clampAndSnapScore(6.4, step)).toBe(6);
		});

		it('clamps above 10', () => {
			expect(clampAndSnapScore(12, step)).toBe(10);
		});

		it('clamps below 0', () => {
			expect(clampAndSnapScore(-3, step)).toBe(0);
		});
	});

	describe('step 0.25', () => {
		const step = 0.25;

		it('snaps to nearest quarter', () => {
			expect(clampAndSnapScore(6.6, step)).toBe(6.5);
			expect(clampAndSnapScore(6.13, step)).toBe(6.25);
			expect(clampAndSnapScore(6.9, step)).toBe(7.0);
		});
	});
});
