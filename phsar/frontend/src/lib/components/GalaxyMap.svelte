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
	 * The camera follows `selected`: picking a star glides to it, close enough for the
	 * covers, and letting go of it glides back out to the whole map.
	 */
	import { onMount, untrack } from 'svelte';
	import { cubicInOut } from 'svelte/easing';
	import { Maximize2, Minus, Plus } from 'lucide-svelte';
	import { getEcharts } from '$lib/echarts';
	import { chartTooltipStyle } from '$lib/utils/chartTheme';
	import { COVERAGE_STYLE, coverageTier } from '$lib/utils/ratingCoverage';
	import { RATED_STATES } from '$lib/utils/search';
	import { escapeHtml, resolveTitle } from '$lib/utils/formatString';
	import {
		COVER_ASPECT, COVER_SPAN, FOCUS_SPAN, MIN_SPAN, NO_VALUE, REGION_LABELS_BELOW, SCORE_RAMP,
		coverCrop, coverSize, evenWindows, fitWindow, labelCentre, mineColour, nebulaPixels, packCovers, percentWindow,
		rankShare, sectorHues, starFigures,
		type GalaxyColour,
		type MapWindow, type NebulaSource
	} from '$lib/utils/galaxy';
	import type { AnimeRatingCoverage, GalaxyMap, GalaxyStar } from '$lib/types/api';

	type State = AnimeRatingCoverage['state'];
	type Range = [number, number];

	interface Props {
		map: GalaxyMap;
		colour: GalaxyColour;
		/** A genre to light up, or '' for none. */
		tag: string;
		states: Map<string, State>;
		selected: string | null;
		neighbours: string[];
		/** The neighbour the panel's pointer is on, whose link stands out. */
		hovered: string | null;
		nameLanguage: 'english' | 'japanese' | 'romaji';
		onSelect: (uuid: string) => void;
	}

	let { map, colour, tag, states, selected, neighbours, hovered, nameLanguage, onSelect }: Props = $props();

	let container: HTMLDivElement;
	let overview: HTMLCanvasElement;
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	let chart = $state<any>(null);
	/** ECharts' own colour helpers, from the bundle the chart loads. */
	let colours: { lerp(t: number, stops: string[]): string; parse(c: string): number[]; modifyAlpha(c: string, a: number): string };
	let win: MapWindow | null = null;
	/** The visible share of the map's width, in percent. */
	let span = $state(100);
	let settleTimer: ReturnType<typeof setTimeout> | undefined;

	let index = $derived(new Map(map.stars.map((s, i) => [s.anime_uuid, i])));
	let hues = $derived(sectorHues(map.sectors));
	let sectorName = $derived(new Map(map.sectors.map((g) => [g.number, g.name])));
	let regionName = $derived(new Map(map.regions.map((g) => [g.number, g.name])));
	const STATE_LABEL = new Map(RATED_STATES.anime.map((s) => [s.value, s.label]));
	const SHEEN = COVERAGE_STYLE.all.hairline!;
	const GOLD = '#f2c46d';

	const name = (s: GalaxyStar) => resolveTitle(s.title, s.name_eng, s.name_jap, nameLanguage);
	const lit = (s: GalaxyStar) => !tag || s.genres.includes(tag);
	const starOf = (uuid: string | null) => (uuid == null ? undefined : index.get(uuid));
	const at = (i: number): [number, number] => [map.stars[i].x, map.stars[i].y];
	const tierOf = (s: GalaxyStar) => {
		const state = states.get(s.anime_uuid);
		return state && coverageTier(state);
	};

	function fill(s: GalaxyStar): string {
		if (colour === 'score') return s.top_percent == null ? NO_VALUE : colours.lerp(rankShare(s.top_percent), SCORE_RAMP);
		if (colour === 'mine') return mineColour(tierOf(s));
		return hues.get(s.sector)!;
	}

	function starItem(s: GalaxyStar, i: number) {
		const tier = colour === 'mine' ? tierOf(s) : undefined;
		const opacity = tag ? (lit(s) ? 1 : 0.1) : colour === 'mine' ? (tier ? 1 : 0.55) : s.between ? 0.45 : 0.9;
		const color = fill(s);
		const ring = tier === 'all' ? SHEEN : undefined;
		return {
			value: [s.x, s.y, i],
			symbolSize: 5 + (tier || (tag && lit(s)) ? 2 : 0),
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

	function labels(level: 'sector' | 'region') {
		const groups = level === 'sector' ? map.sectors : map.regions;
		const explored = colour === 'mine' ? ratedPer(level) : null;
		return groups.map((g) => ({
			value: [g.x, g.y],
			name: g.name,
			label: explored && !explored.has(g.number) ? { color: 'rgba(230,232,255,0.45)', fontStyle: 'italic' } : undefined
		}));
	}

	type Box = { x: number; y: number; width: number; height: number };

	/** A name anchored near the edge slides inward instead of running off the map:
	 *  `labelCentre` places it from its anchor (`rect`, the zero-size symbol) and
	 *  `labelRect`'s size. */
	function labelInside(p: { rect: Box; labelRect: Box }) {
		const [x, y] = labelCentre(
			[p.rect.x + p.rect.width / 2, p.rect.y + p.rect.height / 2],
			[p.labelRect.width, p.labelRect.height],
			[chart.getWidth(), chart.getHeight()]
		);
		return { hideOverlap: true, x, y, align: 'center', verticalAlign: 'middle' };
	}

	// ---- the nebula: one image per look, stretched with the zoom ---------------------------
	// Each image keeps the window it was drawn over and is placed at that window's corners,
	// so a resize moves it rather than redrawing it.
	const nebulaCache = new Map<string, { image: HTMLCanvasElement; over: MapWindow }>();
	let nebulaStates: Map<string, State> | null = null;

	function nebulaSource(s: GalaxyStar): NebulaSource {
		const glow = (weight: number, tint: number[]) => ({ x: s.x, y: s.y, weight, tint: tint.slice(0, 3) as [number, number, number] });
		if (tag) return lit(s) ? glow(1, [255, 110, 200]) : glow(0.12, [60, 52, 96]);
		if (colour === 'mine') {
			const tier = tierOf(s);
			return tier ? glow({ all: 1, main: 0.85, some: 0.55 }[tier], [240, 188, 78]) : glow(0.16, [58, 52, 80]);
		}
		if (colour === 'score') return s.top_percent == null ? glow(0.12, [60, 60, 90]) : glow(0.12 + 0.88 * rankShare(s.top_percent), [90, 150, 255]);
		return glow(1, colours.parse(hues.get(s.sector)!));
	}

	/** Only called while drawing, which needs `win`. */
	function nebula(): { image: HTMLCanvasElement; over: MapWindow } {
		// A lit genre looks the same under every colouring; only My ratings' image goes stale
		// with the viewer's ratings.
		const key = tag ? `tag|${tag}` : colour;
		if (states !== nebulaStates) {
			nebulaStates = states;
			nebulaCache.delete('mine');
		}
		const cached = nebulaCache.get(key);
		if (cached) return cached;
		// Black and gold on My ratings: the viewer's own stars are the only light.
		const veil: [number, number, number] = key === 'mine' ? [70, 62, 72] : [86, 64, 170];
		const { pixels, width, height } = nebulaPixels(map.stars.map(nebulaSource), win!, 360, veil);
		const image = document.createElement('canvas');
		image.width = width;
		image.height = height;
		image.getContext('2d')!.putImageData(new ImageData(pixels, width, height), 0, 0);
		const made = { image, over: win! };
		nebulaCache.set(key, made);
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
				return s.cover_image && s.x >= x0 && s.x <= x1 && s.y >= y0 && s.y <= y1;
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
		g.fillStyle = 'rgba(230,232,255,0.55)';
		for (const s of map.stars) {
			const [x, y] = px(s.x, s.y);
			g.fillRect(x, y, 1.2, 1.2);
		}
		const [vx0, vx1] = axisRange(0);
		const [vy0, vy1] = axisRange(1);
		const [ax, ay] = px(vx0, vy1);
		const [bx, by] = px(vx1, vy0);
		g.fillStyle = colours.modifyAlpha(GOLD, 0.12);
		g.strokeStyle = GOLD;
		g.lineWidth = 1;
		g.fillRect(ax, ay, bx - ax, by - ay);
		g.strokeRect(ax, ay, bx - ax, by - ay);
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
		const dim = (t: string) => `<br><span style="opacity:.7">${t}</span>`;
		const title = name(s);
		return (
			`<b>${escapeHtml(title)}</b>` +
			(title !== s.title ? dim(escapeHtml(s.title)) : '') +
			`<br>${escapeHtml(sectorName.get(s.sector) ?? '')} › ${escapeHtml(regionName.get(s.region) ?? '')}` +
			`<br>${starFigures(s)}` +
			(s.genres.length ? dim(escapeHtml(s.genres.slice(0, 6).join(', '))) : '') +
			(state ? `<br>You: ${STATE_LABEL.get(state)}` : '') +
			(s.trained ? '' : dim('Placed onto the map, not part of its fit yet'))
		);
	}

	const STAR_SERIES = ['stars', 'covers', 'focus'];

	let regionsShown = $derived(span < REGION_LABELS_BELOW);

	/** Draw the whole map; `first` also sets up its zoom. */
	function render(first = false) {
		if (!chart || !win) return;
		packView();
		const [links, rings] = marks();
		const labelStyle = { show: true, formatter: '{b}', color: 'rgba(246,247,255,0.95)', textBorderColor: '#070814', textBorderWidth: 3, overflow: 'break' };
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
				{ id: 'stars', type: 'scatter', z: 2, emphasis: { disabled: true }, data: map.stars.map(starItem) },
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
				{
					id: 'sectors', type: 'scatter', symbolSize: 0, silent: true, z: 7, data: labels('sector'),
					label: { ...labelStyle, width: 200, fontSize: 13, fontWeight: 600, opacity: regionsShown ? 0.28 : 1 },
					labelLayout: labelInside
				},
				{
					id: 'regions', type: 'scatter', symbolSize: 0, silent: true, z: 7, data: labels('region'),
					label: { ...labelStyle, width: 160, show: regionsShown, fontSize: 11, fontWeight: 500 },
					labelLayout: labelInside
				}
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
			const instance = echarts.init(container);
			instance.on('click', (q: { seriesId: string; value: number[] }) => {
				if (STAR_SERIES.includes(q.seriesId)) onSelect(map.stars[q.value[2]].anime_uuid);
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
		void [map, colour, tag, states];
		untrack(() => {
			fit();
			render(!rendered);
			rendered = true;
		});
	});

	// The pick restyles only its marks and the covers, then moves the camera. On the first
	// draw a star already picked (a return from its page) opens there at once rather than
	// gliding in.
	let shown: string | null = null;
	let placed = false;
	$effect(() => {
		if (!chart) return;
		void [selected, neighbours];
		untrack(() => {
			packView();
			chart.setOption({ series: [...marks(), { id: 'covers', data: coverData() }] });
			if (selected !== shown) {
				shown = selected;
				const s = starOf(selected);
				const to = s == null ? whole() : { x: map.stars[s].x, y: map.stars[s].y, width: Math.min(span, FOCUS_SPAN) };
				if (placed) glide(to);
				else view(to);
			}
			placed = true;
		});
	});

	// Hovering a neighbour restyles only the links and rings.
	$effect(() => {
		void hovered;
		if (chart) untrack(() => chart.setOption({ series: marks() }));
	});

	// The label level swaps the moment a zoom crosses it, not when the zoom settles.
	$effect(() => {
		if (!chart) return;
		chart.setOption({
			series: [
				{ id: 'sectors', label: { opacity: regionsShown ? 0.28 : 1 } },
				{ id: 'regions', label: { show: regionsShown } }
			]
		});
	});
</script>


<div class="galaxy-sky relative h-[70vh] min-h-[420px] overflow-hidden rounded-xl border border-white/10">
	<div bind:this={container} class="absolute inset-0"></div>
	<div class="absolute top-3 right-3 flex flex-col gap-1.5">
		<button type="button" class="map-button" aria-label="Zoom in" title="Zoom in" onclick={() => zoomBy(0.5)} disabled={span <= MIN_SPAN}>
			<Plus class="size-4" />
		</button>
		<button type="button" class="map-button" aria-label="Zoom out" title="Zoom out" onclick={() => zoomBy(2)} disabled={span >= 100}>
			<Minus class="size-4" />
		</button>
		<button type="button" class="map-button" aria-label="Show the whole map" title="Whole map" onclick={() => glide(whole())} disabled={span >= 100}>
			<Maximize2 class="size-4" />
		</button>
	</div>
	<canvas
		bind:this={overview}
		class="absolute bottom-3 left-3 w-28 cursor-pointer rounded-md border border-white/15 bg-black/50 sm:w-40"
		hidden={span > 92}
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
	.map-button {
		display: grid;
		place-items: center;
		width: 2rem;
		height: 2rem;
		border-radius: 0.5rem;
		border: 1px solid rgb(255 255 255 / 0.15);
		background: rgb(7 8 20 / 0.7);
		color: rgb(255 255 255 / 0.85);
	}
	.map-button:hover:not(:disabled) {
		border-color: rgb(255 255 255 / 0.35);
		color: white;
	}
	.map-button:disabled {
		opacity: 0.35;
	}
</style>
