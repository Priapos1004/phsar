/**
 * The reveal's canvas side: each signature's light and particles, drawn additively so
 * overlapping glow brightens the way light does. `WorldReveal.svelte` owns the stage, the
 * DOM layers and the swap; both are timed from `BEAT`, so the canvas and the CSS hit the
 * same frames.
 */
import { cubicInOut, cubicOut, quadOut } from 'svelte/easing';
import { BAT, type RevealKind, type WorldLook } from './discoverWorlds';

/** The reveal's beats, in ms from its start. */
export const BEAT = {
	strike: 380, // the signature starts, after the anticipation beat
	freeze: 780, // hit-stop: the canvas holds its frame
	impact: 860, // the impact frame: black, the signature's shapes in white
	peak: 900, // the flash peak, under which the page swaps
	title: 980, // the title card lands, and holds long enough to be read
	clear: 2700, // the stage starts to clear
	end: 3150,
} as const;

// A punching scene's clock stands still from the freeze to the peak, so the hit-stop holds
// the frame and nothing has moved on when the impact frame clears.
const HOLD = BEAT.peak - BEAT.freeze;
// How long the speed lines take to fade after the peak.
const SPEED_FADE = 420;
// The stage clears over this, and every scene fades out with it.
const FADE = BEAT.end - BEAT.clear;
// Below this an alpha can't be seen, even white under 'lighter' — half the smallest 8-bit
// step — so an effect that has faded stops costing anything rather than drawing on unseen.
const UNSEEN = 0.002;

interface Point {
	x: number;
	y: number;
}
type Rand = () => number;
interface Channel {
	points: Point[];
	width: number;
}

/**
 * A branching bolt from `from` to `to` inside `w` × `h`: the main channel first, then its
 * forks, each with a width relative to the main channel's; `forks` is the chance of one at
 * each point along the channel's upper two thirds. Midpoint displacement: each pass
 * pushes every segment's middle sideways by a share of its length, halving the share every
 * pass, so the bolt is jagged at every scale and still lands where it was aimed.
 */
export function bolt(from: Point, to: Point, w: number, h: number, rand: Rand, forks = 0.14): Channel[] {
	const main = displace(from, to, 0.24, 6, rand);
	const channels = [{ points: main, width: 1 }];
	const reach = Math.hypot(to.x - from.x, to.y - from.y);
	for (let i = 4; i < main.length * 0.66; i++) {
		if (rand() > forks) continue;
		const start = main[i];
		const heading =
			Math.atan2(main[i + 1].y - start.y, main[i + 1].x - start.x) +
			(rand() < 0.5 ? -1 : 1) * (0.35 + rand() * 0.55);
		const length = reach * (0.12 + rand() * 0.2);
		const end = { x: start.x + Math.cos(heading) * length, y: start.y + Math.sin(heading) * length };
		channels.push({ points: displace(start, end, 0.28, 4, rand), width: 0.45 });
	}
	for (const channel of channels) {
		for (const p of channel.points) {
			p.x = Math.min(Math.max(p.x, 0), w);
			p.y = Math.min(Math.max(p.y, 0), h);
		}
	}
	return channels;
}

function displace(a: Point, b: Point, roughness: number, passes: number, rand: Rand): Point[] {
	let points = [{ ...a }, { ...b }];
	let share = roughness * Math.hypot(b.x - a.x, b.y - a.y);
	for (let pass = 0; pass < passes; pass++) {
		const next = [points[0]];
		for (let i = 1; i < points.length; i++) {
			const p = points[i - 1];
			const q = points[i];
			const length = Math.hypot(q.x - p.x, q.y - p.y) || 1;
			const offset = (rand() - 0.5) * share;
			next.push({ x: (p.x + q.x) / 2 - ((q.y - p.y) / length) * offset, y: (p.y + q.y) / 2 + ((q.x - p.x) / length) * offset }, q);
		}
		points = next;
		share /= 2;
	}
	return points;
}

interface Scene {
	/** One frame at `u` ms from the strike beat on the scene's clock, `dt` seconds after the
	 *  last; `hold` falls from 1 to 0 as the stage clears. */
	draw(ctx: CanvasRenderingContext2D, u: number, dt: number, hold: number): void;
	/** A punching scene's impact frame: its silhouette, laid in white on the loop's black. */
	impact?(ctx: CanvasRenderingContext2D): void;
}
interface Stage {
	ctx: CanvasRenderingContext2D;
	w: number;
	h: number;
	centre: Point;
	/** The screen's shorter side, which a scene sizes its shapes by. */
	span: number;
	/** `density(w, h)` of this screen. */
	room: number;
	color: string;
	glyph: string;
	rand: Rand;
	/** The flash peak and the start of the clear, on the scene's clock. */
	peak: number;
	clear: number;
}

/**
 * Each kind's scene and, for a soft one, how the stage plays it: how strong the wash of its
 * colour is that stands in for the white flash, and whether the shockwave ring goes out. A
 * soft signature flows straight through — no hit-stop, impact frame, shake, speed lines or
 * burst of glyphs — so it has no impact frame to draw.
 */
interface Signature {
	scene: (stage: Stage) => Scene;
	soft?: { wash: number; ring: boolean };
}
const SIGNATURES: Record<RevealKind, Signature> = {
	bolt: { scene: boltScene },
	swords: { scene: swordsScene },
	blaze: { scene: blazeScene },
	portal: { scene: portalScene },
	glitch: { scene: glitchScene },
	spiral: { scene: spiralScene },
	spotlight: { scene: spotlightScene },
	'lights-out': { scene: lightsOutScene, soft: { wash: 50, ring: false } },
	hearth: { scene: hearthScene, soft: { wash: 28, ring: false } },
	ripples: { scene: ripplesScene, soft: { wash: 55, ring: true } },
};

/** A soft signature's stage, or nothing for one that punches. */
export const softness = (kind: RevealKind) => SIGNATURES[kind].soft;
export const punches = (kind: RevealKind) => !softness(kind);

/** Run `look`'s signature on `canvas` until the reveal ends; returns the stop. A canvas with
 *  no 2D context (jsdom) draws nothing, and the stage around it still plays. */
export function runReveal(canvas: HTMLCanvasElement, look: WorldLook, rand: Rand = Math.random): () => void {
	const ctx = canvas.getContext('2d');
	const w = canvas.clientWidth;
	const h = canvas.clientHeight;
	if (!ctx || !w || !h) return () => {};
	// ponytail: the backing store is capped near 4 MP, so a 4K screen fills as fast as a
	// phone; a WebGL path if a large screen still drops frames.
	const dpr = Math.min(devicePixelRatio || 1, 2, Math.sqrt(4e6 / (w * h)));
	canvas.width = Math.round(w * dpr);
	canvas.height = Math.round(h * dpr);
	ctx.scale(dpr, dpr);
	ctx.lineCap = 'round';
	ctx.lineJoin = 'round';

	const punch = punches(look.reveal);
	const hold = punch ? HOLD : 0;
	const scene = SIGNATURES[look.reveal].scene({
		ctx,
		w,
		h,
		centre: { x: w / 2, y: h / 2 },
		span: Math.min(w, h),
		room: density(w, h),
		color: look.color,
		glyph: look.particle.glyph,
		rand,
		peak: BEAT.peak - hold - BEAT.strike,
		clear: BEAT.clear - hold - BEAT.strike,
	});
	let frame = 0;
	let start = -1;
	let last = -BEAT.strike;
	const tick = (now: number) => {
		if (start < 0) start = now;
		const t = now - start;
		const pastPeak = t >= BEAT.peak;
		const u = (pastPeak ? t - hold : t) - BEAT.strike;
		if (t >= BEAT.end) {
			ctx.clearRect(0, 0, w, h);
			return;
		}
		frame = requestAnimationFrame(tick);
		if (punch && t >= BEAT.freeze && t < BEAT.impact) return;
		ctx.clearRect(0, 0, w, h);
		ctx.globalAlpha = 1;
		ctx.globalCompositeOperation = 'source-over';
		if (punch && t >= BEAT.impact && !pastPeak) {
			darken(ctx, w, h, 1);
			speedLines(ctx, w, h, rand, 0.9);
			ctx.globalAlpha = 1;
			ctx.fillStyle = ctx.strokeStyle = '#fff';
			scene.impact?.(ctx);
			return;
		}
		scene.draw(ctx, u, Math.min(u - last, 50) / 1000, fadeFrom(t, BEAT.clear, FADE));
		last = u;
		if (punch && pastPeak) {
			ctx.globalCompositeOperation = 'lighter';
			speedLines(ctx, w, h, rand, 0.55 * fadeFrom(t, BEAT.peak, SPEED_FADE));
		}
	};
	frame = requestAnimationFrame(tick);
	return () => cancelAnimationFrame(frame);
}

/** Anime speed lines: thin white wedges rushing in from past the corners towards the
 *  centre, scattered afresh every frame so they flicker. */
function speedLines(ctx: CanvasRenderingContext2D, w: number, h: number, rand: Rand, alpha: number) {
	if (alpha <= 0) return;
	const cx = w / 2;
	const cy = h / 2;
	const outer = Math.hypot(w, h) * 0.6;
	ctx.globalAlpha = alpha;
	ctx.fillStyle = '#fff';
	ctx.beginPath();
	for (let i = 0; i < 56; i++) {
		const a = rand() * Math.PI * 2;
		const half = 0.003 + rand() * 0.009;
		const inner = Math.min(w, h) * (0.2 + rand() * 0.3);
		ctx.moveTo(cx + Math.cos(a - half) * outer, cy + Math.sin(a - half) * outer);
		ctx.lineTo(cx + Math.cos(a) * inner, cy + Math.sin(a) * inner);
		ctx.lineTo(cx + Math.cos(a + half) * outer, cy + Math.sin(a + half) * outer);
		ctx.closePath();
	}
	ctx.fill();
}

