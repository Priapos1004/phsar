/**
 * Rating-share plumbing: turn a rendered `ShareCard` DOM node into a PNG the user can
 * save or hand to their phone's share sheet.
 *
 * Sharing is deliberately image-based rather than link-based: a hosted share page would
 * either expire or become a scrapeable endpoint exposing users' ratings. A PNG the user
 * owns is permanent, works in every messenger, and needs no public surface at all.
 */

/** Exported pixel size — portrait 4:5, the shape messengers show without cropping. */
export const SHARE_PNG_WIDTH = 1080;
export const SHARE_PNG_HEIGHT = 1350;

/**
 * CSS size the card is laid out at; the capture scales it up to the pixel size above.
 * Kept at exactly half so the scale factor is an integer 2 (no fractional device pixels
 * smearing text), and small enough that the card reads as a phone-sized composition.
 */
export const SHARE_CARD_WIDTH = SHARE_PNG_WIDTH / 2;
export const SHARE_CARD_HEIGHT = SHARE_PNG_HEIGHT / 2;

/**
 * `phsar-<slug>-rating.png` for a rating card, `phsar-<slug>.png` for a plain info card —
 * the filename shouldn't promise a score the image doesn't carry. Falls back to the bare
 * stem when a title romanizes to nothing (CJK-only).
 */
export function shareFileName(title: string, kind: 'rating' | 'info' = 'rating'): string {
	const suffix = kind === 'rating' ? '-rating' : '';
	const slug = title
		.toLowerCase()
		.normalize('NFKD')
		.replace(/\p{M}/gu, '') // drop the combining marks NFKD split off (é -> e)
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-+|-+$/g, '')
		.slice(0, 60)
		.replace(/-+$/, ''); // slice may have cut mid-separator
	return slug ? `phsar-${slug}${suffix}.png` : `phsar${suffix || '-card'}.png`;
}

/**
 * Read an image URL into a data URI, or `null` if it can't be read.
 *
 * Covers live on `cdn.myanimelist.net`, which serves `Access-Control-Allow-Origin: *`,
 * so this succeeds cross-origin and the resulting data URI is same-origin — no tainted
 * canvas at capture time. Done here rather than left to the rasterizer's own asset
 * embedding so the capture step performs no network I/O (its timing stays deterministic)
 * and a dead cover degrades to the card's "No image" placeholder instead of a blank box.
 */
export async function fetchImageAsDataUri(url: string): Promise<string | null> {
	try {
		const res = await fetch(url);
		if (!res.ok) return null;
		const blob = await res.blob();
		return await new Promise<string | null>((resolve) => {
			const reader = new FileReader();
			reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : null);
			reader.onerror = () => resolve(null);
			reader.readAsDataURL(blob);
		});
	} catch {
		return null;
	}
}

/**
 * Rasterize a laid-out share card to a PNG Blob.
 *
 * Owns every precondition the rasterizer has about the DOM, so they sit beside the
 * options that assume them: fonts resolved and one frame painted before the clone is
 * taken. The caller still owns getting the node laid out — it must be positioned
 * off-screen rather than hidden, since `display:none`/`visibility:hidden` capture blank.
 *
 * `modern-screenshot` is imported dynamically for the same reasons as the ECharts
 * singleton: it's browser-only (SSR would crash on it) and jsdom has no canvas, so
 * keeping it behind the import lets the surrounding module stay unit-testable.
 */
export async function captureCardPng(node: HTMLElement): Promise<Blob> {
	const { domToBlob } = await import('modern-screenshot');
	await document.fonts?.ready;
	await new Promise((resolve) => requestAnimationFrame(resolve));
	return domToBlob(node, {
		width: SHARE_CARD_WIDTH,
		height: SHARE_CARD_HEIGHT,
		scale: SHARE_PNG_WIDTH / SHARE_CARD_WIDTH,
		type: 'image/png',
		// The app ships no webfonts (Tailwind's system stack only), so the font-embedding
		// pass has nothing to find — skipping it avoids a pointless stylesheet crawl.
		// Adding a webfont means turning this back on.
		font: false,
	});
}

/** Can this device hand a PNG to a native share sheet? (Web Share API Level 2.) */
export function canShareFiles(file: File): boolean {
	return (
		typeof navigator !== 'undefined' &&
		typeof navigator.canShare === 'function' &&
		typeof navigator.share === 'function' &&
		navigator.canShare({ files: [file] })
	);
}

/**
 * True on iPhone/iPad, where a saved image has to travel through the share sheet.
 *
 * A UA check because no feature detection exists for the thing that actually matters: an
 * `<a download>` on iOS Safari lands in Files, and only the share sheet's "Save Image"
 * reaches the photo library. iPadOS reports itself as a Mac, so it's caught by the one
 * signal that separates it from a desktop — a touch screen.
 */
export function isIosLike(): boolean {
	if (typeof navigator === 'undefined') return false;
	const ua = navigator.userAgent ?? '';
	if (/iPad|iPhone|iPod/.test(ua)) return true;
	return /Macintosh/.test(ua) && navigator.maxTouchPoints > 1;
}

/**
 * Open the native share sheet with the PNG attached.
 *
 * Two rejections are the sheet behaving normally rather than failing, so both are
 * swallowed: `AbortError` is the user dismissing it, and `InvalidStateError` means a sheet
 * is already open. The caller guards against the second with its own in-flight flag; this
 * is the backstop for platforms that settle the previous share's promise late (or never),
 * where that flag can be clear while the browser still disagrees.
 *
 * There is no third option of closing the sheet ourselves — it's an OS surface, and the
 * Web Share API has no cancellation path.
 */
export async function shareFile(file: File, title: string): Promise<void> {
	try {
		await navigator.share({ files: [file], title });
	} catch (err) {
		if (err instanceof DOMException) {
			if (err.name === 'AbortError' || err.name === 'InvalidStateError') return;
		}
		throw err;
	}
}
