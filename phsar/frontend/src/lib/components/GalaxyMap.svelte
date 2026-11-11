<script lang="ts">
	/**
	 * The galaxy map's canvas (docs/features/galaxy.md). It owns its ECharts instance
	 * rather than going through `EChart.svelte`: that wrapper re-applies the whole option
	 * on every change, which would reset the zoom, and the map needs the instance itself —
	 * the zoom events, and pixel positions to pack covers.
	 *
	 * Both axes zoom together from an aspect-true window (`fitWindow`), so the map keeps
	 * its shape. Covers and the overview wait for a zoom to settle, so nothing jumps
	 * mid-gesture.
	 *
	 * The camera follows the pick: a star glides close enough for the covers, a sector or
	 * region to fit all its stars, and letting go glides back out to the whole map.
	 */
	import { onMount, untrack } from 'svelte';
	import { cubicInOut } from 'svelte/easing';
	import { MediaQuery } from 'svelte/reactivity';
	import { Captions, CaptionsOff, Maximize2, Minus, Plus } from 'lucide-svelte';
	import { getEcharts } from '$lib/echarts';
	import Tooltip from '$lib/components/Tooltip.svelte';
	import * as cls from '$lib/styles/classes';
	import { chartTooltipStyle } from '$lib/utils/chartTheme';
	import { COVERAGE_STYLE, coverageTier } from '$lib/utils/ratingCoverage';
	import { RATED_STATES } from '$lib/utils/search';
	import { escapeHtml, formatScoreWithStep, resolveTitle } from '$lib/utils/formatString';
	import {
		COVER_ASPECT, COVER_SPAN, FOCUS_SPAN, LIT_NO_VALUE, MIN_SPAN, NO_VALUE, REGION_LABELS_BELOW, SCORE_RAMP,
		blankColour, coverCrop, coverSize, evenWindows, fitWindow, groupSizes, groupView, inGroup, labelCentre, mineColour,
		nebulaPixels, onMap, packCovers, percentWindow, personal, rankShare, sectorHues, spreadLabels, starFigures,
		sameGroup, type GalaxyColour, type GroupRef, type Pick,
		type MapWindow, type NebulaSource
	} from '$lib/utils/galaxy';
	import type { AnimeRatingCoverage, GalaxyMap, GalaxyStar } from '$lib/types/api';

	type State = AnimeRatingCoverage['state'];
	type Range = [number, number];

	interface Props {
		map: GalaxyMap;
		colour: GalaxyColour;
		/** The anime the filters keep, lit while the rest dim; null with no filters. */
		lit: Set<string> | null;
		states: Map<string, State>;
		/** The viewer's score per rated anime, and its "Top N%" among theirs, keyed like `states`. */
		scores: Map<string, number>;
		ownTop: Map<string, number>;
		/** The viewer's rating step, which their scores show at. */
		ratingStep: number;
		/** The picked anime, or the picked sector or region; at most one is set. */
		selected: string | null;
		group: GroupRef | null;
		neighbours: string[];
		/** The neighbour the panel's pointer is on, whose link stands out. */
		hovered: string | null;
		nameLanguage: 'english' | 'japanese' | 'romaji';
		/** Whether the groups' names show; hidden, they leave every star to the pointer. */
		names: boolean;
		onNames: (show: boolean) => void;
		/** A star or a name clicked. */
		onPick: (pick: Pick) => void;
	}

	let { map, colour, lit, states, scores, ownTop, ratingStep, selected, group, neighbours, hovered, nameLanguage, names, onNames, onPick }: Props = $props();

	let container: HTMLDivElement;
	let overview: HTMLCanvasElement;
	let controls: HTMLDivElement;
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	let chart = $state<any>(null);
	/** ECharts' own colour helpers and text element, from the bundle the chart loads. */
	let colours: { lerp(t: number, stops: string[]): string; parse(c: string): number[]; modifyAlpha(c: string, a: number): string };
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	let Text: any;
	let win: MapWindow | null = null;
	/** The visible share of the map's width, in percent. */
	let span = $state(100);
	let settleTimer: ReturnType<typeof setTimeout> | undefined;

	let index = $derived(new Map(map.stars.map((s, i) => [s.anime_uuid, i])));
	let hues = $derived(sectorHues(map.sectors));
	let sectorName = $derived(new Map(map.sectors.map((g) => [g.number, g.name])));
	let regionName = $derived(new Map(map.regions.map((g) => [g.number, g.name])));
	let sizes = $derived({ sector: groupSizes(map.stars, 'sector'), region: groupSizes(map.stars, 'region') });
	const wide = new MediaQuery(cls.smUp);
	const STATE_LABEL = new Map(RATED_STATES.anime.map((s) => [s.value, s.label]));
	const SHEEN = COVERAGE_STYLE.all.hairline!;
	const GOLD = '#f2c46d';

	const name = (s: GalaxyStar) => resolveTitle(s.title, s.name_eng, s.name_jap, nameLanguage);
	/** The group whose name the pointer is on. */
	let hoverSpot = $state<GroupRef | null>(null);
	let spotTimer: ReturnType<typeof setTimeout> | undefined;
	/** The group in the spotlight, everything outside it greyed: the one hovered, else the
	 *  one picked. */
	let spot = $derived(hoverSpot ?? group);
	/** The spotlight by value: a hover handing back to the same picked group changes nothing. */
	let spotKey = $derived(spot && `${spot.level} ${spot.number}`);
	/** Greyed: left out by the filters (and out of the hover's way), or outside the spotlight. */
	const filteredOut = (s: GalaxyStar) => lit != null && !lit.has(s.anime_uuid);
	const outsideSpot = (s: GalaxyStar) => spot != null && !inGroup(s, spot);
	const dimmed = (s: GalaxyStar) => filteredOut(s) || outsideSpot(s);
	const starOf = (uuid: string | null) => (uuid == null ? undefined : index.get(uuid));
	const at = (i: number): [number, number] => [map.stars[i].x, map.stars[i].y];
	const tierOf = (s: GalaxyStar) => {
		const state = states.get(s.anime_uuid);
		return state && coverageTier(state);
	};

	/** Its "Top N%" on the ramp colourings: MAL's, or the viewer's own. */
	const rankOf = (s: GalaxyStar) =>
		colour === 'score' ? s.top_percent : colour === 'own' ? ownTop.get(s.anime_uuid) : undefined;

	function fill(s: GalaxyStar): string {
		if (colour === 'sector') return hues.get(s.sector)!;
		const rank = rankOf(s);
		if (rank != null) return colours.lerp(rankShare(rank), SCORE_RAMP);
		const tier = colour === 'mine' ? tierOf(s) : undefined;
		return tier ? mineColour(tier) : blankColour(colour, lit != null);
	}

	function starItem(s: GalaxyStar, i: number) {
		const tier = colour === 'mine' ? tierOf(s) : undefined;
		// Under a personal colouring the viewer's own stars stand out from the rest.
		const yours = personal(colour) && states.has(s.anime_uuid);
		const opacity = lit || yours ? 1 : personal(colour) ? 0.55 : s.between ? 0.45 : 0.9;
		const color = fill(s);
		const ring = tier === 'all' ? SHEEN : undefined;
		return {
			value: [s.x, s.y, i],
			// Lit stars grow, so they are easier to point at among the greyed ones.
			symbolSize: lit ? 8 : 5 + (yours ? 2 : 0),
			// A star placed onto the map rather than shaping it draws hollow.
			itemStyle: s.trained
				? { color, borderColor: ring ?? 'transparent', borderWidth: ring ? 1.2 : 0, opacity }
				: { color: 'transparent', borderColor: ring ?? color, borderWidth: 1.2, opacity }
		};
	}

	/** Groups the viewer has rated something in, for dimming the names of the unexplored. */
	function ratedPer(level: 'sector' | 'region'): Set<number> {
		const out = new Set<number>();
		for (const s of map.stars) if (states.has(s.anime_uuid)) out.add(s[level]);
		return out;
	}

	/** Where colliding names hide (`labelInside`), ECharts keeps the one whose symbol has the
	 *  larger area, so a name's invisible symbol is sized by its group, and the spotlit one's
	 *  above every group's: the map always names what it is showing. Under a pixel, so it
	 *  never catches the pointer. */
	const rankSize = (n: number) => n / (map.stars.length + 2);

	const groupsOf = (level: 'sector' | 'region') => (level === 'sector' ? map.sectors : map.regions);

	function labels(level: 'sector' | 'region') {
		const explored = personal(colour) ? ratedPer(level) : null;
		return groupsOf(level).map((g) => {
			const spotlit = spot != null && sameGroup(spot, { level, number: g.number });
			return {
				value: [g.x, g.y, g.number],
				name: g.name,
				symbolSize: rankSize(spotlit ? map.stars.length + 1 : (sizes[level].get(g.number) ?? 0)),
				label: {
					...(explored && !explored.has(g.number) ? { color: 'rgba(230,232,255,0.45)', fontStyle: 'italic' } : {}),
					// The spotlit name glows, so it is clear which one the map is showing.
					...(spotlit ? { textShadowColor: 'rgba(255,236,190,0.9)', textShadowBlur: 10 } : {})
				}
			};
		});
	}

	type Box = { x: number; y: number; width: number; height: number };

	const LEVELS = ['sector', 'region'] as const;
	/** Region names replace sector names past the region zoom. */
	const nameShown = (level: 'sector' | 'region') => names && (level === 'region') === regionsShown;

	/** A name's style per level, as drawn and as measured: a phone's are smaller and wrap sooner. */
	const nameStyle = (level: 'sector' | 'region') => ({
		overflow: 'break',
		...(level === 'sector'
			? { width: wide.current ? 200 : 130, fontSize: wide.current ? 13 : 12, fontWeight: 600 }
			: { width: wide.current ? 160 : 110, fontSize: wide.current ? 11 : 10.5, fontWeight: 500 })
	});
	const NAME_OUTLINE = { color: '#070814', width: 3 };

	/** A name's size as the map draws it, measured before ECharts lays it out. */
	const nameSizes = new Map<string, [number, number]>();
	function nameSize(level: 'sector' | 'region', text: string): [number, number] {
		const key = `${level} ${wide.current} ${text}`;
		let size = nameSizes.get(key);
		if (!size) {
			const style = { text, ...nameStyle(level), stroke: NAME_OUTLINE.color, lineWidth: NAME_OUTLINE.width };
			const box = new Text({ style }).getBoundingRect();
			size = [box.width, box.height];
			nameSizes.set(key, size);
		}
		return size;
	}

	/** The shown names' heights for this view, by their index in the series: worked out once
	 *  per layout pass, since every name in it shares the view. `render` clears it, as the
	 *  names may change. */
	let spreadView = '';
	let spreadAt = new Map<number, number>();
	function spreadNames(level: 'sector' | 'region'): Map<number, number> {
		const box: [number, number] = [chart.getWidth(), chart.getHeight()];
		const view = [level, ...axisRange(0), ...axisRange(1), ...box].join();
		if (view === spreadView) return spreadAt;
		spreadView = view;
		const placed = groupsOf(level).flatMap((g, i) => {
			const anchor = chart.convertToPixel({ gridIndex: 0 }, [g.x, g.y]);
			// Anchored off the map, a name stays off it (`labelCentre`) and makes no room.
			if (!onMap(anchor, box)) return [];
			const [width, height] = nameSize(level, g.name);
			const [x, y] = labelCentre(anchor, [width, height], box);
			return [{ i, box: { x, y, width, height } }];
		});
		const ys = spreadLabels(placed.map((p) => p.box), box[1]);
		spreadAt = new Map(placed.map((p, k) => [p.i, ys[k]]));
		return spreadAt;
	}

	/** A name sits inside the map (`labelCentre`, from its anchor `rect`, the near-zero symbol,
	 *  and `labelRect`'s size), and names that collide move apart as little as they can
	 *  (`spreadNames`), so every group keeps its name. On a phone, narrow or turned sideways,
	 *  that stacks names far from their clusters or runs out of height, so there a collision
	 *  hides the smaller group's name instead (`rankSize`), as a map does; a zoom brings it back. */
	function labelInside(level: 'sector' | 'region', p: { dataIndex: number; rect: Box; labelRect: Box }) {
		const [x, y] = labelCentre(
			[p.rect.x + p.rect.width / 2, p.rect.y + p.rect.height / 2],
			[p.labelRect.width, p.labelRect.height],
			[chart.getWidth(), chart.getHeight()]
		);
		const place = { x, y, align: 'center', verticalAlign: 'middle' };
		// Under the map's floor only on a short screen (`cls.galaxyMapHeight`).
		if (!wide.current || chart.getHeight() < cls.galaxyMapFloor) return { ...place, hideOverlap: true };
		// The hidden level's names need no room.
		if (!nameShown(level)) return place;
		return { ...place, y: spreadNames(level).get(p.dataIndex) ?? y };
	}

	// ---- the nebula: one image per look, stretched with the zoom ---------------------------
	// Each image keeps the window it was drawn over and is placed at that window's corners,
	// so a resize moves it rather than redrawing it.
	const nebulaCache = new Map<GalaxyColour, { image: HTMLCanvasElement; over: MapWindow }>();
	/** The spotlights' images, the last two only, since one per group would pile up: the
	 *  picked group's survives a hover over another name. */
	const spotImages = new Map<string, { image: HTMLCanvasElement; over: MapWindow }>();
	let nebulaStates: Map<string, State> | null = null;
	let nebulaLit: Set<string> | null = null;

	function nebulaSource(s: GalaxyStar): NebulaSource {
		const glow = (weight: number, tint: number[]) => ({ x: s.x, y: s.y, weight, tint: tint.slice(0, 3) as [number, number, number] });
		// A greyed-out star keeps the galaxy's outline in the veil and lights nothing.
		if (dimmed(s)) return { ...glow(1, [0, 0, 0]), veilOnly: true };
		if (colour === 'sector') return glow(1, colours.parse(hues.get(s.sector)!));
		const rank = rankOf(s);
		if (rank != null) return glow(0.12 + 0.88 * rankShare(rank), [90, 150, 255]);
		const tier = colour === 'mine' ? tierOf(s) : undefined;
		if (tier) return glow({ all: 1, main: 0.85, some: 0.55 }[tier], [240, 188, 78]);
		// No value in the colouring: a faint glow, in the lit teal under filters.
		if (lit) return glow(0.3, colours.parse(LIT_NO_VALUE));
		return personal(colour) ? glow(0.16, [58, 52, 80]) : glow(0.12, [60, 60, 90]);
	}

	/** Only called while drawing, which needs `win`. */
	function nebula(): { image: HTMLCanvasElement; over: MapWindow } {
		// With filters on, only the lit stars glow, in the colouring's own light. Every image
		// goes stale with the filters, the personal ones with the viewer's ratings (`ownTop`
		// arrives in the same response as `states`).
		if (lit !== nebulaLit) {
			nebulaLit = lit;
			nebulaCache.clear();
			spotImages.clear();
		}
		if (states !== nebulaStates) {
			nebulaStates = states;
			for (const key of nebulaCache.keys()) if (personal(key)) nebulaCache.delete(key);
			spotImages.clear();
		}
		const key = spotKey && `${colour} ${spotKey}`;
		const cached = key ? spotImages.get(key) : nebulaCache.get(colour);
		if (cached) return cached;
		// A dark veil on the personal colourings: the viewer's own stars are the only light.
		const veil: [number, number, number] = personal(colour) ? [70, 62, 72] : [86, 64, 170];
		const { pixels, width, height } = nebulaPixels(map.stars.map(nebulaSource), win!, 360, veil);
		const image = document.createElement('canvas');
		image.width = width;
		image.height = height;
		image.getContext('2d')!.putImageData(new ImageData(pixels, width, height), 0, 0);
		const made = { image, over: win! };
		if (key) {
			spotImages.set(key, made);
			if (spotImages.size > 2) spotImages.delete(spotImages.keys().next().value!);
		} else nebulaCache.set(colour, made);
		return made;
	}

	// ---- covers ---------------------------------------------------------------------------
	// Each cover is cut to the tiles' shape once, as the carousels' `object-cover` cuts it, at
	// the largest size a cover draws (2× for sharp screens), so the map only ever scales it.
	// An image symbol stretches a cover of another shape into its box, and keeping the
	// cover's aspect there holds only until the series next redraws.
	const POSTER_HEIGHT = 140;
	/** Cover art by URL: a canvas once loaded, null while loading or when it failed. */
	const posters = new Map<string, HTMLCanvasElement | null>();
	let posterTimer: ReturnType<typeof setTimeout> | undefined;

	function requestPoster(url: string) {
		if (posters.has(url)) return;
		posters.set(url, null);
		const img = new Image();
		img.onload = () => {
			const canvas = document.createElement('canvas');
			canvas.height = POSTER_HEIGHT;
			canvas.width = Math.round(POSTER_HEIGHT * COVER_ASPECT);
			const [sx, sy, sw, sh] = coverCrop(img.naturalWidth, img.naturalHeight, COVER_ASPECT);
			canvas.getContext('2d')!.drawImage(img, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
			posters.set(url, canvas);
			// Arrivals batch into one redraw.
			clearTimeout(posterTimer);
			posterTimer = setTimeout(() => chart?.setOption({ series: [{ id: 'covers', data: coverData() }] }), 50);
		};
		img.src = url;
	}

	/** The stars that get a cover in this view, and the zoom they were packed at. */
	let packed: number[] = [];
	let packSpan = 100;

	/** Pack this view's covers: the pick and its neighbours first, then by score. */
	function packView() {
		packed = [];
		if (!chart || !win || span > COVER_SPAN) return;
		const [x0, x1] = axisRange(0);
		const [y0, y1] = axisRange(1);
		packSpan = span;
		const rank = new Map((selected ? [selected, ...neighbours] : []).map((u, k) => [starOf(u), k]));
		const visible = map.stars
			.map((_, i) => i)
			.filter((i) => {
				const s = map.stars[i];
				// With filters on, only what they keep — plus the pick and its neighbours,
				// which the panel and the links point at whatever the filters say.
				const shown = !dimmed(s) || rank.has(i);
				return shown && s.cover_image && s.x >= x0 && s.x <= x1 && s.y >= y0 && s.y <= y1;
			})
			.sort((a, b) => (rank.get(a) ?? Infinity) - (rank.get(b) ?? Infinity) || (map.stars[b].score ?? 0) - (map.stars[a].score ?? 0));
		packed = packCovers(visible.map((i) => chart.convertToPixel({ gridIndex: 0 }, at(i))), coverSize(span)).map((k) => visible[k]);
		for (const i of packed) requestPoster(map.stars[i].cover_image!);
	}

	/** The packed covers whose art has arrived; the rest join as they load. */
	function coverData() {
		return packed.filter((i) => posters.get(map.stars[i].cover_image!)).map((i) => [...at(i), i]);
	}

	// ---- the picked star's marks ------------------------------------------------------------
	/** Its dashed links and rings; with a neighbour hovered, that one's stand out. */
	function marks() {
		const sel = starOf(selected);
		const links = [];
		const rings: { value: number[]; symbolSize: number; itemStyle?: { opacity: number } }[] =
			sel == null ? [] : [{ value: [...at(sel), sel], symbolSize: 14 }];
		if (sel != null)
			for (const u of neighbours) {
				const j = starOf(u);
				if (j == null) continue;
				const on = !hovered || u === hovered;
				links.push({ coords: [at(sel), at(j)], lineStyle: { opacity: on ? 0.9 : 0.12, width: hovered && on ? 2 : 1.2 } });
				rings.push({ value: [...at(j), j], symbolSize: hovered && on ? 13 : 9, itemStyle: { opacity: on ? 1 : 0.25 } });
			}
		return [
			{ id: 'links', data: links },
			{ id: 'focus', data: rings }
		];
	}

	// ---- zoom -----------------------------------------------------------------------------
	function zoomRange(k: number): Range {
		return chart.getModel().getComponent('dataZoom', k).getPercentRange();
	}

	/** The visible data extent of one axis. */
	function axisRange(k: 0 | 1): Range {
		const [lo, hi] = k === 0 ? win!.x : win!.y;
		const [s, e] = zoomRange(k);
		return [lo + ((hi - lo) * s) / 100, lo + ((hi - lo) * e) / 100];
	}

	/** Set while the map moves its own camera, so a gesture can tell itself apart. */
	let steering = false;

	function setWindows([x, y]: [Range, Range]) {
		steering = true;
		chart.dispatchAction({ type: 'dataZoom', batch: [x, y].map(([start, end], k) => ({ dataZoomIndex: k, start, end })) });
		steering = false;
	}

	interface View {
		x: number;
		y: number;
		width: number;
	}

	/** Show `width` percent of the map around data point (x, y), on both axes. */
	function view({ x, y, width }: View) {
		if (!chart || !win) return;
		setWindows([
			percentWindow(((x - win.x[0]) / (win.x[1] - win.x[0])) * 100, width),
			percentWindow(((y - win.y[0]) / (win.y[1] - win.y[0])) * 100, width)
		]);
	}

	function here(): View {
		const [x0, x1] = axisRange(0);
		const [y0, y1] = axisRange(1);
		return { x: (x0 + x1) / 2, y: (y0 + y1) / 2, width: span };
	}

	const whole = (): View => ({ x: (win!.x[0] + win!.x[1]) / 2, y: (win!.y[0] + win!.y[1]) / 2, width: 100 });

	let glideFrame = 0;

	/** Move the camera to `to` over a moment: the centre slides, the zoom scales evenly. */
	function glide(to: View) {
		if (!chart || !win) return;
		cancelAnimationFrame(glideFrame);
		const width = Math.max(MIN_SPAN, Math.min(100, to.width));
		const from = here();
		const start = performance.now();
		const step = (now: number) => {
			const t = Math.min(1, (now - start) / 450);
			const e = cubicInOut(t);
			view({ x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e, width: from.width * (width / from.width) ** e });
			if (t < 1) glideFrame = requestAnimationFrame(step);
		};
		glideFrame = requestAnimationFrame(step);
	}

	/** Around the picked star while there is one, so + and − keep it in view. */
	function zoomBy(factor: number) {
		const s = starOf(selected);
		const centre = s == null ? here() : { x: map.stars[s].x, y: map.stars[s].y };
		glide({ ...centre, width: span * factor });
	}

	// ---- the overview in the corner ---------------------------------------------------------
	function drawOverview() {
		// Hidden near the whole map; the settle after the zoom that shows it draws it.
		if (!overview || !win || span > 92) return;
		const dpr = devicePixelRatio || 1;
		const w = overview.clientWidth;
		const h = Math.round((w * (win.y[1] - win.y[0])) / (win.x[1] - win.x[0]));
		overview.style.height = `${h}px`;
		overview.width = w * dpr;
		overview.height = h * dpr;
		const g = overview.getContext('2d')!;
		g.scale(dpr, dpr);
		const px = (x: number, y: number) => [((x - win!.x[0]) / (win!.x[1] - win!.x[0])) * w, (1 - (y - win!.y[0]) / (win!.y[1] - win!.y[0])) * h];
		// The view's tint goes under the stars, so it never washes them out.
		const [vx0, vx1] = axisRange(0);
		const [vy0, vy1] = axisRange(1);
		const [ax, ay] = px(vx0, vy1);
		const [bx, by] = px(vx1, vy0);
		g.fillStyle = colours.modifyAlpha(GOLD, 0.12);
		g.fillRect(ax, ay, bx - ax, by - ay);
		// The spotlit group bright and larger over the rest dimmed, in a hue clear of the
		// view's gold, so all of a split group's parts show even while the view holds one.
		// The picked anime takes the same hue, larger again, since it is a single dot.
		const dot = (s: GalaxyStar, size: number) => {
			const [x, y] = px(s.x, s.y);
			g.fillRect(x - size / 2, y - size / 2, size, size);
		};
		g.fillStyle = spot ? 'rgba(230,232,255,0.18)' : 'rgba(230,232,255,0.55)';
		for (const s of map.stars) dot(s, 1.2);
		g.fillStyle = '#8fd3ff';
		if (spot) for (const s of map.stars) if (inGroup(s, spot)) dot(s, 2.2);
		const sel = starOf(selected);
		if (sel != null) dot(map.stars[sel], 4);
		g.strokeStyle = GOLD;
		g.lineWidth = 1;
		g.strokeRect(ax, ay, bx - ax, by - ay);
	}

	/** The room the overview (bottom left) and the zoom buttons (top right) take, which a
	 *  framed group keeps clear. The overview keeps its box while hidden, so it measures. */
	function clearOfControls() {
		const gap = 8;
		return {
			left: overview.offsetLeft + overview.offsetWidth + gap,
			right: container.clientWidth - controls.offsetLeft + gap
		};
	}

	function overviewClick(e: MouseEvent) {
		if (!win) return;
		const r = overview.getBoundingClientRect();
		const x = win.x[0] + ((e.clientX - r.left) / r.width) * (win.x[1] - win.x[0]);
		const y = win.y[0] + (1 - (e.clientY - r.top) / r.height) * (win.y[1] - win.y[0]);
		glide({ x, y, width: span });
	}

	// ---- the chart --------------------------------------------------------------------------
	function card(i: number): string {
		const s = map.stars[i];
		const state = states.get(s.anime_uuid);
		// The score as a search card shows it, between the state and the rank My scores colours by.
		const you = state && `${STATE_LABEL.get(state)} · ${formatScoreWithStep(scores.get(s.anime_uuid)!, ratingStep)} · Top ${ownTop.get(s.anime_uuid)}%`;
		const dim = (t: string) => `<br><span style="opacity:.7">${t}</span>`;
		const title = name(s);
		return (
			`<b>${escapeHtml(title)}</b>` +
			(title !== s.title ? dim(escapeHtml(s.title)) : '') +
			`<br>${escapeHtml(sectorName.get(s.sector) ?? '')} › ${escapeHtml(regionName.get(s.region) ?? '')}` +
			`<br>${starFigures(s)}` +
			(s.genres.length ? dim(escapeHtml(s.genres.slice(0, 6).join(', '))) : '') +
			(you ? `<br>You: ${you}` : '') +
			(s.trained ? '' : dim('Placed onto the map, not part of its fit yet'))
		);
	}

	const STAR_SERIES = ['stars', 'covers', 'focus', 'outside'];
	const greyItem = (s: GalaxyStar, i: number) => ({ value: [s.x, s.y, i], symbolSize: 4, itemStyle: { color: NO_VALUE, opacity: 0.35 } });
	/** The name series, and the group level each names. */
	const NAME_LEVEL: Record<string, 'sector' | 'region' | undefined> = { sectors: 'sector', regions: 'region' };
	/** A name spotlights its group on a hover and picks it on a click: the glow is its only
	 *  highlight, and it has no card. */
	const nameHover = { cursor: 'pointer', tooltip: { show: false }, emphasis: { disabled: true }, itemStyle: { color: 'transparent' } };

	let regionsShown = $derived(span < REGION_LABELS_BELOW);

	/** Draw the whole map; `first` also sets up its zoom. */
	function render(first = false) {
		if (!chart || !win) return;
		packView();
		const [links, rings] = marks();
		const labelStyle = { formatter: '{b}', color: 'rgba(246,247,255,0.95)', textBorderColor: NAME_OUTLINE.color, textBorderWidth: NAME_OUTLINE.width };
		spreadView = '';
		chart.setOption({
			animation: false,
			grid: { left: 0, right: 0, top: 0, bottom: 0 },
			xAxis: { type: 'value', show: false, min: win.x[0], max: win.x[1] },
			yAxis: { type: 'value', show: false, min: win.y[0], max: win.y[1] },
			...(first && {
				dataZoom: [0, 1].map((k) => ({
					type: 'inside', [k ? 'yAxisIndex' : 'xAxisIndex']: 0, filterMode: 'none', minSpan: MIN_SPAN
				}))
			}),
			tooltip: {
				...chartTooltipStyle,
				trigger: 'item',
				formatter: (q: { seriesId: string; value: number[] }) => (STAR_SERIES.includes(q.seriesId) ? card(q.value[2]) : '')
			},
			series: [
				{
					id: 'nebula', type: 'custom', silent: true, z: 0, clip: true, data: [[0, 0]],
					// eslint-disable-next-line @typescript-eslint/no-explicit-any
					renderItem: (_: unknown, api: any) => {
						const { image, over } = nebula();
						const [ax, ay] = api.coord([over.x[0], over.y[1]]);
						const [bx, by] = api.coord([over.x[1], over.y[0]]);
						return { type: 'image', style: { image, x: ax, y: ay, width: bx - ax, height: by - ay } };
					}
				},
				// Greyed by the filters, a star takes no hover; greyed by the spotlight alone it
				// can still be picked, which is how a click leaves a picked group. Two series,
				// since ECharts silences a series whole.
				{ id: 'dimmed', type: 'scatter', z: 1, silent: true, emphasis: { disabled: true }, data: map.stars.flatMap((s, i) => (filteredOut(s) ? [greyItem(s, i)] : [])) },
				{ id: 'outside', type: 'scatter', z: 1, emphasis: { disabled: true }, data: map.stars.flatMap((s, i) => (!filteredOut(s) && outsideSpot(s) ? [greyItem(s, i)] : [])) },
				{ id: 'stars', type: 'scatter', z: 2, emphasis: { disabled: true }, data: map.stars.flatMap((s, i) => (dimmed(s) ? [] : [starItem(s, i)])) },
				{ ...links, type: 'lines', coordinateSystem: 'cartesian2d', silent: true, z: 3, lineStyle: { color: GOLD, type: 'dashed' } },
				{
					id: 'covers', type: 'custom', z: 4, clip: true, emphasis: { disabled: true }, data: coverData(),
					// eslint-disable-next-line @typescript-eslint/no-explicit-any
					renderItem: (_: unknown, api: any) => {
						const s = map.stars[api.value(2)];
						const [px, py] = api.coord([s.x, s.y]);
						// Zooming out before the covers re-pack, they shrink with the map, so they
						// keep the spacing they were packed with instead of piling up.
						const k = Math.min(1, packSpan / span);
						const [w, h] = coverSize(packSpan).map((v) => v * k);
						return { type: 'image', style: { image: posters.get(s.cover_image!), x: px - w / 2, y: py - h / 2, width: w, height: h } };
					}
				},
				{ ...rings, type: 'scatter', z: 5, emphasis: { disabled: true }, itemStyle: { color: 'transparent', borderColor: GOLD, borderWidth: 2 } },
				// Names take the pointer for the spotlight; a star under one is reached by zooming.
				...LEVELS.map((level) => ({
					id: `${level}s`, type: 'scatter', z: 7, silent: !names, data: labels(level), ...nameHover,
					label: { ...labelStyle, ...nameStyle(level), show: nameShown(level) },
					labelLayout: (p: Parameters<typeof labelInside>[1]) => labelInside(level, p)
				}))
			]
		});
	}

	let fitted: [number, number] = [0, 0];

	/** Fit the map to its box; false when the box is the size it was last fitted to — a
	 *  return to the tab, which the hidden tab reports as a resize. */
	function fit(): boolean {
		const box: [number, number] = [container.clientWidth, container.clientHeight];
		if (box[0] === fitted[0] && box[1] === fitted[1]) return false;
		fitted = box;
		chart.resize();
		win = fitWindow(map.stars, ...box);
		return true;
	}

	onMount(() => {
		let disposed = false;
		let observer: ResizeObserver | undefined;
		getEcharts().then((echarts) => {
			if (disposed) return;
			colours = echarts.color;
			Text = echarts.graphic.Text;
			const instance = echarts.init(container);
			instance.on('click', (q: { seriesId: string; value: number[] }) => {
				const level = NAME_LEVEL[q.seriesId];
				if (level) onPick({ level, number: q.value[2] });
				else if (STAR_SERIES.includes(q.seriesId)) onPick(map.stars[q.value[2]].anime_uuid);
			});
			// A spotlight redraws the whole map, so a pointer passing over names on its way
			// lights none of them: only one that stays a moment does.
			instance.on('mouseover', (q: { seriesId: string; value: number[] }) => {
				const level = NAME_LEVEL[q.seriesId];
				if (!level) return;
				clearTimeout(spotTimer);
				spotTimer = setTimeout(() => (hoverSpot = { level, number: q.value[2] }), 50);
			});
			instance.on('mouseout', (q: { seriesId: string }) => {
				if (!NAME_LEVEL[q.seriesId]) return;
				clearTimeout(spotTimer);
				if (hoverSpot) hoverSpot = null;
			});
			instance.on('datazoom', () => {
				// A wheel or pinch takes the camera back from a glide.
				if (!steering) cancelAnimationFrame(glideFrame);
				const [x, y] = [zoomRange(0), zoomRange(1)];
				if (Math.abs(x[1] - x[0] - (y[1] - y[0])) > 0.01) return setWindows(evenWindows(x, y));
				span = x[1] - x[0];
				// Past the cover zoom they go at once, not when the zoom settles.
				if (span > COVER_SPAN && packed.length) {
					packed = [];
					instance.setOption({ series: [{ id: 'covers', data: [] }] });
				}
				clearTimeout(settleTimer);
				settleTimer = setTimeout(() => {
					packView();
					instance.setOption({ series: [{ id: 'covers', data: coverData() }] });
					drawOverview();
				}, 160);
			});
			observer = new ResizeObserver(() => {
				if (container.clientWidth === 0) return;
				// The first measurement hands over to the effects below, which draw the map.
				if (!chart) {
					chart = instance;
					return;
				}
				if (!fit()) return;
				render();
				drawOverview();
			});
			observer.observe(container);
		});
		return () => {
			disposed = true;
			clearTimeout(settleTimer);
			clearTimeout(posterTimer);
			clearTimeout(spotTimer);
			cancelAnimationFrame(glideFrame);
			observer?.disconnect();
			chart?.dispose();
			chart = null;
		};
	});

	// What the map shows is redrawn whole, never on the zoom or the pick: `render` reads
	// `span`, which changes on every wheel tick, so it runs untracked. Every effect below
	// needs the window and the series this one sets up, so they stay after it: effects run
	// in the order they are declared.
	let rendered = false;
	$effect(() => {
		if (!chart) return;
		void [map, colour, lit, states, ownTop, spotKey, wide.current];
		untrack(() => {
			fit();
			render(!rendered);
			rendered = true;
			drawOverview();
		});
	});

	// The pick restyles only its marks and the covers; a new one moves the camera and redraws
	// the overview, which marks it. On the first draw a star already picked (a return from
	// its page) opens there at once rather than gliding in.
	let shown: Pick | null = null;
	let placed = false;
	$effect(() => {
		if (!chart) return;
		void [selected, group, neighbours];
		untrack(() => {
			packView();
			chart.setOption({ series: [...marks(), { id: 'covers', data: coverData() }] });
			// A pick is kept as it was made, so the same one is the same object.
			const key = selected ?? group;
			if (key !== shown) {
				shown = key;
				const s = starOf(selected);
				const to =
					s != null ? { x: map.stars[s].x, y: map.stars[s].y, width: Math.min(span, FOCUS_SPAN) }
					: group ? groupView(map.stars, group, win!, container.clientWidth, clearOfControls())
					: whole();
				if (placed) glide(to);
				else view(to);
				drawOverview();
			}
			placed = true;
		});
	});

	// Hovering a neighbour restyles only the links and rings.
	$effect(() => {
		void hovered;
		if (chart) untrack(() => chart.setOption({ series: marks() }));
	});

	// The label level swaps the moment a zoom crosses it, not when the zoom settles; the names
	// button only restyles the names too.
	$effect(() => {
		if (!chart) return;
		chart.setOption({ series: LEVELS.map((level) => ({ id: `${level}s`, silent: !names, label: { show: nameShown(level) } })) });
	});
</script>


<!-- Its tip opens to the left: the buttons sit at the map's right edge. -->
{#snippet mapButton(tip: string, label: string, onclick: () => void, disabled: boolean, Icon: typeof Plus, pressed?: boolean)}
	<Tooltip text={tip} side="left">
		{#snippet trigger(props)}
			<button {...props} type="button" class="grid size-8 place-items-center rounded-lg border border-white/15 bg-[#070814]/70 text-white/85 hover:border-white/35 hover:text-white disabled:opacity-40" aria-label={label} aria-pressed={pressed} {onclick} {disabled}>
				<Icon class="size-4" />
			</button>
		{/snippet}
	</Tooltip>
{/snippet}

<div class="galaxy-sky relative {cls.galaxyMapHeight} overflow-hidden rounded-xl border border-white/10">
	<div bind:this={container} class="absolute inset-0"></div>
	<div bind:this={controls} class="absolute top-3 right-3 flex flex-col gap-1.5">
		{@render mapButton('Zoom in', 'Zoom in', () => zoomBy(0.5), span <= MIN_SPAN, Plus)}
		{@render mapButton('Zoom out', 'Zoom out', () => zoomBy(2), span >= 100, Minus)}
		{@render mapButton('Whole map', 'Show the whole map', () => glide(whole()), span >= 100, Maximize2)}
		{@render mapButton(names ? 'Hide names' : 'Show names', 'Sector and region names', () => onNames(!names), false, names ? Captions : CaptionsOff, names)}
	</div>
	<canvas
		bind:this={overview}
		class="absolute bottom-3 left-3 w-28 cursor-pointer rounded-md border border-white/15 bg-black/50 sm:w-40 {span > 92 ? 'invisible' : ''}"
		aria-label="Overview: click to move there"
		onclick={overviewClick}
	></canvas>
</div>

<style>
	/* A fixed starfield behind the map: texture that does not move with the zoom. */
	.galaxy-sky {
		background:
			radial-gradient(1px 1px at 12% 18%, rgba(230, 232, 255, 0.5), transparent),
			radial-gradient(1px 1px at 68% 32%, rgba(230, 232, 255, 0.4), transparent),
			radial-gradient(1px 1px at 35% 74%, rgba(230, 232, 255, 0.45), transparent),
			radial-gradient(1px 1px at 86% 82%, rgba(230, 232, 255, 0.35), transparent),
			radial-gradient(1.5px 1.5px at 52% 9%, rgba(230, 232, 255, 0.55), transparent),
			radial-gradient(120% 90% at 50% 40%, #121630 0%, #070814 70%);
		background-size: 220px 180px, 260px 210px, 300px 240px, 180px 150px, 340px 280px, auto;
	}
</style>