const pulse = (x: number, tau: number) => (x < 0 ? 0 : Math.exp(-x / tau));
// 0 until `from`, then up to 1 over `ms`; `fadeFrom` the other way. Clamped both ways: a
// `globalAlpha` outside 0–1 is ignored, not clamped, so the previous value would draw instead.
const ramp = (u: number, from: number, ms: number) => Math.min(1, Math.max(0, (u - from) / ms));
const fadeFrom = (u: number, from: number, ms: number) => 1 - ramp(u, from, ms);

/** How much more than a phone's screen there is to fill, so particle counts grow with it
 *  without turning a large screen into a blizzard. */
const density = (w: number, h: number) => Math.min(2.5, Math.max(0.7, (w * h) / (390 * 844)));

/** The whole screen dimmed towards black. */
function darken(ctx: CanvasRenderingContext2D, w: number, h: number, alpha: number) {
	ctx.globalCompositeOperation = 'source-over';
	ctx.globalAlpha = alpha;
	ctx.fillStyle = '#000';
	ctx.fillRect(0, 0, w, h);
}

/** A radial glow round `at`, its colour fading out to the edge; `core` gives it a white-hot
 *  centre. */
function glow(ctx: CanvasRenderingContext2D, at: Point, radius: number, alpha: number, color: string, core = true) {
	if (alpha < UNSEEN) return;
	const g = ctx.createRadialGradient(at.x, at.y, 0, at.x, at.y, radius);
	if (core) g.addColorStop(0, '#fff');
	g.addColorStop(core ? 0.12 : 0, color);
	g.addColorStop(1, 'transparent');
	ctx.globalAlpha = alpha;
	ctx.fillStyle = g;
	ctx.fillRect(at.x - radius, at.y - radius, radius * 2, radius * 2);
}

/** A line of light's shape, its width relative to the scene's base width for it. Traced once
 *  where the shape never changes, rather than every frame. */
interface Traced {
	path: Path2D;
	width: number;
}
/** `channels` as one path per width. */
function trace(channels: Channel[]): Traced[] {
	const paths = new Map<number, Path2D>();
	for (const { points, width } of channels) {
		const path = paths.get(width) ?? new Path2D();
		paths.set(width, path);
		path.moveTo(points[0].x, points[0].y);
		for (const p of points) path.lineTo(p.x, p.y);
	}
	return [...paths].map(([width, path]) => ({ path, width }));
}

function circle(at: Point, r: number): Path2D {
	const path = new Path2D();
	path.arc(at.x, at.y, Math.max(0, r), 0, Math.PI * 2);
	return path;
}

// A line of light, wide to narrow: the glow, the body in its colour, the white-hot core.
const PASSES = [
	[18, 0.12, false],
	[7, 0.4, false],
	[2.2, 1, true],
] as const;
function strokeLight(ctx: CanvasRenderingContext2D, traced: Traced[], color: string, scale: number, alpha: number) {
	if (alpha < UNSEEN) return;
	for (const [width, share, white] of PASSES) {
		ctx.strokeStyle = white ? '#fff' : color;
		ctx.globalAlpha = alpha * share;
		for (const t of traced) {
			ctx.lineWidth = width * t.width * scale;
			ctx.stroke(t.path);
		}
	}
}

/** A square drawn once for a scene to stamp, `size` across: a blurred `fillText` or a fresh
 *  gradient per particle per frame is what drops a phone's frames. */
function sprite(size: number, paint: (g: CanvasRenderingContext2D) => void): HTMLCanvasElement {
	const canvas = document.createElement('canvas');
	canvas.width = canvas.height = size;
	const g = canvas.getContext('2d');
	if (g) paint(g);
	return canvas;
}

/** `glyph` with its glow, `px` tall in a sprite twice that so the blur has room. */
function glyphSprite(glyph: string, color: string, px: number): HTMLCanvasElement {
	return sprite(px * 2, (g) => {
		g.font = `${px}px system-ui, sans-serif`;
		g.textAlign = 'center';
		g.textBaseline = 'middle';
		g.fillStyle = color;
		g.shadowColor = color;
		g.shadowBlur = px * 0.35;
		g.fillText(glyph, px, px);
	});
}

/** A soft round light `px` in radius, for fire, mist and glows; `core` is how far out from
 *  the middle it stays white-hot, 0 for none. */
function blobSprite(color: string, px: number, core = 0.25): HTMLCanvasElement {
	return sprite(px * 2, (g) => {
		const grad = g.createRadialGradient(px, px, 0, px, px, px);
		if (core) grad.addColorStop(0, '#fff');
		grad.addColorStop(core, color);
		grad.addColorStop(1, 'transparent');
		g.fillStyle = grad;
		g.fillRect(0, 0, px * 2, px * 2);
	});
}

/** `img` centred on `at`, `size` from its middle to its edge, turned by `angle`. */
function stamp(ctx: CanvasRenderingContext2D, img: CanvasImageSource, at: Point, size: number, alpha: number, angle = 0) {
	if (alpha < UNSEEN) return;
	ctx.globalAlpha = alpha;
	if (!angle) {
		ctx.drawImage(img, at.x - size, at.y - size, size * 2, size * 2);
		return;
	}
	ctx.save();
	ctx.translate(at.x, at.y);
	ctx.rotate(angle);
	ctx.drawImage(img, -size, -size, size * 2, size * 2);
	ctx.restore();
}

/** A bolt as it plays: its strokes as `[at, strength, decay]`, the share of its brightness it
 *  keeps between strokes, and when it fades out. */
interface Strike {
	traced: Traced[];
	width: number;
	strokes: [number, number, number][];
	rest: number;
	fadeAt: number;
	fadeMs: number;
}

// 0 before its first stroke, then its resting glow plus whichever stroke is flaring.
function strength(strike: Strike, u: number): number {
	if (u < strike.strokes[0][0]) return 0;
	let flare = 0;
	for (const [at, k, decay] of strike.strokes) flare = Math.max(flare, k * pulse(u - at, decay));
	return (strike.rest + (1 - strike.rest) * flare) * fadeFrom(u, strike.fadeAt, strike.fadeMs);
}

interface Spark {
	x: number;
	y: number;
	vx: number;
	vy: number;
	born: number;
	life: number;
}
const SPARK_STEPS = 6;

/**
 * Streaks of light under `gravity` (a negative one rises, for embers), keeping only `drag`
 * of their speed each second. Stroked in batches by alpha step — hundreds of streaks, a
 * handful of strokes — the first half of a streak's life white-hot, the rest cooled to
 * `color`.
 */
function sparkField(rand: Rand, color: string, gravity: number, drag = 0.25, width = 1.8) {
	let sparks: Spark[] = [];
	return {
		/** `count` streaks from `at`, up to `speed` fast, headed between `from` and `to`
		 *  (radians), each living from `life` to about two and a half times that. */
		burst(at: Point, count: number, speed: number, u: number, from = -Math.PI * 0.95, to = -Math.PI * 0.05, life = 450) {
			for (let i = 0; i < count; i++) {
				const a = from + rand() * (to - from);
				const v = speed * (0.35 + rand() * 0.65);
				sparks.push({ x: at.x, y: at.y, vx: Math.cos(a) * v, vy: Math.sin(a) * v, born: u, life: life * (1 + rand() * 1.45) });
			}
		},
		draw(ctx: CanvasRenderingContext2D, u: number, dt: number, alpha = 1) {
			sparks = sparks.filter((p) => u - p.born < p.life);
			if (!sparks.length || alpha <= 0) return;
			const keep = Math.pow(drag, dt);
			const batches = Array.from({ length: SPARK_STEPS }, () => new Path2D());
			for (const p of sparks) {
				p.vx *= keep;
				p.vy = p.vy * keep + gravity * dt;
				p.x += p.vx * dt;
				p.y += p.vy * dt;
				const batch = batches[Math.min(SPARK_STEPS - 1, Math.floor((1 - (u - p.born) / p.life) * SPARK_STEPS))];
				batch.moveTo(p.x, p.y);
				batch.lineTo(p.x - p.vx * 0.03, p.y - p.vy * 0.03);
			}
			ctx.lineWidth = width;
			batches.forEach((batch, i) => {
				ctx.globalAlpha = (alpha * (i + 0.5)) / SPARK_STEPS;
				ctx.strokeStyle = i >= SPARK_STEPS / 2 ? '#fff' : color;
				ctx.stroke(batch);
			});
		},
	};
}

/**
 * The bolt signature: a storm that builds onto the centre. A stepped leader feels its way
 * down and its return stroke lights it; two bolts land round it; then the main hit, heavier
 * and more forked, lands just before the hit-stop, so the frozen frame is the storm at full
 * strength. The charge stays through the title card: arcs crawl round the title, the main
 * channel flickers again, and two distant strikes fall behind it.
 *
 * Only thin lines flicker: the bolts, the arcs, the stage's speed lines. The light cast on
 * the scene rises once and fades slowly, and the glow round the title breathes slowly and
 * faintly, because a large area pulsing in step with the strikes would be a run of
 * full-screen flashes.
 */
