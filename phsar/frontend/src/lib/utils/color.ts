// Pure color helpers for the tag color picker. No Svelte/DOM, so unit-testable.

/** Clamp to [0,255] and 2-digit lowercase hex. */
function channel(n: number): string {
	return Math.max(0, Math.min(255, Math.round(n)))
		.toString(16)
		.padStart(2, '0');
}

/** HSL → lowercase #rrggbb. h in degrees (any sign), s/l in [0,1]. */
export function hslToHex(h: number, s: number, l: number): string {
	const hp = ((((h % 360) + 360) % 360) / 60);
	const c = (1 - Math.abs(2 * l - 1)) * s;
	const x = c * (1 - Math.abs((hp % 2) - 1));
	const m = l - c / 2;
	let r = 0;
	let g = 0;
	let b = 0;
	if (hp < 1) [r, g, b] = [c, x, 0];
	else if (hp < 2) [r, g, b] = [x, c, 0];
	else if (hp < 3) [r, g, b] = [0, c, x];
	else if (hp < 4) [r, g, b] = [0, x, c];
	else if (hp < 5) [r, g, b] = [x, 0, c];
	else [r, g, b] = [c, 0, x];
	return `#${channel((r + m) * 255)}${channel((g + m) * 255)}${channel((b + m) * 255)}`;
}

/** Validate + normalize a user-typed hex to lowercase #rrggbb, or null. Accepts a
 *  missing leading `#`; mirrors the backend `^#[0-9A-Fa-f]{6}$` rule (tag_schema). */
export function normalizeHex(v: string): string | null {
	const body = v.trim().replace(/^#/, '');
	return /^[0-9a-fA-F]{6}$/.test(body) ? `#${body.toLowerCase()}` : null;
}

/** Black or white, whichever reads better on `hex` (perceived-luminance pick). Used
 *  for the trigger's Plus glyph + the selected-cell check so they stay legible. */
export function contrastText(hex: string): '#000000' | '#ffffff' {
	const n = normalizeHex(hex);
	if (!n) return '#000000';
	const r = parseInt(n.slice(1, 3), 16);
	const g = parseInt(n.slice(3, 5), 16);
	const b = parseInt(n.slice(5, 7), 16);
	// Rec. 601 luma, 0..1. >0.6 is a light background → use black text.
	return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 ? '#000000' : '#ffffff';
}

export interface HexCell {
	hex: string;
	key: string;
}

// Honeycomb silhouette: rows of these counts make a hexagon (widest in the middle).
const WHEEL_ROW_COUNTS = [4, 5, 6, 7, 6, 5, 4];

/**
 * A hexagonal color wheel laid out as honeycomb rows. Each cell's angle from the
 * center sets its hue and its distance sets its lightness — a near-black center that
 * brightens to a light rim — so the middle is black (a black bookmark) and vivid hues
 * ring outward. Deterministic (no randomness); computed once and rendered as clip-path
 * hexagons by the picker.
 */
export function buildColorWheel(): HexCell[][] {
	const midRow = (WHEEL_ROW_COUNTS.length - 1) / 2;
	// Pass 1: each cell's polar distance (→ lightness) + angle (→ hue), computed once.
	const cells = WHEEL_ROW_COUNTS.map((count, r) =>
		Array.from({ length: count }, (_, j) => {
			const x = j - (count - 1) / 2;
			const y = r - midRow;
			return { key: `${r}-${j}`, d: Math.hypot(x, y), hue: (Math.atan2(y, x) * 180) / Math.PI };
		}),
	);
	let maxD = 0;
	for (const row of cells) for (const c of row) maxD = Math.max(maxD, c.d);
	return cells.map((row) =>
		row.map(({ key, d, hue }) =>
			d === 0
				? { hex: '#141414', key } // black center
				: { hex: hslToHex(hue, 0.85, 0.12 + 0.76 * (d / maxD)), key },
		),
	);
}
