import { describe, it, expect, vi, afterEach } from 'vitest';
import { canShareFiles, fetchImageAsDataUri, isIosLike, shareFileName } from '$lib/utils/shareImage';

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

describe('isIosLike', () => {
	const IPHONE =
		'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';
	const MAC =
		'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15';

	it('detects an iPhone', () => {
		vi.stubGlobal('navigator', { userAgent: IPHONE, maxTouchPoints: 5 });
		expect(isIosLike()).toBe(true);
	});

	// iPadOS ships the desktop UA string, so the touch screen is the only thing left to go on.
	it('detects an iPad masquerading as a Mac', () => {
		vi.stubGlobal('navigator', { userAgent: MAC, maxTouchPoints: 5 });
		expect(isIosLike()).toBe(true);
	});

	it('is false on a real Mac', () => {
		vi.stubGlobal('navigator', { userAgent: MAC, maxTouchPoints: 0 });
		expect(isIosLike()).toBe(false);
	});

	it('is false on Android, where a download already reaches the gallery', () => {
		vi.stubGlobal('navigator', {
			userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/126 Mobile',
			maxTouchPoints: 5,
		});
		expect(isIosLike()).toBe(false);
	});
});