function boltScene({ w, h, centre: target, span, color, rand, peak, clear }: Stage): Scene {
	const LEADER = 110;
	const HIT = 370;
	const sky = (spread: number) => ({ x: target.x + (rand() - 0.5) * w * spread, y: 0 });
	const near = () => ({ x: target.x + (rand() - 0.5) * w * 0.32, y: target.y + (rand() - 0.5) * h * 0.24 });
	const storm: Strike[] = [
		{ traced: trace(bolt(sky(0.4), target, w, h, rand)), width: 1, strokes: [[LEADER, 0.8, 60], [230, 0.55, 45]], rest: 0.25, fadeAt: peak, fadeMs: 260 },
		{ traced: trace(bolt(sky(0.9), near(), w, h, rand)), width: 0.65, strokes: [[180, 0.7, 50]], rest: 0.2, fadeAt: peak, fadeMs: 200 },
		{ traced: trace(bolt(sky(0.9), near(), w, h, rand)), width: 0.65, strokes: [[300, 0.75, 50]], rest: 0.2, fadeAt: peak, fadeMs: 200 },
		{
			traced: trace(bolt(sky(0.12), target, w, h, rand, 0.3)),
			width: 1.8,
			strokes: [[HIT, 1, 110], [peak + 140, 0.5, 60], [peak + 330, 0.35, 50]],
			rest: 0.3,
			fadeAt: peak,
			fadeMs: 900,
		},
	];
	// Far off on either side, behind the title card, with no glow left between their strokes.
	const distant = [-1, 1].map((side, i) => {
		const end = { x: target.x + side * w * (0.25 + rand() * 0.2), y: h * (0.3 + rand() * 0.3) };
		const at = peak + 380 + i * 620 + rand() * 300;
		const strike: Strike = {
			traced: trace(bolt({ x: end.x + (rand() - 0.5) * w * 0.1, y: 0 }, end, w, h, rand)),
			width: 0.55,
			strokes: [[at, 0.75, 60], [at + 110, 0.45, 50]],
			rest: 0,
			fadeAt: clear,
			fadeMs: FADE,
		};
		return { strike, end };
	});
	// The arcs crawl round an ellipse a little wider than the title.
	const rx = Math.min(w * 0.42, 330);
	const ry = Math.min(h * 0.14, 110);
	const onRing = (a: number) => ({ x: target.x + Math.cos(a) * rx, y: target.y + Math.sin(a) * ry });
	const arcs: { traced: Traced[]; born: number; life: number }[] = [];
	const sparks = sparkField(rand, color, 1500);
	const sparkCount = Math.round(Math.min(110, 40 + (w * h) / 18000));
	let bursts = 0;

	return {
		draw(ctx, u, dt, hold) {
			if (u < 0) return;
			ctx.globalCompositeOperation = 'lighter';
			if (u < LEADER) {
				ctx.save();
				ctx.beginPath();
				ctx.rect(0, 0, w, target.y * (u / LEADER));
				ctx.clip();
				strokeLight(ctx, storm[0].traced, color, 1, 0.3);
				ctx.restore();
				return;
			}
			if (bursts === 0) {
				sparks.burst(target, sparkCount, 620, u);
				bursts = 1;
			}
			if (bursts === 1 && u >= HIT) {
				sparks.burst(target, Math.round(sparkCount * 1.6), 950, u);
				bursts = 2;
			}

			glow(ctx, target, span * 0.32, 0.55 * (0.35 + 0.65 * pulse(u - LEADER, 420)) * fadeFrom(u, peak, 260), color);
			// The charge left round the title, breathing about once a second.
			if (u >= peak) glow(ctx, target, rx * 1.3, (0.11 + 0.04 * Math.sin((u - peak) / 160)) * hold, color);

			for (const strike of storm) strokeLight(ctx, strike.traced, color, strike.width, strength(strike, u));
			for (const { strike, end } of distant) {
				const lit = strength(strike, u);
				strokeLight(ctx, strike.traced, color, strike.width, lit);
				glow(ctx, end, 70, 0.3 * lit, color);
			}

			if (u >= peak && u < clear && rand() < dt * 18) {
				const a = rand() * Math.PI * 2;
				const gap = (0.3 + rand() * 0.6) * (rand() < 0.5 ? -1 : 1);
				const points = displace(onRing(a), onRing(a + gap), 0.5, 4, rand);
				arcs.push({ traced: trace([{ points, width: 0.4 }]), born: u, life: 80 + rand() * 120 });
			}
			for (const arc of arcs) {
				const left = 1 - (u - arc.born) / arc.life;
				if (left > 0) strokeLight(ctx, arc.traced, color, 1, left * (0.6 + 0.4 * rand()) * hold);
			}

			sparks.draw(ctx, u, dt);
		},
		impact(ctx) {
			for (const strike of storm) {
				for (const t of strike.traced) {
					ctx.lineWidth = 6 * t.width * strike.width;
					ctx.stroke(t.path);
				}
			}
		},
	};
}

/**
 * The blaze signature: a wall of fire climbs from the bottom of the screen with embers
 * streaming ahead of it, and a flare bursts at the centre — the beast's roar — just before
 * the hit-stop. Through the title card the fire burns low along the bottom and embers keep
 * rising.
 */
function blazeScene({ w, h, centre, span, room, color, rand, peak, clear }: Stage): Scene {
	const flame = blobSprite(color, 48);
	const embers = sparkField(rand, color, -320, 0.7, 1.5);
	let flames: { x: number; y: number; vx: number; vy: number; born: number; life: number; size: number; sway: number }[] = [];
	return {
		draw(ctx, u, dt, hold) {
			if (u < 0) return;
			ctx.globalCompositeOperation = 'lighter';
			const after = u >= peak;
			const rise = ramp(u, 0, 380);
			// The wall climbs as it builds; past the peak it settles to licks along the bottom.
			const reach = after ? 0.25 : 0.25 + 0.75 * rise;
			for (let n = Math.floor((after ? 110 * hold : 320) * room * dt + rand()); n > 0; n--) {
				flames.push({
					x: rand() * w,
					y: h + 30,
					vx: (rand() - 0.5) * 40,
					vy: -(220 + rand() * 520) * reach,
					born: u,
					life: 520 + rand() * 420,
					size: (34 + rand() * 46) * (after ? 0.8 : 1),
					sway: rand() * Math.PI * 2,
				});
			}

			// The heat, filled only up to where its gradient has faded out.
			const top = h * (0.65 - 0.4 * reach);
			const heat = ctx.createLinearGradient(0, h, 0, top);
			heat.addColorStop(0, color);
			heat.addColorStop(1, 'transparent');
			ctx.globalAlpha = after ? 0.3 * hold : 0.25 + 0.35 * rise;
			ctx.fillStyle = heat;
			ctx.fillRect(0, top, w, h - top);

			flames = flames.filter((f) => u - f.born < f.life);
			for (const f of flames) {
				const age = (u - f.born) / f.life;
				f.x += (f.vx + Math.sin(u / 140 + f.sway) * 50) * dt;
				f.y += f.vy * dt;
				// Swells, then burns down to nothing.
				stamp(ctx, flame, f, f.size * Math.sin(Math.PI * (0.15 + 0.85 * age)), 0.75 * (1 - age) * (after ? hold : 1));
			}

			glow(ctx, centre, span * (0.25 + 0.3 * ramp(u, 300, 100)), 0.55 * ramp(u, 280, 100) * fadeFrom(u, peak, 300), color);

			if (u < clear && rand() < dt * (after ? 35 * hold : 70) * room) {
				embers.burst({ x: rand() * w, y: h - rand() * h * 0.35 * reach }, 1, 180, u, -Math.PI * 0.62, -Math.PI * 0.38, 900);
			}
			embers.draw(ctx, u, dt, after ? hold : 1);
		},
		impact(ctx) {
			ctx.beginPath();
			for (const f of flames) {
				ctx.moveTo(f.x + f.size * 0.4, f.y);
				ctx.arc(f.x, f.y, f.size * 0.4, 0, Math.PI * 2);
			}
			ctx.fill();
		},
	};
}

/**
 * The portal signature: light spirals into a vortex while rings of runes counter-rotate
 * round a dark heart, then the iris opens and the light floods out into the flash. Through
 * the title card the rings turn slowly round it, stars twinkle, and the last of the light
 * drifts back out.
 */
