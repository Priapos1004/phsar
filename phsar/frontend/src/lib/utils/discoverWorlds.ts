/**
 * Discover's worlds as the page draws them — presentation only, so it lives here; which
 * worlds exist and what they hold is the backend's (docs/features/browse.md).
 *
 * The colours are literal on purpose: inside Discover a world's colour stands in for the
 * theme's `--primary`, so it cannot be a theme token itself.
 */
import { Bot, Coffee, Compass, Flame, Ghost, Mic, Orbit, Puzzle, Sparkles, Swords, Zap } from 'lucide-svelte';

export type ParticleMotion = 'rise' | 'fall' | 'drift' | 'twinkle';

export interface WorldLook {
	icon: typeof Flame;
	color: string;
	particle: { glyph: string; motion: ParticleMotion };
}

/** Keyed by the backend's world key (`browse_service.WORLDS`). */
export const WORLD_LOOK: Record<string, WorldLook> = {
	beasts: { icon: Flame, color: '#f0883e', particle: { glyph: '•', motion: 'rise' } },
	'other-worlds': { icon: Orbit, color: '#9d8cf7', particle: { glyph: '✦', motion: 'twinkle' } },
	cozy: { icon: Coffee, color: '#e8a07a', particle: { glyph: '🍂', motion: 'fall' } },
	twists: { icon: Puzzle, color: '#2db7ae', particle: { glyph: '?', motion: 'drift' } },
	steel: { icon: Swords, color: '#e2534e', particle: { glyph: '✧', motion: 'rise' } },
	'after-dark': { icon: Ghost, color: '#8f98f2', particle: { glyph: '🦇', motion: 'drift' } },
	future: { icon: Bot, color: '#3dbcf5', particle: { glyph: '▪', motion: 'fall' } },
	'power-up': { icon: Zap, color: '#f4c543', particle: { glyph: '⚡', motion: 'twinkle' } },
	spotlight: { icon: Mic, color: '#ec62a9', particle: { glyph: '★', motion: 'fall' } },
	offbeat: { icon: Compass, color: '#a8cf4c', particle: { glyph: '•', motion: 'drift' } },
};

// A world the backend adds before this map knows it still gets a segment and a page.
const FALLBACK: WorldLook = { icon: Sparkles, color: '#b9a6e8', particle: { glyph: '✦', motion: 'twinkle' } };

export function worldLook(key: string): WorldLook {
	return WORLD_LOOK[key] ?? FALLBACK;
}

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
