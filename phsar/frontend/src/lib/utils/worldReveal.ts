/**
 * The reveal's canvas side: each signature's light and particles, drawn additively so
 * overlapping glow brightens the way light does. `WorldReveal.svelte` owns the stage, the
 * DOM layers and the swap; both are timed from `BEAT`, so the canvas and the CSS hit the
 * same frames.
 */
import { cubicOut } from 'svelte/easing';
import type { RevealKind, WorldLook } from './discoverWorlds';

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

/** A punching signature takes the hit-stop, the impact frame, the shake, the speed lines and
 *  a white flash; a soft one flows straight through on a wash of its colour. */
export const punches = (kind: RevealKind) => kind !== 'drift';

// A punching scene's clock stands still from the freeze to the peak, so the hit-stop holds
// the frame and nothing has moved on when the impact frame clears.
const HOLD = BEAT.peak - BEAT.freeze;
// How long the speed lines take to fade after the peak.
const SPEED_FADE = 420;

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
	/** One frame at `u` ms from the strike beat on the scene's clock, `dt` seconds after the last. */
	draw(ctx: CanvasRenderingContext2D, u: number, dt: number): void;
	/** A punching scene's impact frame: its silhouette, in white on the black the loop has laid. */
	impact?(ctx: CanvasRenderingContext2D): void;
	/** When, on the scene's clock, it has nothing left to draw — the loop stops there. */
	until: number;
}
interface Stage {
	w: number;
	h: number;
	color: string;
	glyph: string;
	rand: Rand;
	/** The flash peak and the start of the clear, on the scene's clock. */
	peak: number;
	clear: number;
}