function portalScene({ w, h, centre, span, room, color, glyph, rand, peak }: Stage): Scene {
	const far = Math.hypot(w, h) * 0.55;
	const star = glyphSprite(glyph, color, 48);
	const motes = Array.from({ length: Math.round(90 * room) }, () => ({
		angle: rand() * Math.PI * 2,
		from: far * (0.6 + rand() * 0.5),
		delay: rand() * 160,
		size: 5 + rand() * 9,
		spin: 3 + rand() * 3,
	}));
	const twinkles = Array.from({ length: 14 }, () => {
		const a = rand() * Math.PI * 2;
		const r = span * (0.32 + rand() * 0.22);
		return { x: centre.x + Math.cos(a) * r * 1.3, y: centre.y + Math.sin(a) * r * 0.8, phase: rand() * Math.PI * 2, size: 8 + rand() * 10 };
	});
	const RINGS = [0.17, 0.25, 0.33];
	const ring = (r: number) => [{ path: circle(centre, r), width: 0.5 }];
	// Dashed so the runes show the turn; the dash offset is the rotation.
	const runes = (ctx: CanvasRenderingContext2D, r: number, i: number, turn: number, alpha: number) => {
		ctx.setLineDash([span * 0.02 * (i + 1), span * 0.012]);
		ctx.lineDashOffset = (i % 2 ? -1 : 1) * turn;
		strokeLight(ctx, ring(r), color, 1, alpha);
		ctx.setLineDash([]);
	};

	return {
		draw(ctx, u, _, hold) {
			if (u < 0) return;
			const open = cubicOut(ramp(u, 0, 260));
			const turn = Math.min(u, peak) * 0.35 + Math.max(0, u - peak) * 0.06;

			if (u < peak) {
				// The dark heart, drawn over before the light is added round it.
				ctx.globalCompositeOperation = 'source-over';
				ctx.globalAlpha = 0.85 * open;
				ctx.fillStyle = '#000';
				ctx.fill(circle(centre, span * 0.11 * open));
			}
			ctx.globalCompositeOperation = 'lighter';
			const near = fadeFrom(u, peak, 250);
			strokeLight(ctx, ring(span * 0.11 * open), color, 1.6, 0.9 * open * near);
			RINGS.forEach((share, i) => runes(ctx, span * share * (0.4 + 0.6 * open), i, turn, 0.9 * open * near));
			// Round the title, wider, through the hold.
			if (u >= peak) RINGS.forEach((share, i) => runes(ctx, span * share * 1.45, i, turn, 0.3 * hold * ramp(u, peak, 300)));

			for (const m of motes) {
				if (u < peak) {
					const p = ramp(u, m.delay, 380 - m.delay * 0.5);
					if (p <= 0 || p >= 1) continue;
					const pulled = p * p;
					const r = m.from * (1 - pulled) + span * 0.1 * pulled;
					const a = m.angle + pulled * m.spin;
					stamp(ctx, star, { x: centre.x + Math.cos(a) * r, y: centre.y + Math.sin(a) * r }, m.size * (1 - 0.5 * pulled), Math.min(1, p * 5));
				} else if (m.spin > 4.5) {
					// Half of them drift back out, slowly, as the portal settles.
					const r = span * 0.12 + (u - peak) * 0.03 * m.spin;
					const a = m.angle - (u - peak) * 0.0006 * m.spin;
					stamp(ctx, star, { x: centre.x + Math.cos(a) * r, y: centre.y + Math.sin(a) * r }, m.size * 0.7, 0.6 * fadeFrom(u, peak, 1400) * hold);
				}
			}

			const iris = ramp(u, 300, 100);
			if (u < peak && iris > 0) glow(ctx, centre, span * (0.1 + 0.45 * iris * iris), 0.85 * iris, color);

			if (u >= peak) {
				const shown = hold * ramp(u, peak + 100, 400);
				for (const t of twinkles) stamp(ctx, star, t, t.size, shown * (0.5 + 0.5 * Math.sin((u - peak) / 260 + t.phase)));
			}
		},
		impact(ctx) {
			ctx.lineWidth = 3;
			for (const share of [0.11, ...RINGS]) ctx.stroke(circle(centre, span * share));
		},
	};
}

/**
 * The glitch signature: the signal breaks up. Scanlines, a refresh beam sweeping the screen,
 * data raining down its columns, and tears and blocks of corrupt colour that grow as the
 * strike nears. Through the title card the rain thins and the signal stutters now and then;
 * the card itself arrives as a broken signal (`WorldReveal.svelte`).
 *
 * The corruption is redrawn every 50ms rather than every frame — a stutter, not a strobe —
 * and every tear and block is small or part-width, so it never lights a large area at once.
 */
function glitchScene({ w, h, room, color, glyph, rand, peak }: Stage): Scene {
	const bit = glyphSprite(glyph, color, 32);
	const scanlines = new Path2D();
	for (let y = 0; y < h; y += 4) {
		scanlines.moveTo(0, y);
		scanlines.lineTo(w, y);
	}
	const COLUMN = 26;
	const columns = Array.from({ length: Math.ceil(w / COLUMN) }, () => ({ speed: 260 + rand() * 520, offset: rand() * h, length: 3 + Math.floor(rand() * 5) }));
	const bursts = [300, 900, 1500].map((at) => peak + at + rand() * 120);
	let step = -1;
	let shards: { x: number; y: number; w: number; h: number; ink: string }[] = [];

	const corrupt = (amount: number) => {
		shards = Array.from({ length: Math.round((3 + 9 * amount) * Math.min(room, 1.6)) }, () => {
			const tear = rand() < 0.4;
			return {
				x: rand() * w + (rand() - 0.5) * 120 * amount,
				y: rand() * h,
				w: tear ? w * (0.15 + rand() * 0.3) : 8 + rand() * 36,
				h: tear ? 2 + rand() * 10 : 6 + rand() * 24,
				// The world's colour, and the cyan and magenta of a split signal.
				ink: [color, '#0ff', '#f0f'][Math.floor(rand() * 3)],
			};
		});
	};

	return {
		draw(ctx, u, _, hold) {
			if (u < 0) return;
			ctx.globalCompositeOperation = 'lighter';
			const after = u >= peak;
			const build = ramp(u, 0, 400);

			ctx.globalAlpha = 0.1 * (after ? hold : 0.4 + 0.6 * build);
			ctx.strokeStyle = color;
			ctx.lineWidth = 1;
			ctx.stroke(scanlines);

			const rain = after ? 0.35 * hold : 0.85 * build;
			if (rain > 0) {
				columns.forEach((c, i) => {
					const head = ((c.offset + (u * c.speed) / 1000) % (h + 200)) - 100;
					for (let j = 0; j < c.length; j++) {
						ctx.globalAlpha = rain * (1 - j / c.length);
						ctx.drawImage(bit, i * COLUMN + 4, head - j * 22, 18, 18);
					}
				});
			}

			if (!after) {
				// The refresh beam: down the screen, then a faster pass back up.
				const y = u < 300 ? h * cubicInOut(u / 300) : h * fadeFrom(u, 300, 90);
				const band = ctx.createLinearGradient(0, y - 30, 0, y + 30);
				band.addColorStop(0, 'transparent');
				band.addColorStop(0.5, color);
				band.addColorStop(1, 'transparent');
				ctx.globalAlpha = 0.55;
				ctx.fillStyle = band;
				ctx.fillRect(0, y - 30, w, 60);
			}

			const stutter = bursts.some((at) => u >= at && u < at + 180);
			const amount = after ? (stutter ? 0.6 * hold : 0) : build * build;
			if (amount > 0) {
				const now = Math.floor(u / 50);
				if (now !== step) {
					step = now;
					corrupt(amount);
				}
				ctx.globalAlpha = 0.3;
				for (const s of shards) {
					ctx.fillStyle = s.ink;
					ctx.fillRect(s.x, s.y, s.w, s.h);
				}
			}
		},
		impact(ctx) {
			for (const s of shards) ctx.fillRect(s.x, s.y, s.w, s.h);
		},
	};
}

/**
 * The spiral signature: four arms of light wind in towards the centre, faster and faster,
 * pulling question marks in along them — then the twist: the spin snaps the other way just
 * before the hit-stop. Through the title card the arms turn slowly behind it and the
 * questions drift back out.
 */
function spiralScene({ w, h, centre, span, color, glyph, rand, peak }: Stage): Scene {
	const ARMS = 4;
	// A logarithmic spiral, growing this much per radian, from near the centre out past the corners.
	const GROWTH = 0.2;
	const winds = Math.log((Math.hypot(w, h) * 0.6) / 6) / GROWTH;
	const TWIST = 320;
	const mark = glyphSprite(glyph, color, 56);
	const marks = Array.from({ length: 20 }, () => ({
		arm: Math.floor(rand() * ARMS),
		along: 0.45 + rand() * 0.5,
		size: 16 + rand() * 22,
		spin: (rand() - 0.5) * 5,
		delay: rand() * 120,
	}));
	let phase = 0;
	let shown: Traced[] = [];

	const at = (arm: number, along: number, zoom: number) => {
		const theta = along * winds;
		const r = 6 * Math.exp(GROWTH * theta) * zoom;
		const a = theta + phase + (arm * 2 * Math.PI) / ARMS;
		return { x: centre.x + Math.cos(a) * r, y: centre.y + Math.sin(a) * r };
	};

	return {
		draw(ctx, u, dt, hold) {
			if (u < 0) return;
			ctx.globalCompositeOperation = 'lighter';
			const after = u >= peak;
			// Winding up, the twist, then a slow turn behind the title. In radians a second.
			phase += (after ? 0.6 : u < TWIST ? 2 + 12 * (u / TWIST) : -16) * dt;
			const zoom = after ? 1 : 1 + 0.5 * ramp(u, 0, 400) ** 2;
			shown = trace(
				Array.from({ length: ARMS }, (_, arm) => ({ points: Array.from({ length: 81 }, (_, i) => at(arm, i / 80, zoom)), width: 0.55 })),
			);
			strokeLight(ctx, shown, color, 1, after ? 0.25 * hold : 0.75 * ramp(u, 0, 160));
			glow(ctx, centre, span * 0.22, (0.5 * ramp(u, 100, 300) + 0.4 * pulse(u - TWIST, 80)) * fadeFrom(u, peak, 200), color);

			for (const m of marks) {
				const pull = ramp(u, m.delay, 400 - m.delay);
				const along = after ? m.along * 0.2 + ramp(u, peak, 1600) * 0.7 : m.along * (1 - 0.8 * pull * pull);
				const alpha = after ? 0.7 * hold * fadeFrom(u, peak + 900, 700) : Math.min(1, pull * 4);
				stamp(ctx, mark, at(m.arm, along, zoom), m.size * (0.35 + along), alpha, m.spin * along + phase * 0.2);
			}
		},
		impact(ctx) {
			ctx.lineWidth = 4;
			for (const t of shown) ctx.stroke(t.path);
		},
	};
}

