/**
 * The galaxy map's arithmetic and colours (docs/features/galaxy.md), kept out of the
 * component so they are testable without a canvas.
 *
 * The colours are literals on purpose, like `COVERAGE_STYLE`: the map is night sky on the
 * dark page surface under every theme, and its hues are picked for contrast against it.
 */
import type { GalaxySector, GalaxyStar } from '$lib/types/api';
import { getThemedChartColorPalette } from '$lib/utils/chartColors';
import { COVERAGE_STYLE, type CoverageTier } from '$lib/utils/ratingCoverage';

/** What colours the stars: `mine` is My progress, `own` My scores. */
export type GalaxyColour = 'sector' | 'score' | 'mine' | 'own';

/** The colourings read from the viewer's own ratings: a guest's are inert, and the rest of
 *  the map recedes under them. */
export const personal = (colour: GalaxyColour) => colour === 'mine' || colour === 'own';

/** Neighbouring sectors never share one; the names carry identity, the hue only separates. */
const SECTOR_HUES = ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#2f9e44', '#9085e9', '#e66767'];
/**
 * The search's "Top N%" rank, bottom to top: one hue, dark to light. By rank rather than by
 * score, because MAL scores crowd between 6.5 and 8 and an absolute scale paints the map
 * nearly one shade; a rank spreads evenly by construction. The dark end stays bright
 * enough to read as a star on the night sky.
 */
export const SCORE_RAMP = ['#3a5a92', '#4f94ee', '#e3efff'];
/** Where a "Top N%" sits on `SCORE_RAMP`: 0 for the bottom of the catalogue, 1 for the top. */
export const rankShare = (topPercent: number) => (100 - topPercent) / 99;
/** The grey that recedes: a star the filters leave out, or an unscored one with no filters
 *  on (`blankColour`). */
export const NO_VALUE = '#4a4e66';
export const LIT_NO_VALUE = '#589194';
/**
 * A star with no value in the colouring — unscored, or not rated — in a grey that recedes.
 * With filters on, a lit one takes a muted teal instead, so a filter matching only unrated
 * anime does not read as one cloud with the greyed-out rest: muted, so it never outshines
 * a star that has a value; teal, because it stays clear of the tiers' gold, every
 * theme's primary and the score blues. The stars and the legend both read it.
 */
export function blankColour(colour: GalaxyColour, lit: boolean): string {
	if (lit) return LIT_NO_VALUE;
	return personal(colour) ? '#3b3f57' : NO_VALUE;
}

/** Why an empty Find box suggests an anime. */
export type PickReason = 'favourite' | 'watchlist' | 'top';

/** An empty Find box's suggestions, and how many may be the viewer's own favourites or
 *  watchlist entries each: a couple to anchor them on the map, the rest to discover. */
const PICKS = 6;
const PERSONAL_PICKS = 2;

/** FNV-1a: a stable, well-spread order, the same for a day and different the next. */
function hash(text: string): number {
	let h = 0x811c9dc5;
	for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193);
	return h >>> 0;
}

/**
 * The suggestions an empty Find box shows on `day`: `PERSONAL_PICKS` of the viewer's
 * favourites (their own Top 10%, `ownTop` as `/ratings/coverage` ranks it, never fewer than
 * their best `PERSONAL_PICKS`), as many from their watchlist (highest priority first), and the
 * catalogue's top 5% of anime they have neither rated nor listed for the rest. Within a pool
 * the day picks, so they hold all day and change the next.
 */
export function dailyPicks(
	stars: GalaxyStar[],
	ownTop: Map<string, number>,
	watchPriority: Map<string, number>,
	day: string
): { star: GalaxyStar; why: PickReason }[] {
	const byDay = (a: GalaxyStar, b: GalaxyStar) => hash(day + a.anime_uuid) - hash(day + b.anime_uuid);
	const top = (s: GalaxyStar) => ownTop.get(s.anime_uuid)!;
	const priority = (s: GalaxyStar) => watchPriority.get(s.anime_uuid)!;
	const rated = stars.filter((s) => ownTop.has(s.anime_uuid)).sort((a, b) => top(a) - top(b));
	const favourites = rated
		.filter((s, k) => k < PERSONAL_PICKS || top(s) <= 10)
		.sort(byDay)
		.slice(0, PERSONAL_PICKS);
	const listed = stars
		.filter((s) => watchPriority.has(s.anime_uuid) && !favourites.includes(s))
		.sort((a, b) => priority(a) - priority(b) || byDay(a, b))
		.slice(0, PERSONAL_PICKS);
	const malTop = stars
		.filter((s) => s.top_percent != null && s.top_percent <= 5 && !ownTop.has(s.anime_uuid) && !watchPriority.has(s.anime_uuid))
		.sort(byDay)
		.slice(0, PICKS - favourites.length - listed.length);
	return [
		...favourites.map((star) => ({ star, why: 'favourite' as const })),
		...listed.map((star) => ({ star, why: 'watchlist' as const })),
		...malTop.map((star) => ({ star, why: 'top' as const }))
	];
}

