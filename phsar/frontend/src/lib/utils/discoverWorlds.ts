/**
 * Discover's worlds as the page draws them — presentation only, so it lives here; which
 * worlds exist and what they hold is the backend's (docs/features/browse.md).
 *
 * The colours are literal on purpose: inside Discover a world's colour stands in for the
 * theme's `--primary`, so it cannot be a theme token itself.
 */
import { Bot, Coffee, Compass, Flame, Ghost, Mic, Orbit, Puzzle, Sparkles, Swords, Zap } from 'lucide-svelte';

export type ParticleMotion = 'rise' | 'fall' | 'drift' | 'twinkle' | 'fly';

/** The signature a world's reveal plays after the spin (`utils/worldReveal.ts`). */
export type RevealKind = 'bolt' | 'swords' | 'blaze' | 'portal' | 'glitch' | 'spiral' | 'lights-out' | 'spotlight' | 'hearth' | 'ripples';

export interface WorldLook {
	icon: typeof Flame;
	color: string;
	particle: { glyph: string; motion: ParticleMotion };
	reveal: RevealKind;
}

/** Keyed by the backend's world key (`browse_service.WORLDS`). */
export const WORLD_LOOK: Record<string, WorldLook> = {
	beasts: { icon: Flame, color: '#f0883e', particle: { glyph: '•', motion: 'rise' }, reveal: 'blaze' },
	'other-worlds': { icon: Orbit, color: '#9d8cf7', particle: { glyph: '✦', motion: 'twinkle' }, reveal: 'portal' },
	cozy: { icon: Coffee, color: '#e8a07a', particle: { glyph: '🍂', motion: 'fall' }, reveal: 'hearth' },
	twists: { icon: Puzzle, color: '#2db7ae', particle: { glyph: '?', motion: 'drift' }, reveal: 'spiral' },
	steel: { icon: Swords, color: '#e2534e', particle: { glyph: '✧', motion: 'rise' }, reveal: 'swords' },
	'after-dark': { icon: Ghost, color: '#8f98f2', particle: { glyph: '🦇', motion: 'fly' }, reveal: 'lights-out' },
	future: { icon: Bot, color: '#3dbcf5', particle: { glyph: '▪', motion: 'fall' }, reveal: 'glitch' },
	'power-up': { icon: Zap, color: '#f4c543', particle: { glyph: '⚡', motion: 'twinkle' }, reveal: 'bolt' },
	spotlight: { icon: Mic, color: '#ec62a9', particle: { glyph: '★', motion: 'fall' }, reveal: 'spotlight' },
	offbeat: { icon: Compass, color: '#a8cf4c', particle: { glyph: '•', motion: 'drift' }, reveal: 'ripples' },
};

// A world the backend adds before this map knows it still gets a segment and a page.
const FALLBACK: WorldLook = { icon: Sparkles, color: '#b9a6e8', particle: { glyph: '✦', motion: 'twinkle' }, reveal: 'ripples' };

/**
 * After Dark's bat, as SVG paths in a 100 × 60 box: a body, and one wing the other mirrors,
 * hinged at `shoulder` so it can beat between `beat`'s two angles (degrees, up then down).
 * The banner and the reveal fly the same one, where an emoji would only be dragged along.
 */
export const BAT = {
	body: 'M47 24 L48 18 L50 21.5 L52 18 L53 24 Q55.5 31 52 38.5 Q50 41.5 48 38.5 Q44.5 31 47 24 Z',
	wing: 'M47.5 26 Q36 13 19 16.5 Q8 19 1.5 28 Q9.5 26.5 13.5 32 Q18.5 27.5 23.5 33 Q28.5 28.5 33 35 Q38.5 30 47.5 32.5 Z',
	shoulder: { x: 47.5, y: 28 },
	beat: [38, -28],
} as const;

export function worldLook(key: string): WorldLook {
	return WORLD_LOOK[key] ?? FALLBACK;
}

export const reducedMotion = () =>
	typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches;

/**
 * The wheel's rotation (degrees, clockwise) that stops segment `index` of `count` under
 * the pointer at the top, at least `turns` whole turns past `from`. `nudge` (−0.5…0.5)
 * moves the stop off the segment's centre, so the wheel doesn't land dead centre every
 * time; it stays inside the segment.
 */
export function landingRotation(from: number, index: number, count: number, turns = 6, nudge = 0): number {
	const segment = 360 / count;
	// Segment i spans [i, i + 1) segments clockwise from the top, and a wheel turned by R
	// shows its angle −R at the pointer.
	const stop = -(index + 0.5 + nudge * 0.7) * segment;
	const base = from + turns * 360;
	return base + ((((stop - base) % 360) + 360) % 360);
}

/** A wheel label's lines. A long title takes two, split at the space nearest its middle —
 *  the later one on a tie, so "Twists &" keeps its ampersand — so every label fits between
 *  the hub and the icon at one legible size. */
export function labelLines(title: string): string[] {
	if (title.length <= 10 || !title.includes(' ')) return [title];
	const middle = title.length / 2;
	let cut = -1;
	for (let i = title.indexOf(' '); i !== -1; i = title.indexOf(' ', i + 1)) {
		if (cut === -1 || Math.abs(i - middle) <= Math.abs(cut - middle)) cut = i;
	}
	return [title.slice(0, cut), title.slice(cut + 1)];
}

export interface Particle {
	left: number;
	top: number;
	delay: number;
	duration: number;
	size: number;
}

/** `count` particles scattered by their index — the same on the server and the client, so
 *  hydration matches. Negative delays put them mid-flight on the first frame. */
export function particles(count: number): Particle[] {
	return Array.from({ length: count }, (_, i) => ({
		left: (i * 61 + 7) % 100,
		top: (i * 37 + 11) % 85 + 5,
		delay: -((i * 2.3) % 9),
		duration: 7 + ((i * 1.7) % 5),
		size: 0.7 + ((i * 0.37) % 0.9),
	}));
}