/**
 * The spotlight signature: the stage goes dark, a spotlight sweeps across it with dust
 * hanging in its beam, a second joins from the other side, and both land on the centre as
 * stars burst. Through the title card the two beams hold on it, swaying a little, stars
 * twinkle round it and confetti falls.
 */
function spotlightScene({ w, h, centre, span, room, color, glyph, rand, peak, clear }: Stage): Scene {
	const LAND = 360;
	const star = glyphSprite(glyph, color, 48);
	// The radius of the pool of light where a beam lands.
	const pool = span * 0.2;
	const lamps = [
		{ x: -w * 0.08, y: -h * 0.1 },
		{ x: w * 1.08, y: -h * 0.1 },
	];
	const dust = Array.from({ length: Math.round(110 * room) }, () => ({ x: rand() * w, y: rand() * h, vx: (rand() - 0.5) * 16, vy: (rand() - 0.5) * 12, size: 0.8 + rand() * 1.6 }));
	const burst = Array.from({ length: 16 }, (_, i) => {
		const a = (i / 16) * Math.PI * 2 + rand() * 0.3;
		const v = span * (0.5 + rand() * 0.5);
		return { vx: Math.cos(a) * v, vy: Math.sin(a) * v, size: 10 + rand() * 12, spin: (rand() - 0.5) * 6 };
	});
	const twinkles = Array.from({ length: 12 }, () => {
		const a = rand() * Math.PI * 2;
		const r = span * (0.3 + rand() * 0.2);
		return { x: centre.x + Math.cos(a) * r * 1.35, y: centre.y + Math.sin(a) * r * 0.75, phase: rand() * Math.PI * 2, size: 8 + rand() * 9 };
	});
	// Paper in the world's colour, white and gold.
	const INKS = [color, '#fff', '#ffd54a'];
	let confetti: { x: number; y: number; vy: number; w: number; h: number; turn: number; spin: number; wobble: number; ink: string }[] = [];
	const drop = (count: number, top: number) => {
		for (let i = 0; i < count; i++) {
			confetti.push({
				x: rand() * w,
				y: top - rand() * 80,
				vy: 90 + rand() * 130,
				w: 5 + rand() * 4,
				h: 9 + rand() * 5,
				turn: rand() * Math.PI * 2,
				spin: (rand() - 0.5) * 8,
				wobble: rand() * Math.PI * 2,
				ink: INKS[Math.floor(rand() * INKS.length)],
			});
		}
	};
	let dropped = false;

	// Where a beam lands: swept in from its own side, then held on the centre, swaying a little.
	const landing = (i: number, u: number) => {
		const p = cubicInOut(i === 0 ? ramp(u, 0, 300) : ramp(u, 150, 210));
		const sway = u >= peak ? Math.sin((u - peak) / 420 + i * 2) * span * 0.04 : 0;
		return { x: centre.x + (i === 0 ? -1 : 1) * w * 0.36 * (1 - p) + sway, y: centre.y + span * 0.08 };
	};
	// A cone from the lamp, widening to the pool's width where it lands, and the pool itself.
	const beam = (lamp: Point, at: Point) => {
		const len = Math.hypot(at.x - lamp.x, at.y - lamp.y) || 1;
		const nx = (-(at.y - lamp.y) / len) * pool;
		const ny = ((at.x - lamp.x) / len) * pool;
		const path = new Path2D();
		path.moveTo(lamp.x - nx * 0.08, lamp.y - ny * 0.08);
		path.lineTo(at.x - nx, at.y - ny);
		path.lineTo(at.x + nx, at.y + ny);
		path.lineTo(lamp.x + nx * 0.08, lamp.y + ny * 0.08);
		path.closePath();
		path.ellipse(at.x, at.y, pool, pool * 0.32, 0, 0, Math.PI * 2);
		return path;
	};
	// Whether `p` lies in that beam: tested here rather than clipping the canvas to the beams,
	// which every frame would cost a screen-sized mask of a moving shape.
	const lights = (p: Point, lamp: Point, at: Point) => {
		const dx = at.x - lamp.x;
		const dy = at.y - lamp.y;
		const len2 = dx * dx + dy * dy || 1;
		const t = ((p.x - lamp.x) * dx + (p.y - lamp.y) * dy) / len2;
		if (t >= 0 && t <= 1 && Math.abs((p.x - lamp.x) * dy - (p.y - lamp.y) * dx) / Math.sqrt(len2) <= pool * (0.08 + 0.92 * t)) return true;
		const ex = (p.x - at.x) / pool;
		const ey = (p.y - at.y) / (pool * 0.32);
		return ex * ex + ey * ey <= 1;
	};

	return {
		draw(ctx, u, dt, hold) {
			if (u < 0) return;
			const after = u >= peak;
			if (!after) darken(ctx, w, h, 0.6 * cubicOut(ramp(u, 0, 140)));
			ctx.globalCompositeOperation = 'lighter';

			const lit: { lamp: Point; at: Point }[] = [];
			lamps.forEach((lamp, i) => {
				const on = ramp(u, i === 0 ? 0 : 150, 60) * (after ? 0.75 * hold : 1);
				if (on <= 0) return;
				const at = landing(i, u);
				const fill = ctx.createLinearGradient(lamp.x, lamp.y, at.x, at.y);
				fill.addColorStop(0, '#fff');
				fill.addColorStop(0.35, color);
				fill.addColorStop(1, color);
				ctx.globalAlpha = 0.22 * on;
				ctx.fillStyle = fill;
				ctx.fill(beam(lamp, at));
				glow(ctx, at, pool * 1.3, 0.3 * on, color, false);
				lit.push({ lamp, at });
			});

			// Dust, seen only where a beam passes through it.
			ctx.globalAlpha = 0.8 * (after ? hold : 1);
			ctx.fillStyle = '#fff';
			ctx.beginPath();
			for (const d of dust) {
				d.x = (d.x + d.vx * dt + w) % w;
				d.y = (d.y + d.vy * dt + h) % h;
				if (lit.some((b) => lights(d, b.lamp, b.at))) ctx.rect(d.x, d.y, d.size, d.size);
			}
			ctx.fill();

			const landed = landing(0, u);
			glow(ctx, landed, span * 0.35, 0.5 * pulse(u - LAND, 160), color);
			const flown = (u - LAND) / 1000;
			const shown = fadeFrom(u, LAND + 300, 700);
			if (flown > 0 && shown > 0) {
				const out = (1 - Math.exp(-flown * 3)) / 3;
				for (const s of burst) stamp(ctx, star, { x: landed.x + s.vx * out, y: landed.y + s.vy * out }, s.size, shown, s.spin * flown);
			}
			if (!after) return;

			const twinkling = hold * ramp(u, peak + 200, 400);
			for (const t of twinkles) stamp(ctx, star, t, t.size, twinkling * (0.5 + 0.5 * Math.sin((u - peak) / 280 + t.phase)));

			if (!dropped) {
				drop(Math.round(70 * room), 0);
				dropped = true;
			}
			if (u < clear && rand() < dt * 25 * room) drop(1, -20);
			confetti = confetti.filter((c) => c.y < h + 40);
			ctx.globalCompositeOperation = 'source-over';
			ctx.globalAlpha = hold;
			for (const c of confetti) {
				c.y += c.vy * dt;
				c.x += Math.sin(u / 300 + c.wobble) * 30 * dt;
				c.turn += c.spin * dt;
				ctx.save();
				ctx.translate(c.x, c.y);
				ctx.rotate(c.turn);
				// Flutters: the paper turns edge-on and back as it falls.
				ctx.scale(1, Math.abs(Math.cos(u / 180 + c.wobble)) + 0.05);
				ctx.fillStyle = c.ink;
				ctx.fillRect(-c.w / 2, -c.h / 2, c.w, c.h);
				ctx.restore();
			}
		},
		impact(ctx) {
			lamps.forEach((lamp, i) => ctx.fill(beam(lamp, landing(i, peak))));
		},
	};
}

/**
 * A katana, its guard at the origin and its blade running down +y to the tip at `length`,
 * curving back a little towards the spine the way a katana's does. Built once as paths, so
 * a frame only fills and strokes them.
 */
