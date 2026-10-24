import { describe, it, expect } from 'vitest';
import { inYearlyRange, SEASONAL_PICS, THEMES, themeArt } from '$lib/themes';

const on = (month: number, day: number) => new Date(2026, month - 1, day);

describe('themeArt', () => {
	it('shows the Halloween pic through October, both ends included', () => {
		expect(themeArt('blue', on(9, 30)).pic).toBe('/profile_pics/blue.webp');
		expect(themeArt('blue', on(10, 1)).pic).toBe('/profile_pics/blue_halloween.webp');
		expect(themeArt('blue', on(10, 31)).pic).toBe('/profile_pics/blue_halloween.webp');
		expect(themeArt('blue', on(11, 1)).pic).toBe('/profile_pics/blue.webp');
	});

	it('falls back to the default theme, seasonal too', () => {
		expect(themeArt('nope', on(10, 15)).pic).toBe('/profile_pics/rainbow_halloween.webp');
	});

	it('pairs each pic with its settings-tile thumbnail', () => {
		expect(themeArt('blue', on(10, 15)).thumb).toBe('/profile_pics/thumbs/blue_halloween.webp');
	});

	// A new theme or season needs both converted files (the cwebp lines in themes.ts).
	it('has a served file for every pic and thumbnail it can return', () => {
		const served = new Set(Object.keys(import.meta.glob('/static/profile_pics/**/*.webp')));
		const days = [on(6, 15), ...SEASONAL_PICS.map(({ from }) => on(from[0], from[1]))];
		for (const key of Object.keys(THEMES)) {
			for (const day of days) {
				const { pic, thumb } = themeArt(key, day);
				for (const path of [pic, thumb]) expect(served.has(`/static${path}`), path).toBe(true);
			}
		}
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
