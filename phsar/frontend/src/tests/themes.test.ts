import { describe, it, expect } from 'vitest';
import { inYearlyRange, themeArt } from '$lib/themes';

const on = (month: number, day: number) => new Date(2026, month - 1, day);

describe('themeArt', () => {
	it('shows the Halloween pic through October, both ends included', () => {
		expect(themeArt('blue', on(9, 30)).pic).toBe('/profile_pics/blue.png');
		expect(themeArt('blue', on(10, 1)).pic).toBe('/profile_pics/blue_halloween.png');
		expect(themeArt('blue', on(10, 31)).pic).toBe('/profile_pics/blue_halloween.png');
		expect(themeArt('blue', on(11, 1)).pic).toBe('/profile_pics/blue.png');
	});

	it('falls back to the default theme, seasonal too', () => {
		expect(themeArt('nope', on(10, 15)).pic).toBe('/profile_pics/rainbow_halloween.png');
	});

	it("crops a variant at its own focal point where it has one, else at the theme's", () => {
		expect(themeArt('red', on(10, 15)).focal).not.toBe(themeArt('red', on(11, 15)).focal);
		expect(themeArt('blue', on(10, 15)).focal).toBe(themeArt('blue', on(11, 15)).focal);
	});
});

describe('inYearlyRange', () => {
	it('wraps a range whose start comes after its end over New Year', () => {
		const newYear = (d: Date) => inYearlyRange(d, [12, 31], [1, 1]);
		expect(newYear(on(12, 31))).toBe(true);
		expect(newYear(on(1, 1))).toBe(true);
		expect(newYear(on(12, 30))).toBe(false);
		expect(newYear(on(1, 2))).toBe(false);
	});
});