function katana(length: number) {
	const W = length * 0.022; // half the blade's width at the guard
	const point = length * 0.93; // where the edge starts curving up into the tip
	const half = (y: number) => W * (1 - 0.3 * (y / length));
	const bend = (y: number) => length * 0.035 * (y / length) ** 2;
	const spine = (y: number) => -half(y) - bend(y);
	const edgeAt = (y: number) => half(y) - bend(y);
	const tip = { x: spine(length) + W * 0.3, y: length };
	const STEPS = 40;

	const blade = new Path2D();
	blade.moveTo(spine(0), 0);
	for (let i = 1; i <= STEPS; i++) blade.lineTo(spine((length * i) / STEPS), (length * i) / STEPS);
	blade.lineTo(tip.x, tip.y);
	blade.quadraticCurveTo(edgeAt(length), length * 0.985, edgeAt(point), point);
	for (let i = STEPS; i >= 0; i--) blade.lineTo(edgeAt((point * i) / STEPS), (point * i) / STEPS);
	blade.closePath();

	const edge = new Path2D();
	edge.moveTo(edgeAt(0), 0);
	for (let i = 1; i <= STEPS; i++) edge.lineTo(edgeAt((point * i) / STEPS), (point * i) / STEPS);
	edge.quadraticCurveTo(edgeAt(length), length * 0.985, tip.x, tip.y);

	// The temper line, the wave a katana's hardened edge shows along the steel.
	const hamon = new Path2D();
	hamon.moveTo(edgeAt(0) - W * 0.55, 0);
	for (let i = 1; i <= STEPS; i++) {
		const y = (point * i) / STEPS;
		hamon.lineTo(edgeAt(y) - W * (0.5 + 0.12 * Math.sin(i * 1.9)), y);
	}

	const grip = length * 0.27;
	const hilt = new Path2D();
	hilt.rect(-W * 0.95, -grip, W * 1.9, grip - W * 0.6);
	const wrap = new Path2D();
	for (let y = -grip + W; y < -W * 1.5; y += W * 1.8) {
		wrap.moveTo(-W * 0.95, y);
		wrap.lineTo(W * 0.95, y + W * 0.9);
		wrap.moveTo(W * 0.95, y);
		wrap.lineTo(-W * 0.95, y + W * 0.9);
	}
	const fittings = new Path2D();
	fittings.rect(-W * 1.15, 0, W * 2.3, length * 0.03);
	fittings.rect(-W * 1.05, -grip - W * 0.5, W * 2.1, W * 0.9);
	const guard = new Path2D();
	guard.ellipse(0, 0, W * 2.8, W * 1.1, 0, 0, Math.PI * 2);
	return { W, length, blade, edge, hamon, hilt, wrap, fittings, guard };
}

/**
 * The swords signature: two katanas fall spinning out of the dark, and the second slams
 * across the first into an X — a clang of sparks, and blood-red ink bursting behind them,
 * all frozen in the hit. Through the title card light runs down the blades now and then and
 * the blood drips.
 */
function swordsScene({ ctx: canvas, w, h, centre, span, room, color, rand, peak, clear }: Stage): Scene {
	const GOLD = '#c9a24a';
	const sword = katana(Math.min(h * 0.5, w * 0.62, 520));
	// Where the blades cross: a third of the way down each, just above the title.
	const cross = { x: centre.x, y: centre.y - span * 0.02 };
	const down = sword.length * 0.3;
	const TILT = 0.62;
	const pose = (side: number) => ({
		at: { x: cross.x + side * Math.sin(TILT) * down, y: cross.y - Math.cos(TILT) * down },
		angle: side * TILT,
	});
	// Each falls from above its own side, spinning down into place; the second lands on the first.
	const swords = [-1, 1].map((side, i) => ({ ...pose(side), side, from: 60 + i * 50, lands: 330 + i * 50, spin: side * (1.6 + rand() * 0.8) }));
	const CLANG = swords[1].lands;
	const sparks = sparkField(rand, '#ffd27a', 1400);
	const embers = sparkField(rand, '#ffd27a', 300, 0.5, 1.2);
	let settled = false;
	let clanged = false;
	// Polished steel, banded across the blade: dark spine, bright ridge, bright edge.
	const steel = canvas.createLinearGradient(-sword.W, 0, sword.W, 0);
	for (const [stop, ink] of [
		[0, '#2c323c'],
		[0.3, '#aab3c0'],
		[0.48, '#f3f6fa'],
		[0.56, '#7d8796'],
		[0.8, '#d9dfe8'],
		[1, '#4b5361'],
	] as const) {
		steel.addColorStop(stop, ink);
	}

	// The splash, built once round the clang: a blot of uneven lobes; spines flung out of it,
	// tapering, often with a droplet just past the point; droplets past the rim, round close in
	// and drawn out further off with their tails pointing back at the clang; and a fine mist
	// beyond. Thick blood pools dark and thin blood shows bright, so it is shaded from a dark
	// heart out to a bright rim, and it is wet — the lobes and the larger drops catch the light.
	const R = span * 0.28;
	const blood = canvas.createRadialGradient(0, 0, 0, 0, 0, R * 2.2);
	for (const [stop, ink] of [
		[0, '#2e0106'],
		[0.3, '#5c040d'],
		[0.6, '#8e0b18'],
		[1, '#b3172a'],
	] as const) {
		blood.addColorStop(stop, ink);
	}
	const polar = (a: number, d: number) => ({ x: Math.cos(a) * d, y: Math.sin(a) * d });
	const rim = Array.from({ length: 28 }, (_, i) => {
		const a = (i / 28) * Math.PI * 2 + (rand() - 0.5) * 0.12;
		const lobe = rand() < 0.3;
		return { ...polar(a, R * (lobe ? 0.78 + rand() * 0.3 : 0.48 + rand() * 0.16)), a, lobe };
	});
	const body = new Path2D();
	const spray = new Path2D();
	const bodyGloss = new Path2D();
	const sprayGloss = new Path2D();
	// A highlight on a round drop `r` across, up and to the left where the light catches it.
	const glint = (path: Path2D, p: Point, r: number) => {
		const x = p.x - r * 0.3;
		const y = p.y - r * 0.35;
		path.moveTo(x + r * 0.32, y);
		path.ellipse(x, y, r * 0.32, r * 0.2, -0.5, 0, Math.PI * 2);
	};
	const mid = (p: Point, q: Point) => ({ x: (p.x + q.x) / 2, y: (p.y + q.y) / 2 });
	const start = mid(rim[rim.length - 1], rim[0]);
	body.moveTo(start.x, start.y);
	rim.forEach((p, i) => {
		const next = mid(p, rim[(i + 1) % rim.length]);
		body.quadraticCurveTo(p.x, p.y, next.x, next.y);
		if (p.lobe) {
			bodyGloss.moveTo(p.x * 0.78 + R * 0.06, p.y * 0.78);
			bodyGloss.ellipse(p.x * 0.78, p.y * 0.78, R * 0.06, R * 0.03, p.a + Math.PI / 2, 0, Math.PI * 2);
		}
	});
	const bead = (p: Point, r: number) => {
		spray.moveTo(p.x + r, p.y);
		spray.arc(p.x, p.y, r, 0, Math.PI * 2);
		if (r >= 4) glint(sprayGloss, p, r);
	};
	for (let i = 0; i < 16; i++) {
		const a = rand() * Math.PI * 2;
		const base = R * (0.5 + rand() * 0.15);
		const reach = R * (0.35 + rand() * 0.6);
		const side = polar(a + Math.PI / 2, 1.5 + rand() * 3);
		const root = polar(a, base);
		const bend = polar(a, base + reach * 0.5);
		const point = polar(a, base + reach);
		body.moveTo(root.x + side.x, root.y + side.y);
		body.quadraticCurveTo(bend.x + side.x * 0.4, bend.y + side.y * 0.4, point.x, point.y);
		body.quadraticCurveTo(bend.x - side.x * 0.4, bend.y - side.y * 0.4, root.x - side.x, root.y - side.y);
		body.closePath();
		if (rand() < 0.6) bead(polar(a, base + reach + 6 + rand() * 14), 1.5 + rand() * 3);
	}
	for (let i = 0; i < 30; i++) {
		const a = rand() * Math.PI * 2;
		const out = rand();
		const d = R * (0.95 + out * 1.1);
		const r = (2 + rand() * 7) * (1.3 - out * 0.8);
		const p = polar(a, d);
		if (out > 0.45) {
			const tail = polar(a, d - r * (3 + rand() * 4));
			const side = polar(a + Math.PI / 2, r * 0.55);
			spray.moveTo(p.x + side.x, p.y + side.y);
			spray.lineTo(tail.x, tail.y);
			spray.lineTo(p.x - side.x, p.y - side.y);
			spray.closePath();
		}
		bead(p, r);
	}
	for (let i = 0; i < Math.round(140 * Math.min(room, 1.6)); i++) bead(polar(rand() * Math.PI * 2, R * (0.8 + rand() * 1.7)), 0.5 + rand() * 1.4);
	// It runs from the lower rim, slowly and in spurts, a bead gathering at each drip's end.
	const drips = rim
		.filter((p) => Math.abs(p.a - Math.PI / 2) < 0.7)
		.slice(0, 5)
		.map((p, i) => ({ x: p.x, y: p.y, length: span * (0.12 + rand() * 0.18), width: 3 + rand() * 2.5, at: peak + 150 + i * 180 }));
	const sheens = [
		[0, peak + 300],
		[1, peak + 700],
		[0, peak + 1100],
		[1, peak + 1500],
	] as const;

	// Where a sword is `u` into its fall: eased in, so it gathers speed as it drops.
	const fall = (s: (typeof swords)[number], u: number) => {
		const p = ramp(u, s.from, s.lands - s.from) ** 2;
		return {
			at: { x: s.at.x + s.side * w * 0.25 * (1 - p), y: s.at.y - h * 0.9 * (1 - p) },
			angle: s.angle + s.spin * (1 - p),
		};
	};
	const place = (ctx: CanvasRenderingContext2D, at: Point, angle: number) => {
		ctx.translate(at.x, at.y);
		ctx.rotate(angle);
	};
	const draw = (ctx: CanvasRenderingContext2D, at: Point, angle: number, alpha: number) => {
		ctx.save();
		place(ctx, at, angle);
		ctx.globalAlpha = alpha;
		ctx.fillStyle = steel;
		ctx.fill(sword.blade);
		ctx.strokeStyle = '#fff';
		ctx.lineWidth = 1.1;
		ctx.globalAlpha = alpha * 0.9;
		ctx.stroke(sword.edge);
		ctx.lineWidth = 1.4;
		ctx.globalAlpha = alpha * 0.3;
		ctx.stroke(sword.hamon);
		ctx.globalAlpha = alpha;
		ctx.fillStyle = '#16161b';
		ctx.fill(sword.hilt);
		ctx.strokeStyle = color;
		ctx.lineWidth = sword.W * 0.35;
		ctx.stroke(sword.wrap);
		ctx.fillStyle = GOLD;
		ctx.fill(sword.fittings);
		ctx.fillStyle = '#1b1b20';
		ctx.fill(sword.guard);
		ctx.strokeStyle = GOLD;
		ctx.lineWidth = 1.5;
		ctx.stroke(sword.guard);
		ctx.restore();
	};
	// A band of light running down the blade, kept to the steel.
	const sheen = (ctx: CanvasRenderingContext2D, at: Point, angle: number, along: number, alpha: number) => {
		if (alpha < UNSEEN) return;
		const y = along * sword.length;
		const band = sword.length * 0.06;
		ctx.save();
		place(ctx, at, angle);
		ctx.clip(sword.blade);
		const light = ctx.createLinearGradient(0, y - band, 0, y + band);
		light.addColorStop(0, 'transparent');
		light.addColorStop(0.5, '#fff');
		light.addColorStop(1, 'transparent');
		ctx.globalCompositeOperation = 'lighter';
		ctx.globalAlpha = alpha;
		ctx.fillStyle = light;
		ctx.fillRect(-sword.W * 2, y - band, sword.W * 4, band * 2);
		ctx.restore();
	};

	return {
		draw(ctx, u, dt, hold) {
			if (u < 0) return;

			// The splash, under the swords: the blot thrown out at the clang, the spray a beat
			// behind it and further.
			const thrown = cubicOut(ramp(u, CLANG, 140));
			if (thrown > 0) {
				const flung = cubicOut(ramp(u, CLANG, 220));
				const shine = (path: Path2D) => {
					ctx.globalCompositeOperation = 'lighter';
					ctx.globalAlpha = 0.35 * hold;
					ctx.fillStyle = '#ffd0d4';
					ctx.fill(path);
				};
				ctx.save();
				ctx.translate(cross.x, cross.y);
				ctx.globalCompositeOperation = 'source-over';
				ctx.globalAlpha = 0.96 * hold;
				ctx.fillStyle = blood;
				ctx.strokeStyle = blood;
				// Two spurts: a quick run, a pause while the bead gathers, then a slower one.
				const runs = drips.map((d) => {
					const p = ramp(u, d.at, 2200);
					return d.length * (0.45 * cubicOut(ramp(p, 0, 0.3)) + 0.55 * cubicInOut(ramp(p, 0.5, 0.5)));
				});
				drips.forEach((d, i) => {
					if (runs[i] <= 0) return;
					ctx.lineWidth = d.width * 0.75;
					ctx.beginPath();
					ctx.moveTo(d.x, d.y);
					ctx.lineTo(d.x, d.y + runs[i]);
					ctx.stroke();
					ctx.fill(circle({ x: d.x, y: d.y + runs[i] }, d.width));
				});
				ctx.save();
				ctx.scale(flung, flung);
				ctx.fill(spray);
				shine(sprayGloss);
				ctx.restore();
				ctx.save();
				ctx.scale(thrown, thrown);
				ctx.fill(body);
				shine(bodyGloss);
				ctx.restore();
				const beads = new Path2D();
				drips.forEach((d, i) => {
					if (runs[i] > 0) glint(beads, { x: d.x, y: d.y + runs[i] }, d.width);
				});
				shine(beads);
				ctx.restore();
			}

			for (const s of swords) {
				if (u < s.from) continue;
				const now = fall(s, u);
				if (u < s.lands) {
					// Motion trails: where it was a moment ago, fainter the further back.
					for (const [back, alpha] of [
						[36, 0.08],
						[24, 0.15],
						[12, 0.25],
					] as const) {
						const was = fall(s, u - back);
						draw(ctx, was.at, was.angle, alpha);
					}
				}
				draw(ctx, now.at, now.angle, hold);
			}

			ctx.globalCompositeOperation = 'lighter';
			// The first blade's shing as it settles, then the light running down them through the hold.
			sheen(ctx, swords[0].at, swords[0].angle, ramp(u, swords[0].lands, 260), 0.8 * Math.sin(Math.PI * ramp(u, swords[0].lands, 260)));
			for (const [i, at] of sheens) {
				const p = ramp(u, at, 450);
				sheen(ctx, swords[i].at, swords[i].angle, p, 0.7 * Math.sin(Math.PI * p) * hold);
			}

			glow(ctx, cross, span * 0.3, 0.9 * pulse(u - CLANG, 90) * fadeFrom(u, peak, 200), '#ffd27a');
			if (!settled && u >= swords[0].lands) {
				sparks.burst(swords[0].at, Math.round(12 * room), 400, u, -Math.PI, 0, 250);
				settled = true;
			}
			if (!clanged && u >= CLANG) {
				sparks.burst(cross, Math.round(80 * room), 950, u, -Math.PI, Math.PI, 350);
				clanged = true;
			}
			if (u >= peak && u < clear && rand() < dt * 12) embers.burst(cross, 1, 80, u, 0.2, Math.PI - 0.2, 700);
			sparks.draw(ctx, u, dt);
			embers.draw(ctx, u, dt, hold);
		},
		impact(ctx) {
			for (const s of swords) {
				ctx.save();
				place(ctx, s.at, s.angle);
				ctx.fill(sword.blade);
				ctx.fill(sword.hilt);
				ctx.fill(sword.guard);
				ctx.restore();
			}
		},
	};
}