const SCENES: Record<RevealKind, (stage: Stage) => Scene> = { bolt: boltScene, drift: driftScene };

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
	const scene = SCENES[look.reveal]({
		w,
		h,
		color: look.color,
		glyph: look.particle.glyph,
		rand,
		peak: BEAT.peak - hold - BEAT.strike,
		clear: BEAT.clear - hold - BEAT.strike,
	});
	// Once the scene and the speed lines have nothing left to draw.
	const stopAt = Math.min(BEAT.end, Math.max(scene.until + BEAT.strike + hold, punch ? BEAT.peak + SPEED_FADE : 0));
	let frame = 0;
	let start = -1;
	let last = -BEAT.strike;
	const tick = (now: number) => {
		if (start < 0) start = now;
		const t = now - start;
		const pastPeak = t >= BEAT.peak;
		const u = (pastPeak ? t - hold : t) - BEAT.strike;
		if (t >= stopAt) {
			ctx.clearRect(0, 0, w, h);
			return;
		}
		frame = requestAnimationFrame(tick);
		if (punch && t >= BEAT.freeze && t < BEAT.impact) return;
		ctx.clearRect(0, 0, w, h);
		ctx.globalAlpha = 1;
		ctx.globalCompositeOperation = 'source-over';
		if (punch && t >= BEAT.impact && !pastPeak) {
			ctx.fillStyle = '#000';
			ctx.fillRect(0, 0, w, h);
			speedLines(ctx, w, h, rand, 0.9);
			scene.impact?.(ctx);
			return;
		}
		scene.draw(ctx, u, Math.min(u - last, 50) / 1000);
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
// 1 until `from`, then down to 0 over `ms`. Clamped both ways: a `globalAlpha` outside 0–1
// is ignored, not clamped, so the previous value would draw instead.
const fadeFrom = (s: number, from: number, ms: number) => Math.min(1, Math.max(0, 1 - (s - from) / ms));

/** A radial glow round `at`, its colour fading out to the edge; `core` gives it a white-hot
 *  centre. */
function glow(ctx: CanvasRenderingContext2D, at: Point, radius: number, alpha: number, color: string, core = true) {
	if (alpha <= 0) return;
	const g = ctx.createRadialGradient(at.x, at.y, 0, at.x, at.y, radius);
	if (core) g.addColorStop(0, '#fff');
	g.addColorStop(core ? 0.12 : 0, color);
	g.addColorStop(1, 'transparent');
	ctx.globalAlpha = alpha;
	ctx.fillStyle = g;
	ctx.fillRect(at.x - radius, at.y - radius, radius * 2, radius * 2);
}

/** A bolt's channels as one path per width. Its shape never changes once struck, so it is
 *  traced once rather than every frame. */
interface Traced {
	path: Path2D;
	width: number;
}
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

// Wide to narrow: the glow, the body in the bolt's colour, the white-hot core.
const PASSES = [
	[18, 0.12, false],
	[7, 0.4, false],
	[2.2, 1, true],
] as const;
function strokeBolt(ctx: CanvasRenderingContext2D, traced: Traced[], color: string, scale: number, alpha: number) {
	if (alpha <= 0) return;
	for (const [width, share, white] of PASSES) {
		ctx.strokeStyle = white ? '#fff' : color;
		ctx.globalAlpha = alpha * share;
		for (const t of traced) {
			ctx.lineWidth = width * t.width * scale;
			ctx.stroke(t.path);
		}
	}
}

/** `glyph` drawn once with its glow, for a scene to stamp: a blurred `fillText` per glyph per
 *  frame is what drops a phone's frames. The glyph is `px` tall in a sprite twice that, so
 *  the blur has room. */
function glyphSprite(glyph: string, color: string, px: number): HTMLCanvasElement {
	const sprite = document.createElement('canvas');
	sprite.width = sprite.height = px * 2;
	const g = sprite.getContext('2d');
	if (g) {
		g.font = `${px}px system-ui, sans-serif`;
		g.textAlign = 'center';
		g.textBaseline = 'middle';
		g.fillStyle = color;
		g.shadowColor = color;
		g.shadowBlur = px * 0.35;
		g.fillText(glyph, px, px);
	}
	return sprite;
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
// Sparks are stroked in batches by alpha step, the upper half white-hot and the lower half
// cooled to the bolt's colour: hundreds of them, a handful of strokes.
const SPARK_STEPS = 6;

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
function boltScene({ w, h, color, rand, peak, clear }: Stage): Scene {
	const target = { x: w / 2, y: h / 2 };
	const LEADER = 110;
	const HIT = 370;
	// The last of the charge fades over this from the clear; the scene ends with it.
	const OUT = 350;
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
			fadeMs: OUT,
		};
		return { strike, end };
	});
	// The arcs crawl round an ellipse a little wider than the title.
	const rx = Math.min(w * 0.42, 330);
	const ry = Math.min(h * 0.14, 110);
	const onRing = (a: number) => ({ x: target.x + Math.cos(a) * rx, y: target.y + Math.sin(a) * ry });
	const arcs: { traced: Traced[]; born: number; life: number }[] = [];
	let sparks: Spark[] = [];
	const sparkCount = Math.round(Math.min(110, 40 + (w * h) / 18000));
	let bursts = 0;

	const burst = (count: number, speed: number, u: number) => {
		for (let i = 0; i < count; i++) {
			const a = -Math.PI * (0.05 + rand() * 0.9);
			const v = speed * (0.35 + rand() * 0.65);
			sparks.push({ ...target, vx: Math.cos(a) * v, vy: Math.sin(a) * v, born: u, life: 450 + rand() * 650 });
		}
	};

	return {
		draw(ctx, u, dt) {
			if (u < 0) return;
			ctx.globalCompositeOperation = 'lighter';
			if (u < LEADER) {
				ctx.save();
				ctx.beginPath();
				ctx.rect(0, 0, w, target.y * (u / LEADER));
				ctx.clip();
				strokeBolt(ctx, storm[0].traced, color, 1, 0.3);
				ctx.restore();
				return;
			}
			if (bursts === 0) {
				burst(sparkCount, 620, u);
				bursts = 1;
			}
			if (bursts === 1 && u >= HIT) {
				burst(Math.round(sparkCount * 1.6), 950, u);
				bursts = 2;
			}
			const charge = fadeFrom(u, clear, OUT);

			glow(ctx, target, Math.min(w, h) * 0.32, 0.55 * (0.35 + 0.65 * pulse(u - LEADER, 420)) * fadeFrom(u, peak, 260), color);
			// The charge left round the title, breathing about once a second.
			if (u >= peak) glow(ctx, target, rx * 1.3, (0.11 + 0.04 * Math.sin((u - peak) / 160)) * charge, color);

			for (const strike of storm) strokeBolt(ctx, strike.traced, color, strike.width, strength(strike, u));
			for (const { strike, end } of distant) {
				const k = strength(strike, u);
				strokeBolt(ctx, strike.traced, color, strike.width, k);
				glow(ctx, end, 70, 0.3 * k, color);
			}

			if (u >= peak && u < clear && rand() < dt * 18) {
				const a = rand() * Math.PI * 2;
				const gap = (0.3 + rand() * 0.6) * (rand() < 0.5 ? -1 : 1);
				const points = displace(onRing(a), onRing(a + gap), 0.5, 4, rand);
				arcs.push({ traced: trace([{ points, width: 0.4 }]), born: u, life: 80 + rand() * 120 });
			}
			for (const arc of arcs) {
				const left = 1 - (u - arc.born) / arc.life;
				if (left > 0) strokeBolt(ctx, arc.traced, color, 1, left * (0.6 + 0.4 * rand()) * charge);
			}

			sparks = sparks.filter((p) => u - p.born < p.life);
			if (!sparks.length) return;
			const drag = Math.pow(0.25, dt);
			const batches = Array.from({ length: SPARK_STEPS }, () => new Path2D());
			for (const p of sparks) {
				p.vx *= drag;
				p.vy = p.vy * drag + 1500 * dt;
				p.x += p.vx * dt;
				p.y += p.vy * dt;
				const batch = batches[Math.min(SPARK_STEPS - 1, Math.floor((1 - (u - p.born) / p.life) * SPARK_STEPS))];
				batch.moveTo(p.x, p.y);
				batch.lineTo(p.x - p.vx * 0.03, p.y - p.vy * 0.03);
			}
			ctx.lineWidth = 1.8;
			batches.forEach((batch, i) => {
				ctx.globalAlpha = (i + 0.5) / SPARK_STEPS;
				ctx.strokeStyle = i >= SPARK_STEPS / 2 ? '#fff' : color;
				ctx.stroke(batch);
			});
		},
		impact(ctx) {
			ctx.globalAlpha = 1;
			ctx.strokeStyle = '#fff';
			for (const strike of storm) {
				for (const t of strike.traced) {
					ctx.lineWidth = 6 * t.width * strike.width;
					ctx.stroke(t.path);
				}
			}
		},
		until: clear + OUT,
	};
}

