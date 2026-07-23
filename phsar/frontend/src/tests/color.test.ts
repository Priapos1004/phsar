import { describe, it, expect } from 'vitest';
import { hslToHex, normalizeHex, contrastText, buildColorWheel } from '$lib/utils/color';
import { DEFAULT_NEW_TAG_COLOR } from '$lib/utils/watchlist';

describe('hslToHex', () => {
	it('converts the primaries + achromatics', () => {
		expect(hslToHex(0, 1, 0.5)).toBe('#ff0000');
		expect(hslToHex(120, 1, 0.5)).toBe('#00ff00');
		expect(hslToHex(240, 1, 0.5)).toBe('#0000ff');
		expect(hslToHex(0, 0, 0)).toBe('#000000');
		expect(hslToHex(0, 0, 1)).toBe('#ffffff');
		expect(hslToHex(0, 0, 0.5)).toBe('#808080');
	});

	it('normalizes out-of-range / negative hue', () => {
		expect(hslToHex(-120, 1, 0.5)).toBe('#0000ff'); // -120 ≡ 240
		expect(hslToHex(360, 1, 0.5)).toBe('#ff0000'); // 360 ≡ 0
	});
});

describe('normalizeHex', () => {
	it('accepts valid hex, lowercasing and adding the #', () => {
		expect(normalizeHex('#3b82f6')).toBe('#3b82f6');
		expect(normalizeHex('#3B82F6')).toBe('#3b82f6');
		expect(normalizeHex('3b82f6')).toBe('#3b82f6'); // missing #
		expect(normalizeHex('  #ABCDEF  ')).toBe('#abcdef'); // trimmed
	});

	it('rejects malformed values', () => {
		expect(normalizeHex('#fff')).toBeNull(); // 3-digit shorthand not allowed (mirrors backend)
		expect(normalizeHex('#12345g')).toBeNull(); // non-hex char
		expect(normalizeHex('rgb(0,0,0)')).toBeNull();
		expect(normalizeHex('')).toBeNull();
	});
});

describe('contrastText', () => {
	it('picks the readable text color for a background', () => {
		expect(contrastText('#000000')).toBe('#ffffff');
		expect(contrastText('#ffffff')).toBe('#000000');
		expect(contrastText('#3b82f6')).toBe('#ffffff'); // mid blue reads dark → white text
		expect(contrastText('#fde047')).toBe('#000000'); // bright yellow → black text
	});

	it('falls back to black for an invalid color', () => {
		expect(contrastText('nope')).toBe('#000000');
	});
});

describe('buildColorWheel', () => {
	const wheel = buildColorWheel();

	it('lays out a hexagon honeycomb (37 cells)', () => {
		expect(wheel.map((r) => r.length)).toEqual([4, 5, 6, 7, 6, 5, 4]);
		expect(wheel.flat()).toHaveLength(37);
	});

	it('emits only valid lowercase #rrggbb, with a black center', () => {
		for (const cell of wheel.flat()) expect(cell.hex).toMatch(/^#[0-9a-f]{6}$/);
		expect(wheel[3][3].hex).toBe('#141414'); // middle of the middle row = black
	});

	// The new-list default must be a selectable cell, else the picker can't re-select it
	// (it would need a page refresh to restore) — the regression this guards.
	it('exposes DEFAULT_NEW_TAG_COLOR as one of its cells', () => {
		expect(wheel.flat().map((c) => c.hex)).toContain(DEFAULT_NEW_TAG_COLOR);
	});
});