/**
 * The lights-out signature, soft and slow: the dark comes down, and in it a great pair of
 * eyes opens above where the title will land. They look one way, then the other, blink, and
 * narrow as the colour blooms. Then they stay, watching over the title card, blink once
 * more, and close as the stage clears, while a few bats flutter lazily out of the dark
 * round them and mist drifts along the bottom.
 */
function lightsOutScene({ ctx: canvas, w, h, centre, span, room, color, rand, peak, clear }: Stage): Scene {
	const gaze = { x: centre.x, y: centre.y - span * 0.19 };
	const across = span * 0.09;
	const gap = span * 0.15;
	const body = new Path2D(BAT.body);
	const wing = new Path2D(BAT.wing);
	const [UP, DOWN] = BAT.beat.map((deg) => (deg * Math.PI) / 180);
	const mist = blobSprite(color, 64, 0);
	const BLINKS = [430, peak + 750];
	const flock = Math.round(8 * Math.min(room, 1.6));
	const bats = Array.from({ length: flock }, (_, i) => {
		const a = (i / flock) * Math.PI * 2 + rand() * 0.5;
		return {
			from: { x: gaze.x + Math.cos(a) * span * 0.18, y: gaze.y + Math.sin(a) * span * 0.1 },
			a,
			speed: 45 + rand() * 70,
			at: peak + 60 + rand() * 700,
			size: 14 + rand() * 14,
			flap: rand() * Math.PI * 2,
			curl: (rand() - 0.5) * 0.8,
		};
	});
	const wisps = Array.from({ length: 7 }, () => ({ x: rand() * w, y: h * (0.82 + rand() * 0.2), size: span * (0.25 + rand() * 0.2), drift: (rand() - 0.5) * 20 }));
	// The iris, drawn about each eye's own centre, so one gradient serves both.
	const iris = canvas.createRadialGradient(0, 0, 0, 0, 0, across);
	iris.addColorStop(0, '#fff');
	iris.addColorStop(0.35, color);
	iris.addColorStop(1, '#1a1540');

	// How open the eyes are: slowly open, a narrowing as the colour blooms, the blinks, and
	// shut as the stage clears.
	const openness = (u: number) => {
		let open = 0.85 * cubicInOut(ramp(u, -150, 400)) - 0.2 * ramp(u, peak - 80, 80) + 0.15 * ramp(u, peak + 300, 900);
		for (const at of BLINKS) {
			const blink = Math.abs(u - at) / 60;
			if (blink < 1) open *= blink;
		}
		return open * fadeFrom(u, clear, 350);
	};
	// Where they look, from -1 (left) to 1 (right): one way, the other, back, then drifting.
	const look = (u: number) => {
		if (u >= peak) return 0.25 * Math.sin((u - peak) / 700);
		return -cubicInOut(ramp(u, 250, 80)) + 2 * cubicInOut(ramp(u, 330, 80)) - cubicInOut(ramp(u, 410, 60));
	};
	const eye = (ctx: CanvasRenderingContext2D, x: number, side: number, open: number, lit: number, shift: number) => {
		const tall = across * 0.5 * open;
		ctx.save();
		ctx.translate(x, gaze.y);
		ctx.rotate(side * 0.18);
		const lids = new Path2D();
		lids.moveTo(-across, 0);
		lids.quadraticCurveTo(0, -tall * 2, across, 0);
		lids.quadraticCurveTo(0, tall * 1.6, -across, 0);
		ctx.globalCompositeOperation = 'source-over';
		ctx.globalAlpha = lit;
		ctx.fillStyle = iris;
		ctx.fill(lids);
		// A slit of a pupil, kept inside the lids as it looks about.
		ctx.clip(lids);
		ctx.fillStyle = '#000';
		ctx.beginPath();
		ctx.ellipse(shift * across * 0.4, 0, across * 0.12, across * 0.5, 0, 0, Math.PI * 2);
		ctx.fill();
		ctx.restore();
	};

	// A bat `size` across at half its span, its wings `beat` (radians) through their stroke.
	const fly = (ctx: CanvasRenderingContext2D, at: Point, size: number, beat: number, alpha: number) => {
		if (alpha < UNSEEN) return;
		const angle = DOWN + (UP - DOWN) * (0.5 + 0.5 * Math.sin(beat));
		stamp(ctx, mist, at, size * 1.3, 0.3 * alpha);
		ctx.save();
		ctx.translate(at.x, at.y);
		ctx.scale(size / 50, size / 50);
		ctx.translate(-50, -30);
		ctx.globalAlpha = alpha;
		ctx.fillStyle = color;
		ctx.fill(body);
		for (const mirrored of [false, true]) {
			ctx.save();
			if (mirrored) {
				ctx.translate(100, 0);
				ctx.scale(-1, 1);
			}
			ctx.translate(BAT.shoulder.x, BAT.shoulder.y);
			ctx.rotate(angle);
			ctx.translate(-BAT.shoulder.x, -BAT.shoulder.y);
			ctx.fill(wing);
			ctx.restore();
		}
		ctx.restore();
	};

	return {
		draw(ctx, u, _, hold) {
			// The dark comes down over the anticipation beat, and eases off for the title card.
			darken(ctx, w, h, (0.8 * cubicOut(ramp(u, -380, 300)) - 0.4 * ramp(u, peak, 400)) * hold);

			const open = openness(u);
			if (open > 0) {
				const lit = (0.4 + 0.6 * ramp(u, -150, 500)) * hold;
				ctx.globalCompositeOperation = 'lighter';
				const breathe = 0.85 + 0.15 * Math.sin(u / 500);
				for (const side of [-1, 1]) {
					glow(ctx, { x: gaze.x + side * gap, y: gaze.y }, across * 3, (0.45 + 0.4 * pulse(u - peak, 300)) * lit * breathe * open, color, false);
				}
				for (const side of [-1, 1]) eye(ctx, gaze.x + side * gap, side, open, lit, look(u));
			}

			if (u < peak) return;
			ctx.globalCompositeOperation = 'lighter';
			for (const m of wisps) stamp(ctx, mist, { x: m.x + (m.drift * (u - peak)) / 1000, y: m.y }, m.size, 0.16 * hold * ramp(u, peak, 800));
			for (const b of bats) {
				const t = (u - b.at) / 1000;
				if (t < 0) continue;
				const a = b.a + b.curl * t;
				const at = { x: b.from.x + Math.cos(a) * b.speed * t, y: b.from.y + Math.sin(a) * b.speed * t };
				fly(ctx, at, b.size * (1 + 0.3 * t), u / 70 + b.flap, 0.85 * ramp(t, 0, 0.3) * hold);
			}
		},
	};
}