/** My progress' colour for a coverage tier: the tiers' metals, the theme's colour for
 *  everything still in progress. The stars and the legend both read it. */
export function mineColour(tier: CoverageTier): string {
	return tier === 'some' ? getThemedChartColorPalette()[0] : COVERAGE_STYLE[tier].edge;
}

/** The figures a star's hover card and the panel both show: score · Top N% · year. */
export function starFigures(s: GalaxyStar): string {
	return [malScore(s.score), s.top_percent == null ? null : `Top ${s.top_percent}%`, s.year].filter(Boolean).join(' · ');
}

/** A MAL score as the map shows one, an anime's or a group's average. */
export const malScore = (score: number | null) => (score == null ? 'Unscored' : `★ ${score.toFixed(2)}`);

const mean = (vs: number[]) => (vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : null);

/** The extent of `points`: `[x0, x1, y0, y1]`. */
function bounds(points: { x: number; y: number }[]): [number, number, number, number] {
	const [xs, ys] = [points.map((p) => p.x), points.map((p) => p.y)];
	return [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
}

/** Below this share of the map's width (percent), region names replace sector names. */
export const REGION_LABELS_BELOW = 55;
/** Below this, stars become covers. */
export const COVER_SPAN = 11;
/** The deepest zoom. */
export const MIN_SPAN = 2.5;
/** The zoom a picked star opens at: deep enough that its cover and those around it read. */
export const FOCUS_SPAN = 4;
const MAX_COVERS = 220;

/**
 * A hue per sector number: greedy colouring of the graph joining each sector to its four
 * nearest label anchors, most-connected first. A sector left without a free hue wraps
 * round rather than failing.
 */
export function sectorHues(sectors: GalaxySector[]): Map<number, string> {
	const near = sectors.map((s, i) =>
		sectors
			.map((t, j) => [j, Math.hypot(s.x - t.x, s.y - t.y)] as const)
			.filter(([j]) => j !== i)
			.sort((a, b) => a[1] - b[1])
			.slice(0, 4)
			.map(([j]) => j)
	);
	near.forEach((ns, i) => ns.forEach((j) => near[j].includes(i) || near[j].push(i)));
	const hue: number[] = [];
	for (const i of sectors.map((_, i) => i).sort((a, b) => near[b].length - near[a].length)) {
		const used = new Set(near[i].map((j) => hue[j]));
		hue[i] = SECTOR_HUES.findIndex((_, h) => !used.has(h));
		if (hue[i] < 0) hue[i] = i % SECTOR_HUES.length;
	}
	return new Map(sectors.map((s, i) => [s.number, SECTOR_HUES[hue[i]]]));
}

export interface MapWindow {
	x: [number, number];
	y: [number, number];
}

/**
 * The extents that show every point with one data unit per pixel on both axes, so the map
 * keeps its shape in any box. Zooming scales both axes by the same factor, which keeps it.
 */
export function fitWindow(points: { x: number; y: number }[], width: number, height: number): MapWindow {
	const [x0, x1, y0, y1] = bounds(points);
	const perPx = (Math.max((x1 - x0) / width, (y1 - y0) / height) || 1) * 1.06;
	const [cx, cy] = [(x0 + x1) / 2, (y0 + y1) / 2];
	return {
		x: [cx - (perPx * width) / 2, cx + (perPx * width) / 2],
		y: [cy - (perPx * height) / 2, cy + (perPx * height) / 2]
	};
}

/** A `width`-percent zoom window around `centre` (percent), slid inside the map rather than cut at its edge. */
export function percentWindow(centre: number, width: number): [number, number] {
	const start = Math.max(0, Math.min(100 - width, centre - width / 2));
	return [start, start + width];
}

/**
 * Both axes' zoom windows at the wider of their two spans, each kept on its centre.
 * ECharts zooms each axis on its own and cuts a window that overruns the map's edge, so
 * zooming out beside an edge narrows one axis more than the other and the map would
 * stretch. Zooming in never cuts, so the wider span is the one the gesture meant.
 */
export function evenWindows(x: [number, number], y: [number, number]): [[number, number], [number, number]] {
	const width = Math.max(x[1] - x[0], y[1] - y[0]);
	return [percentWindow((x[0] + x[1]) / 2, width), percentWindow((y[0] + y[1]) / 2, width)];
}

/** A sector or a region, by its number at its level. */
export interface GroupRef {
	level: 'sector' | 'region';
	number: number;
}

export const inGroup = (s: GalaxyStar, g: GroupRef) => s[g.level] === g.number;
export const sameGroup = (a: GroupRef, b: GroupRef) => a.level === b.level && a.number === b.number;

/** How many anime each sector or region holds. */
export const groupSizes = (stars: GalaxyStar[], level: GroupRef['level']) =>
	new Map([...Map.groupBy(stars, (s) => s[level])].map(([number, members]) => [number, members.length]));

/** What the galaxy's panel shows: an anime by its uuid, or a sector or region. */
export type Pick = string | GroupRef;

/**
 * The view that shows all of a group's stars, with a margin: its centre, and its width in
 * percent of `win`. The map's own controls sit at its sides (`insets`, in pixels of a box
 * `boxWidth` wide), so the group is framed in the strip between them, not under them. A
 * group the layout split shows wide, across its parts.
 */
export function groupView(
	stars: GalaxyStar[],
	group: GroupRef,
	win: MapWindow,
	boxWidth: number,
	insets: { left: number; right: number }
): { x: number; y: number; width: number } {
	const [x0, x1, y0, y1] = bounds(stars.filter((s) => inGroup(s, group)));
	const winWidth = win.x[1] - win.x[0];
	const clear = boxWidth - insets.left - insets.right;
	const share = Math.max(((x1 - x0) / winWidth) * (boxWidth / clear), (y1 - y0) / (win.y[1] - win.y[0]));
	const span = Math.min(100, Math.max(MIN_SPAN, share * 100 * 1.15));
	// The strip's centre sits off the box's by half the difference of the insets.
	const perPixel = (winWidth * span) / 100 / boxWidth;
	return { x: (x0 + x1) / 2 - ((insets.left - insets.right) / 2) * perPixel, y: (y0 + y1) / 2, width: span };
}

/** How far around a star its group counts as its cluster, as a share of the map's extent. */
const ANCHOR_RADIUS = 0.04;

/**
 * Where each group's name sits: on its densest cluster. The group's mean position, which the
 * map carries, lands between the parts of a group the layout split, or over a neighbour. The
 * densest spot is the star with the most of its group within `ANCHOR_RADIUS`; the name sits
 * at that neighbourhood's mean.
 */
export function labelAnchors(stars: GalaxyStar[], level: GroupRef['level']): Map<number, [number, number]> {
	const [x0, x1, y0, y1] = bounds(stars);
	const r2 = (ANCHOR_RADIUS * Math.max(x1 - x0, y1 - y0)) ** 2;
	return new Map(
		[...Map.groupBy(stars, (s) => s[level])].map(([number, members]) => {
			let best: GalaxyStar[] = [];
			for (const s of members) {
				const near = members.filter((t) => (t.x - s.x) ** 2 + (t.y - s.y) ** 2 <= r2);
				if (near.length > best.length) best = near;
			}
			// Never empty: every star is within the radius of itself.
			return [number, [mean(best.map((s) => s.x))!, mean(best.map((s) => s.y))!]];
		})
	);
}

/** How many genres and anime a group's panel lists. */
const GROUP_GENRES = 5;
const GROUP_TOP = 5;

/** What a sector's or region's panel shows, from the map and the viewer's own scores. */
export function groupStats(stars: GalaxyStar[], group: GroupRef, scores: Map<string, number>) {
	const members = stars.filter((s) => inGroup(s, group));
	const rated = members.filter((s) => scores.has(s.anime_uuid));
	const genreCounts = new Map<string, number>();
	for (const s of members) for (const g of s.genres) genreCounts.set(g, (genreCounts.get(g) ?? 0) + 1);
	return {
		count: members.length,
		rated: rated.length,
		malMean: mean(members.flatMap((s) => (s.score == null ? [] : [s.score]))),
		ownMean: mean(rated.map((s) => scores.get(s.anime_uuid)!)),
		genres: [...genreCounts]
			.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
			.slice(0, GROUP_GENRES)
			.map(([name, n]) => ({ name, share: n / members.length })),
		top: members
			.filter((s) => s.top_percent != null)
			.sort((a, b) => a.top_percent! - b.top_percent! || (b.score ?? 0) - (a.score ?? 0))
			.slice(0, GROUP_TOP)
	};
}

/** Whether a point (pixels) lies on a map of this size. */
export const onMap = ([x, y]: [number, number], [width, height]: [number, number]) => x >= 0 && x <= width && y >= 0 && y <= height;

/**
 * Where to centre a label (pixels) so it sits wholly inside the map, `pad` from the edge,
 * from its anchor and its size alone. Nothing it returned before feeds back in: ECharts
 * hands a layout callback the label's box as last placed, so a shift worked out from that
 * box undoes itself on the next redraw and the label flips in and out. A label anchored
 * off the map stays off it rather than piling up along the edge.
 */
export function labelCentre(
	[ax, ay]: [number, number],
	[w, h]: [number, number],
	[width, height]: [number, number],
	pad = 8
): [number, number] {
	if (!onMap([ax, ay], [width, height])) return [ax, ay];
	const keep = (v: number, size: number, box: number) => Math.max(pad + size / 2, Math.min(box - pad - size / 2, v));
	return [keep(ax, w, width), keep(ay, h, height)];
}

/** A name's box, by its centre, in pixels. */
interface LabelBox {
	x: number;
	y: number;
	width: number;
	height: number;
}

/**
 * Each name's centre height, moved so no two whose boxes share any of their width overlap,
 * kept `pad` inside a map `height` tall, and moved as little as possible: the least sum of
 * squared shifts. Not ECharts' own `shiftY`, which treats every name as one column and only
 * pushes down, so names side by side push each other off their clusters. Two names keep
 * their order top to bottom, which keeps the problem convex; Hildreth's dual coordinate
 * ascent solves it, exactly in the limit, and names taller together than the map stop at a cap.
 */
export function spreadLabels(boxes: LabelBox[], height: number, pad = 8, gap = 2): number[] {
	const ys = boxes.map((b) => b.y);
	const pairs: { above: number; below: number; apart: number; dual: number }[] = [];
	boxes.forEach((a, i) =>
		boxes.forEach((b, j) => {
			if (j <= i || Math.abs(a.x - b.x) >= (a.width + b.width) / 2) return;
			const [above, below] = a.y <= b.y ? [i, j] : [j, i];
			pairs.push({ above, below, apart: (a.height + b.height) / 2 + gap, dual: 0 });
		})
	);
	const edges = boxes.map((b) => ({ top: pad + b.height / 2, bottom: height - pad - b.height / 2, down: 0, up: 0 }));
	let moved = 0;
	const shift = (dual: number, short: number) => {
		const step = Math.max(-dual, short);
		moved = Math.max(moved, Math.abs(step));
		return step;
	};
	for (let sweep = 0; sweep < 500; sweep++) {
		moved = 0;
		for (const p of pairs) {
			const step = shift(p.dual, (p.apart - (ys[p.below] - ys[p.above])) / 2);
			p.dual += step;
			ys[p.below] += step;
			ys[p.above] -= step;
		}
		edges.forEach((e, i) => {
			const down = shift(e.down, e.top - ys[i]);
			e.down += down;
			ys[i] += down;
			const up = shift(e.up, ys[i] - e.bottom);
			e.up += up;
			ys[i] -= up;
		});
		if (moved < 0.01) break;
	}
	return ys;
}

/** A cover's width over its height: the carousel tiles' `aspect-[2/3]`, so a cover looks the same on both. */
export const COVER_ASPECT = 2 / 3;

/** A cover's box at a zoom: it grows as the view narrows, up to a readable poster. */
export function coverSize(span: number): [number, number] {
	const h = Math.round(Math.min(70, 22 + (COVER_SPAN - span) * 5.5));
	return [Math.round(h * COVER_ASPECT), h];
}

/**
 * The part of a `width` × `height` image that fills a box of `aspect` (width over height),
 * centred: CSS `object-fit: cover`, as `[sx, sy, sw, sh]` for `drawImage`.
 */
export function coverCrop(width: number, height: number, aspect: number): [number, number, number, number] {
	if (width / height > aspect) {
		const sw = height * aspect;
		return [(width - sw) / 2, 0, sw, height];
	}
	const sh = width / aspect;
	return [0, (height - sh) / 2, width, sh];
}

/**
 * Which of `points` (pixel centres, in priority order) get a cover: each one that would
 * not overlap a cover already placed, up to a cap that keeps a dense view drawable.
 */
export function packCovers(points: [number, number][], [w, h]: [number, number]): number[] {
	const placed: [number, number][] = [];
	const kept: number[] = [];
	points.forEach(([px, py], i) => {
		if (kept.length >= MAX_COVERS) return;
		if (placed.some(([qx, qy]) => Math.abs(qx - px) < w + 2 && Math.abs(qy - py) < h + 2)) return;
		placed.push([px, py]);
		kept.push(i);
	});
	return kept;
}

/** One star's pull on the nebula: how strongly, in which tint. */
export interface NebulaSource {
	x: number;
	y: number;
	weight: number;
	tint: [number, number, number];
	/** Shapes the veil only, adding no haze and no core: a star the filters leave out. */
	veilOnly?: boolean;
}

/**
 * The nebula as RGBA pixels over `win`, `width` wide: three layers drawn once per
 * colouring and stretched with the zoom — a faint veil joining the clusters, the tinted
 * haze, bright cores where stars crowd. Density is tone-mapped (1 − e^−d), so a crowded
 * cluster glows instead of burning white. One image rather than a glow per star, which
 * is what keeps panning smooth.
 */
export function nebulaPixels(
	sources: NebulaSource[],
	win: MapWindow,
	width: number,
	veilTint: [number, number, number]
): { pixels: Uint8ClampedArray; width: number; height: number } {
	const [dx, dy] = [win.x[1] - win.x[0], win.y[1] - win.y[0]];
	const height = Math.max(1, Math.round((width * dy) / dx));
	const n = width * height;
	const [R, G, B, W, V] = [0, 0, 0, 0, 0].map(() => new Float32Array(n));
	for (const s of sources) {
		const col = Math.round(((s.x - win.x[0]) / dx) * (width - 1));
		const row = Math.round((1 - (s.y - win.y[0]) / dy) * (height - 1));
		if (col < 0 || col >= width || row < 0 || row >= height) continue;
		const k = row * width + col;
		V[k] += s.weight;
		if (s.veilOnly) continue;
		R[k] += s.tint[0] * s.weight;
		G[k] += s.tint[1] * s.weight;
		B[k] += s.tint[2] * s.weight;
		W[k] += s.weight;
	}
	const core = boxBlur(W.slice(), width, height, 2);
	const veil = boxBlur(V, width, height, 34);
	for (const a of [R, G, B, W]) boxBlur(a, width, height, 11);
	const [kH, kC, kV] = [quantile(W, 0.9), quantile(core, 0.995), quantile(veil, 0.9)];
	const RGB = [R, G, B];
	const pixels = new Uint8ClampedArray(n * 4);
	for (let k = 0; k < n; k++) {
		const w = W[k];
		const va = (1 - Math.exp(-veil[k] / kV)) * 0.2;
		if (w < 1e-6 && va < 0.004) continue;
		const c = Math.min(1, core[k] / kC) ** 2;
		const ha = w < 1e-6 ? 0 : Math.min(0.8, (1 - Math.exp(-w / kH)) * 0.5 + c * 0.3);
		const a = ha + va * (1 - ha);
		for (let ch = 0; ch < 3; ch++) {
			const hue = w < 1e-6 ? veilTint[ch] : (RGB[ch][k] / w) * (1 - 0.5 * c) + 128 * c;
			pixels[k * 4 + ch] = (hue * ha + veilTint[ch] * va * (1 - ha)) / a;
		}
		pixels[k * 4 + 3] = 255 * a;
	}
	return { pixels, width, height };
}

/** Three separable box passes, which approximate a gaussian, in place. */
function boxBlur(a: Float32Array, w: number, h: number, r: number): Float32Array {
	const t = new Float32Array(a.length);
	const n = 2 * r + 1;
	for (let pass = 0; pass < 3; pass++) {
		for (let y = 0; y < h; y++) {
			let s = 0;
			const o = y * w;
			for (let x = -r; x < w; x++) {
				if (x + r < w) s += a[o + x + r];
				if (x - r - 1 >= 0) s -= a[o + x - r - 1];
				if (x >= 0) t[o + x] = s / n;
			}
		}
		for (let x = 0; x < w; x++) {
			let s = 0;
			for (let y = -r; y < h; y++) {
				if (y + r < h) s += t[(y + r) * w + x];
				if (y - r - 1 >= 0) s -= t[(y - r - 1) * w + x];
				if (y >= 0) a[y * w + x] = s / n;
			}
		}
	}
	return a;
}

/** The `f` quantile of the non-empty values, so empty sky does not drag the scale down. */
function quantile(a: Float32Array, f: number): number {
	// A typed array sorts numerically and natively, with no comparator to call.
	const v = a.filter((x) => x > 1e-6).sort();
	return v[Math.floor(v.length * f)] || 1;
}