/** The soft signature, and the default: the world's glyph flutters in from past the edges,
 *  spiralling onto the centre while a warm glow gathers there. */
function driftScene({ w, h, color, glyph, rand, peak }: Stage): Scene {
	const centre = { x: w / 2, y: h / 2 };
	// Everything fades over this from the peak; the scene ends with it.
	const OUT = 320;
	const outer = Math.hypot(w, h) * 0.55;
	// Drawn at twice the largest flake, so it stays sharp on a 2× screen.
	const sprite = glyphSprite(glyph, color, 72);
	const flakes = Array.from({ length: 22 }, () => ({
		angle: rand() * Math.PI * 2,
		size: 16 + rand() * 18,
		spin: (rand() - 0.5) * 7,
		sway: rand() * Math.PI * 2,
		delay: rand() * 220,
	}));
	return {
		draw(ctx, u) {
			// The flakes set off a beat before the strike, so they are in the air by then.
			const v = u + 200;
			if (v < 0) return;
			const fade = fadeFrom(u, peak, OUT);
			ctx.globalCompositeOperation = 'lighter';
			glow(ctx, centre, Math.min(w, h) * 0.4, 0.35 * Math.min(1, v / 700) * fade, color, false);

			ctx.globalCompositeOperation = 'source-over';
			for (const f of flakes) {
				const p = Math.min(1, Math.max(0, (v - f.delay) / 760));
				if (p <= 0) continue;
				const eased = cubicOut(p);
				const r = outer * (1 - eased) + Math.min(w, h) * 0.1 * eased;
				const a = f.angle + eased * 1.8 + Math.sin(p * 6 + f.sway) * 0.08;
				ctx.globalAlpha = Math.min(1, p * 4) * fade;
				ctx.save();
				ctx.translate(centre.x + Math.cos(a) * r, centre.y + Math.sin(a) * r);
				ctx.rotate(f.spin * p);
				ctx.drawImage(sprite, -f.size, -f.size, f.size * 2, f.size * 2);
				ctx.restore();
			}
		},
		until: peak + OUT,
	};
}