/**
 * The hearth signature: nothing rushes. A string of fairy lights comes on
 * bulb by bulb along the top, soft lights hang out of focus in the warm dark, leaves rock
 * gently down, and the glow of a fire breathes along the bottom. It all stays through the
 * title card, and its wash is only faint.
 */
function hearthScene({ w, h, room, color, glyph, rand }: Stage): Scene {
	const leaf = glyphSprite(glyph, color, 48);
	const bokeh = blobSprite(color, 64, 0);
	// Bulbs in the world's colour and two warmer golds.
	const BULB = 26;
	const bulbs = [color, '#ffd28a', '#ffb070'].map((ink) => blobSprite(ink, BULB, 0.12));
	// Hung below the letterbox bar, sagging between its ends.
	const string = (t: number) => ({ x: -w * 0.04 + t * w * 1.08, y: h * 0.16 + h * 0.07 * 4 * t * (1 - t) });
	const wire = trace([{ points: Array.from({ length: 41 }, (_, i) => string(i / 40)), width: 1 }])[0].path;
	const count = Math.round(Math.min(22, Math.max(9, w / 42)));
	const lights = Array.from({ length: count }, (_, i) => ({
		...string((i + 0.5) / count),
		on: -180 + (i * 420) / count,
		bulb: bulbs[i % bulbs.length],
		phase: rand() * Math.PI * 2,
	}));
	const blurs = Array.from({ length: Math.round(16 * room) }, () => ({
		x: rand() * w,
		y: h * (0.2 + rand() * 0.75),
		size: 28 + rand() * 60,
		rise: 6 + rand() * 10,
		sway: rand() * Math.PI * 2,
		alpha: 0.1 + rand() * 0.12,
		at: -300 + rand() * 500,
	}));
	const leaves = Array.from({ length: Math.round(11 * Math.min(room, 1.8)) }, (_, i) => ({
		x: rand() * w,
		y: -30 + rand() * h * 0.5,
		fall: 32 + rand() * 36,
		size: 16 + rand() * 12,
		rock: rand() * Math.PI * 2,
		at: -260 + i * 190 + rand() * 120,
	}));

	return {
		draw(ctx, u, _, hold) {
			const since = u / 1000;
			ctx.globalCompositeOperation = 'lighter';

			const fire = ramp(u, -300, 600) * hold * (0.85 + 0.15 * Math.sin(u / 130) * Math.sin(u / 47));
			glow(ctx, { x: w / 2, y: h * 1.15 }, Math.max(w, h) * 0.7, 0.28 * fire, '#ffb070', false);

			for (const b of blurs) {
				stamp(ctx, bokeh, { x: b.x + Math.sin(since * 0.8 + b.sway) * 10, y: b.y - b.rise * since }, b.size, b.alpha * ramp(u, b.at, 700) * hold);
			}

			ctx.globalAlpha = 0.25 * ramp(u, -300, 300) * hold;
			ctx.strokeStyle = color;
			ctx.lineWidth = 1.2;
			ctx.stroke(wire);
			for (const l of lights) {
				if (u < l.on) continue;
				// A pop as it comes on, then a slow, slight twinkle.
				const lit = Math.min(1, 0.8 + 0.2 * pulse(u - l.on, 160) + 0.06 * Math.sin(u / 400 + l.phase)) * hold;
				stamp(ctx, l.bulb, l, BULB, 0.7 * lit);
				ctx.globalAlpha = lit;
				ctx.fillStyle = '#fff';
				ctx.fill(circle(l, 2.6));
			}

			// The leaves in their own colours, rocking side to side as they settle.
			ctx.globalCompositeOperation = 'source-over';
			for (const f of leaves) {
				const t = (u - f.at) / 1000;
				if (t < 0) continue;
				const rock = t * 1.3 + f.rock;
				stamp(ctx, leaf, { x: f.x + Math.sin(rock) * 34, y: f.y + f.fall * t }, f.size, ramp(t, 0, 0.4) * hold, Math.sin(rock) * 0.7);
			}
		},
	};
}

/**
 * The ripples signature: drops land here and there off the beat, each sending rings out
 * like a sound, the rings brightening where they cross. The last lands on the centre just
 * before the wash, so its rings spread out under the title card, and through the hold drops
 * keep landing, still off the beat.
 */
function ripplesScene({ w, h, centre, span, color, rand, peak, clear }: Stage): Scene {
	const splash = sparkField(rand, color, 900, 0.3, 1.2);
	const somewhere = () => ({ x: w * (0.08 + rand() * 0.84), y: h * (0.1 + rand() * 0.8) });
	// A beat, and drops that keep missing it: half, one and a half, or a whole beat apart.
	const BEAT_MS = 260;
	const drops: { at: number; x: number; y: number; reach: number; landed?: boolean }[] = [];
	for (let u = -260; u < peak - 120; u += BEAT_MS * [0.5, 1, 1.5, 1][Math.floor(rand() * 4)]) {
		drops.push({ at: u + (rand() - 0.5) * 50, ...somewhere(), reach: span * (0.18 + rand() * 0.14) });
	}
	drops.push({ at: peak - 60, ...centre, reach: span * 0.55 });
	for (let u = peak + 300; u < clear - 300; u += 420 + rand() * 380) {
		drops.push({ at: u, ...somewhere(), reach: span * (0.16 + rand() * 0.14) });
	}

	return {
		draw(ctx, u, dt, hold) {
			ctx.globalCompositeOperation = 'lighter';
			for (const d of drops) {
				if (u < d.at) continue;
				if (!d.landed) {
					d.landed = true;
					splash.burst(d, 5, 160, u, -Math.PI * 0.9, -Math.PI * 0.1, 160);
				}
				glow(ctx, d, 22, 0.8 * pulse(u - d.at, 90) * hold, color);
				for (let ring = 0; ring < 3; ring++) {
					const p = ramp(u, d.at + ring * 220, 2800);
					if (p <= 0 || p >= 1) continue;
					strokeLight(ctx, [{ path: circle(d, d.reach * quadOut(p)), width: 1 }], color, 0.25 * (1 - ring * 0.2), 0.7 * (1 - p) * hold);
				}
			}
			splash.draw(ctx, u, dt, hold);
		},
	};
}
