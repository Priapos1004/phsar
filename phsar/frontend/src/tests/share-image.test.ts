import { describe, it, expect, vi, afterEach } from 'vitest';
import { canShareFiles, fetchImageAsDataUri, shareFileName } from '$lib/utils/shareImage';

afterEach(() => vi.unstubAllGlobals());

describe('shareFileName', () => {
	it('slugifies the title', () => {
		expect(shareFileName('Attack on Titan')).toBe('phsar-attack-on-titan-rating.png');
	});

	it('collapses punctuation runs into single separators and trims the edges', () => {
		expect(shareFileName('Re:ZERO -Starting Life in Another World-')).toBe(
			'phsar-re-zero-starting-life-in-another-world-rating.png',
		);
	});

	it('folds accents to their base letters rather than dropping them', () => {
		expect(shareFileName('Café Terrace')).toBe('phsar-cafe-terrace-rating.png');
	});

	it('falls back when a title has no ASCII to slugify (CJK-only)', () => {
		expect(shareFileName('進撃の巨人')).toBe('phsar-rating.png');
	});

	it('never emits a trailing separator when the length cap cuts mid-word', () => {
		const name = shareFileName(`${'a'.repeat(60)} tail`);
		expect(name.endsWith('-rating.png')).toBe(true);
		expect(name).not.toContain('--');
	});
});

describe('fetchImageAsDataUri', () => {
	it('reads a fetched image into a data URI', async () => {
		vi.stubGlobal(
			'fetch',
			vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['x'], { type: 'image/png' }) }),
		);
		await expect(fetchImageAsDataUri('https://cdn.example/c.png')).resolves.toMatch(
			/^data:image\/png;base64,/,
		);
	});

	// A dead cover must degrade to the card's "No image" placeholder, never break the export.
	it('returns null on a non-ok response', async () => {
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, blob: async () => new Blob() }));
		await expect(fetchImageAsDataUri('https://cdn.example/gone.png')).resolves.toBeNull();
	});

	it('returns null when the request itself throws (offline, CORS)', async () => {
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
		await expect(fetchImageAsDataUri('https://cdn.example/c.png')).resolves.toBeNull();
	});
});

describe('canShareFiles', () => {
	const png = new File([''], 'a.png', { type: 'image/png' });

	it('is false when the Web Share API is absent (desktop browsers)', () => {
		vi.stubGlobal('navigator', {});
		expect(canShareFiles(png)).toBe(false);
	});

	it('is false when the platform refuses this file type', () => {
		vi.stubGlobal('navigator', { share: vi.fn(), canShare: vi.fn().mockReturnValue(false) });
		expect(canShareFiles(png)).toBe(false);
	});

	it('is true when the platform accepts the PNG', () => {
		vi.stubGlobal('navigator', { share: vi.fn(), canShare: vi.fn().mockReturnValue(true) });
		expect(canShareFiles(png)).toBe(true);
	});
});
