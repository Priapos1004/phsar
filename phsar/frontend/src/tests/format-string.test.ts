import { describe, it, expect } from 'vitest';
import { formatNumber, formatDuration, formatDecimalDigits } from '$lib/utils/formatString';

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
