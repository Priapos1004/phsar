// Pure, client-side statistics derived from the single GET /ratings/scores fetch.
// Every function here is total (empty input → [] / { ok: false }) and free of
// Svelte/DOM so the whole module is unit-testable. The /ratings page derives the
// anime-level list AND every statistics chart from these — no per-user backend
// stats endpoint, no scipy (the regression + correlation are closed-form below).

import { RATING_ATTRIBUTE_OPTIONS, isAttrRated, getRatingAttr, type RatingScoreItem, type WatchStatus } from '$lib/types/api';
import { formatSeason } from '$lib/utils/formatString';

/** Display + match key for a media's season, e.g. "Spring 2021"; null when undated. */
export function seasonLabel(it: RatingScoreItem): string | null {
	return formatSeason(it.anime_season_name, it.anime_season_year);
}

type NameLanguage = 'english' | 'japanese' | 'romaji';

// ── Anime-level rollup ──────────────────────────────────────────────────────
// Ratings are per-media; an anime can have several rated media (seasons, movies,
// OVAs). The list view shows one row per anime.

export interface AnimeRatingRow {
	anime_uuid: string;
	title: string;
	name_eng: string | null;
	name_jap: string | null;
	cover_image: string | null;
	/** Mean of this anime's rated-media scores (simple mean — every rated media weighs equally). */
	userScore: number;
	/** Mean of the rated media's non-null MAL scores, else null. */
	malScore: number | null;
	/** userScore − malScore (how far above/below MAL you rate it), else null. */
	malDelta: number | null;
	/** Sum of MAL vote counts across the rated media (a confidence proxy for the row). */
	scoredBy: number;
	/** Union of the rated media's genres (first-seen order). */
	genres: string[];
	/** Distinct watch statuses present across the rated media. */
	statuses: WatchStatus[];
	/** Priority-collapsed status flag for the card badge (dropped > on_hold > completed→null). */
	statusBadge: 'dropped' | 'on_hold' | null;
	ratedMediaCount: number;
	/** Rated-media counts split into the main story (main + alternative_version
	 * retellings) vs everything else (side stories, summaries, crossovers). */
	mainCount: number;
	sideCount: number;
	/** Most recent modified_at across the rated media (drives the "date rated" sort). */
	modifiedAt: string;
}

function mean(nums: number[]): number {
	return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : 0;
}

// "Main story" = the canonical chain plus alternative-version retellings; everything
// else (side stories, summaries, crossovers) counts as side.
const MAIN_RELATION_TYPES = new Set(['main', 'alternative_version']);

/** "X main · Y side" rated-media breakdown for the card + table (a count of 0 is
 * omitted, so a side-story-only anime reads "1 side"). */
export function mainSideLabel(row: AnimeRatingRow): string {
	return [row.mainCount ? `${row.mainCount} main` : null, row.sideCount ? `${row.sideCount} side` : null]
		.filter(Boolean)
		.join(' · ');
}

export function groupByAnime(items: RatingScoreItem[]): AnimeRatingRow[] {
	const groups = new Map<string, RatingScoreItem[]>();
	for (const it of items) {
		const g = groups.get(it.anime_uuid);
		if (g) g.push(it);
		else groups.set(it.anime_uuid, [it]);
	}

	const rows: AnimeRatingRow[] = [];
	for (const [anime_uuid, members] of groups) {
		const userScore = mean(members.map((m) => m.rating));
		const malScores = members.map((m) => m.mal_score).filter((s): s is number => s != null);
		const malScore = malScores.length ? mean(malScores) : null;

		// Genre union, first-seen order preserved.
		const genres: string[] = [];
		const seenGenre = new Set<string>();
		for (const m of members) {
			for (const g of m.genres) {
				if (!seenGenre.has(g)) {
					seenGenre.add(g);
					genres.push(g);
				}
			}
		}

		const statuses = [...new Set(members.map((m) => m.watch_status))];
		const statusBadge: 'dropped' | 'on_hold' | null = statuses.includes('dropped')
			? 'dropped'
			: statuses.includes('on_hold')
				? 'on_hold'
				: null;

		const mainCount = members.filter((m) => MAIN_RELATION_TYPES.has(m.relation_type)).length;

		// Anime cover, falling back to the first member's media cover when absent.
		const cover_image =
			members.find((m) => m.anime_cover_image)?.anime_cover_image ??
			members.find((m) => m.media_cover_image)?.media_cover_image ??
			null;

		const first = members[0];
		rows.push({
			anime_uuid,
			title: first.anime_title,
			name_eng: first.anime_name_eng,
			name_jap: first.anime_name_jap,
			cover_image,
			userScore,
			malScore,
			malDelta: malScore != null ? userScore - malScore : null,
			scoredBy: members.reduce((a, m) => a + m.scored_by, 0),
			genres,
			statuses,
			statusBadge,
			ratedMediaCount: members.length,
			mainCount,
			sideCount: members.length - mainCount,
			modifiedAt: members.reduce((a, m) => (m.modified_at > a ? m.modified_at : a), first.modified_at),
		});
	}
	return rows;
}

// ── List filtering / sorting / banding ──────────────────────────────────────

export interface RatingFilters {
	genres: string[];
	genreMode: 'any' | 'all';
	ageRatings: number[]; // any-match against age_rating_numeric; [] = no age filter
	seasons: string[]; // any-match against the media's "Spring 2021" season; [] = no filter
}

/** Filter the per-media items BEFORE grouping (genre + age + season act per media;
 * the filters AND together, so an anime survives if it has ≥1 media matching all). */
export function filterItems(items: RatingScoreItem[], f: RatingFilters): RatingScoreItem[] {
	if (!f.genres.length && !f.ageRatings.length && !f.seasons.length) return items;
	return items.filter((it) => {
		if (f.genres.length) {
			const has = (g: string) => it.genres.includes(g);
			if (f.genreMode === 'all' ? !f.genres.every(has) : !f.genres.some(has)) return false;
		}
		if (f.ageRatings.length && (it.age_rating_numeric == null || !f.ageRatings.includes(it.age_rating_numeric)))
			return false;
		if (f.seasons.length) {
			const s = seasonLabel(it);
			if (s == null || !f.seasons.includes(s)) return false;
		}
		return true;
	});
}

export type SortKey = 'score' | 'title' | 'date' | 'mal' | 'malDelta' | 'status';

function titleOf(r: AnimeRatingRow, lang: NameLanguage): string {
	if (lang === 'japanese' && r.name_jap) return r.name_jap;
	if (lang === 'english' && r.name_eng) return r.name_eng;
	return r.title;
}

// Ascending status order: dropped < on hold < completed.
function statusRank(r: AnimeRatingRow): number {
	return r.statusBadge === 'dropped' ? 0 : r.statusBadge === 'on_hold' ? 1 : 2;
}

// Compare two nullable numbers, sending nulls to the end regardless of direction.
function cmpNullable(a: number | null, b: number | null, dir: 'asc' | 'desc'): number {
	if (a == null && b == null) return 0;
	if (a == null) return dir === 'asc' ? 1 : -1;
	if (b == null) return dir === 'asc' ? 1 : -1;
	return a - b;
}

export function sortAnimeRows(
	rows: AnimeRatingRow[],
	key: SortKey,
	dir: 'asc' | 'desc',
	nameLanguage: NameLanguage,
): AnimeRatingRow[] {
	const sign = dir === 'asc' ? 1 : -1;
	const cmp = (a: AnimeRatingRow, b: AnimeRatingRow): number => {
		switch (key) {
			case 'title':
				return titleOf(a, nameLanguage).localeCompare(titleOf(b, nameLanguage));
			case 'date':
				return a.modifiedAt < b.modifiedAt ? -1 : a.modifiedAt > b.modifiedAt ? 1 : 0;
			case 'status':
				return statusRank(a) - statusRank(b);
			case 'mal':
				return cmpNullable(a.malScore, b.malScore, dir);
			case 'malDelta':
				return cmpNullable(a.malDelta, b.malDelta, dir);
			case 'score':
			default:
				return a.userScore - b.userScore;
		}
	};
	// Stable title tiebreak so equal primary keys read predictably.
	return [...rows].sort((a, b) => {
		const primary = cmp(a, b) * sign;
		if (primary !== 0) return primary;
		return titleOf(a, nameLanguage).localeCompare(titleOf(b, nameLanguage));
	});
}

export interface ScoreBand {
	band: number; // floor of the score (10, 9, …)
	word: string; // qualitative label ("Great") — view composes its own header
	rows: AnimeRatingRow[];
}

const BAND_WORD: Record<number, string> = {
	10: 'Masterpiece',
	9: 'Great',
	8: 'Very good',
	7: 'Good',
	6: 'Solid',
	5: 'Decent', // lowest score still worth recommending
	4: 'Mixed',
	3: 'Bad',
	2: 'Awful',
	1: 'Terrible',
	0: 'Unwatchable',
};

/** Group anime rows into integer-score bands, highest first, omitting empty bands.
 * `rows` should already be in the desired within-band order (the caller sorts). */
export function toScoreBands(rows: AnimeRatingRow[]): ScoreBand[] {
	const buckets = new Map<number, AnimeRatingRow[]>();
	for (const r of rows) {
		const band = Math.min(10, Math.max(0, Math.floor(r.userScore)));
		const b = buckets.get(band);
		if (b) b.push(r);
		else buckets.set(band, [r]);
	}
	return [...buckets.keys()]
		.sort((a, b) => b - a)
		.map((band) => ({ band, word: BAND_WORD[band] ?? '', rows: buckets.get(band)! }));
}

// ── Score distribution ──────────────────────────────────────────────────────

export interface HistogramBucket {
	center: number;
	count: number;
	main: number; // count split by relation type (main = main + alternative_version)
	side: number;
}

// Fixed 0.5-wide buckets across the 0–10 scale: a finer width (0.1/0.25) would blow
// past a legible bar count for any wide-spread library, so 0.5 is what shows in
// practice — we just always use it. 0.5 → 1-decimal axis labels.
export const SCORE_HISTOGRAM_WIDTH = 0.5;

/**
 * Histogram of raw per-media scores in fixed 0.5-wide buckets (scores snapped to the
 * nearest 0.5). Buckets are contiguous (empty ones filled with 0) so the x-axis stays
 * evenly spaced and gaps read as gaps — never collapsing two distinct scores into one bar.
 */
export function scoreHistogram(items: RatingScoreItem[]): HistogramBucket[] {
	if (!items.length) return [];
	const w = SCORE_HISTOGRAM_WIDTH;
	const snap = (v: number) => Math.round(v / w) * w;
	// Single pass for the range — avoids a throwaway array + Math.min/max(...spread),
	// which has a call-stack ceiling on large libraries.
	let lo = Infinity;
	let hi = -Infinity;
	for (const it of items) {
		if (it.rating < lo) lo = it.rating;
		if (it.rating > hi) hi = it.rating;
	}
	const loCenter = snap(lo);
	const steps = Math.round((snap(hi) - loCenter) / w);
	const buckets: HistogramBucket[] = Array.from({ length: steps + 1 }, (_, i) => ({
		center: Math.round((loCenter + i * w) * 100) / 100,
		count: 0,
		main: 0,
		side: 0,
	}));
	for (const it of items) {
		const b = buckets[Math.round((snap(it.rating) - loCenter) / w)];
		b.count++;
		if (MAIN_RELATION_TYPES.has(it.relation_type)) b.main++;
		else b.side++;
	}
	return buckets;
}

// ── You vs MAL alignment ─────────────────────────────────────────────────────

export interface AlignmentPoint {
	x: number; // MAL score
	y: number; // user rating
	w: number; // confidence weight = log10(scored_by + 1)
	mediaUuid: string; // → media detail page on click
	// Raw title fields so the consumer can resolve to the user's name language.
	title: string;
	nameEng: string | null;
	nameJap: string | null;
}

/** Per-media points (only media with a MAL score). Weight = log10(scored_by + 1),
 * the shared confidence weight used across search ranking. */
export function alignmentPoints(items: RatingScoreItem[]): AlignmentPoint[] {
	return items
		.filter((it) => it.mal_score != null)
		.map((it) => ({
			x: it.mal_score as number,
			y: it.rating,
			w: Math.log10((it.scored_by ?? 0) + 1),
			mediaUuid: it.media_uuid,
			title: it.media_title,
			nameEng: it.media_name_eng,
			nameJap: it.media_name_jap,
		}));
}

export interface WeightedFit {
	slope: number;
	intercept: number;
	r2: number;
	n: number;
	ok: boolean;
}

/** Weighted least-squares fit y ≈ slope·x + intercept with weights w.
 * Closed form: a = Sxy/Sxx, b = ȳ − a·x̄, R² = Sxy²/(Sxx·Syy).
 * ok=false when n<2, all weights 0, or x/y has zero (weighted) variance. */
export function weightedLinearFit(pts: { x: number; y: number; w: number }[]): WeightedFit {
	const fail: WeightedFit = { slope: 0, intercept: 0, r2: 0, n: pts.length, ok: false };
	if (pts.length < 2) return fail;
	const W = pts.reduce((a, p) => a + p.w, 0);
	if (W <= 0) return fail;
	const xbar = pts.reduce((a, p) => a + p.w * p.x, 0) / W;
	const ybar = pts.reduce((a, p) => a + p.w * p.y, 0) / W;
	let Sxx = 0;
	let Syy = 0;
	let Sxy = 0;
	for (const p of pts) {
		const dx = p.x - xbar;
		const dy = p.y - ybar;
		Sxx += p.w * dx * dx;
		Syy += p.w * dy * dy;
		Sxy += p.w * dx * dy;
	}
	if (Sxx === 0 || Syy === 0) return fail;
	const slope = Sxy / Sxx;
	const intercept = ybar - slope * xbar;
	const r2 = (Sxy * Sxy) / (Sxx * Syy);
	return { slope, intercept, r2, n: pts.length, ok: true };
}

export interface SpearmanResult {
	rho: number;
	n: number;
	ok: boolean;
}

/** Average ranks (1-based), ties share the mean of their rank positions. */
function averageRanks(values: number[]): number[] {
	const idx = values.map((v, i) => ({ v, i })).sort((a, b) => a.v - b.v);
	const ranks = new Array<number>(values.length);
	let i = 0;
	while (i < idx.length) {
		let j = i;
		while (j + 1 < idx.length && idx[j + 1].v === idx[i].v) j++;
		const avg = (i + j) / 2 + 1; // positions i..j → mean rank (1-based)
		for (let k = i; k <= j; k++) ranks[idx[k].i] = avg;
		i = j + 1;
	}
	return ranks;
}

/** Spearman rank correlation (monotonicity), = Pearson on average-ranks.
 * Unweighted by design — it's a rank correlation; the confidence weighting is
 * for the scatter/regression display only. ok=false on n<3 or zero rank variance. */
export function spearman(pairs: { x: number; y: number }[]): SpearmanResult {
	const fail: SpearmanResult = { rho: 0, n: pairs.length, ok: false };
	if (pairs.length < 3) return fail;
	const rx = averageRanks(pairs.map((p) => p.x));
	const ry = averageRanks(pairs.map((p) => p.y));
	const n = pairs.length;
	const mx = rx.reduce((a, b) => a + b, 0) / n;
	const my = ry.reduce((a, b) => a + b, 0) / n;
	let sxy = 0;
	let sxx = 0;
	let syy = 0;
	for (let i = 0; i < n; i++) {
		const dx = rx[i] - mx;
		const dy = ry[i] - my;
		sxy += dx * dy;
		sxx += dx * dx;
		syy += dy * dy;
	}
	if (sxx === 0 || syy === 0) return fail;
	return { rho: sxy / Math.sqrt(sxx * syy), n, ok: true };
}

// ── Genre / studio breakdowns (one implementation, keyed on the tag field) ───

export type TagDim = 'genres' | 'studios';

export interface TagAvg {
	tag: string;
	avg: number;
	count: number;
}

export interface TagStatusBreakdown {
	tag: string;
	completed: number;
	onHold: number;
	dropped: number;
	total: number;
}

/** Collect (tag → rating[]) once; genre + studio breakdowns reuse it. */
function bucketByTag(items: RatingScoreItem[], dim: TagDim): Map<string, RatingScoreItem[]> {
	const map = new Map<string, RatingScoreItem[]>();
	for (const it of items) {
		for (const tag of it[dim]) {
			const b = map.get(tag);
			if (b) b.push(it);
			else map.set(tag, [it]);
		}
	}
	return map;
}

/** Average score per tag (genre or studio), highest first. */
export function tagAvg(items: RatingScoreItem[], dim: TagDim): TagAvg[] {
	return [...bucketByTag(items, dim).entries()]
		.map(([tag, rs]) => ({ tag, avg: mean(rs.map((r) => r.rating)), count: rs.length }))
		.sort((a, b) => b.avg - a.avg || b.count - a.count);
}

/** Per-tag watch-status counts ("what you watch most" + how much you finish vs
 * drop, in one stacked bar). Replaces separate frequency + dropped-rate plots:
 * a tag with 5 dropped out of 200 reads as a small red segment on a long bar
 * instead of a lonely 2.5% stamp. Sorted by total (most-rated first). */
export function tagStatusBreakdown(items: RatingScoreItem[], dim: TagDim): TagStatusBreakdown[] {
	return [...bucketByTag(items, dim).entries()]
		.map(([tag, rs]) => {
			let completed = 0;
			let onHold = 0;
			let dropped = 0;
			for (const r of rs) {
				if (r.watch_status === 'completed') completed++;
				else if (r.watch_status === 'on_hold') onHold++;
				else dropped++;
			}
			return { tag, completed, onHold, dropped, total: rs.length };
		})
		.sort((a, b) => b.total - a.total || a.tag.localeCompare(b.tag));
}

// ── Attribute analysis ───────────────────────────────────────────────────────
// Averaging ordinal/nominal attributes (the old radar/bars) isn't meaningful, so
// instead we measure how each attribute RELATES to the score.

// Ordinal attributes have a natural low→high order (read off RATING_ATTRIBUTE_OPTIONS).
export const ORDINAL_ATTR_KEYS = [
	'animation_quality',
	'story_quality',
	'character_depth',
	'dialogue_quality',
	'ending_quality',
	'pace',
	'fan_service',
	'originality',
	'has_3d_animation',
] as const;
// Nominal attributes have no order — a mean over codes is meaningless, so we look
// at per-category mean scores instead.
export const NOMINAL_ATTR_KEYS = ['watched_format', 'ending_type'] as const;

const MIN_ATTR_SAMPLES = 5;

export interface AttributeCorrelation {
	key: string;
	rho: number; // Spearman rank correlation of the ordinal level vs your rating (−1…1)
	n: number;
}

/** For each ordinal attribute, how strongly its level tracks your score (signed
 * Spearman ρ). Answers "does higher animation quality raise my rating more than
 * higher story quality?". Sorted by |ρ|; attributes with <5 rated samples or no
 * variation are dropped (spearman returns ok=false). */
export function attributeCorrelations(items: RatingScoreItem[]): AttributeCorrelation[] {
	const out: AttributeCorrelation[] = [];
	for (const key of ORDINAL_ATTR_KEYS) {
		const order = RATING_ATTRIBUTE_OPTIONS[key].options
			.map((o) => o.value)
			.filter((v) => v !== 'not_applicable');
		const rank = new Map(order.map((v, i) => [v, i] as const));
		const pairs: { x: number; y: number }[] = [];
		for (const it of items) {
			const v = getRatingAttr(it, key);
			if (v && isAttrRated(v) && rank.has(v)) pairs.push({ x: rank.get(v)!, y: it.rating });
		}
		const r = spearman(pairs);
		if (r.ok && r.n >= MIN_ATTR_SAMPLES) out.push({ key, rho: r.rho, n: r.n });
	}
	return out.sort((a, b) => Math.abs(b.rho) - Math.abs(a.rho));
}

export interface CategoryEffect {
	value: string;
	mean: number;
	count: number;
	delta: number; // mean − your overall mean for ratings carrying this attribute
}

export interface NominalAttributeEffect {
	key: string;
	overallMean: number;
	eta: number; // correlation ratio (0…1): share of score spread this attribute explains
	n: number;
	categories: CategoryEffect[];
}

/** For each nominal attribute, the mean score per category vs your overall mean
 * ("when the ending is open, you score ~0.6 higher"). `eta` (correlation ratio)
 * gives a single 0…1 magnitude of how much the attribute explains your score
 * spread, so a near-0 eta says "this doesn't really move your scores". */
export function attributeCategoryEffects(items: RatingScoreItem[]): NominalAttributeEffect[] {
	const out: NominalAttributeEffect[] = [];
	for (const key of NOMINAL_ATTR_KEYS) {
		const rated = items.filter((it) => {
			const v = getRatingAttr(it, key);
			return !!v && isAttrRated(v);
		});
		if (rated.length < MIN_ATTR_SAMPLES) continue;

		const overallMean = mean(rated.map((r) => r.rating));
		const byVal = new Map<string, number[]>();
		for (const it of rated) {
			const v = getRatingAttr(it, key)!;
			const b = byVal.get(v);
			if (b) b.push(it.rating);
			else byVal.set(v, [it.rating]);
		}
		const categories: CategoryEffect[] = [...byVal.entries()]
			.map(([value, rs]) => ({ value, mean: mean(rs), count: rs.length, delta: mean(rs) - overallMean }))
			.sort((a, b) => b.mean - a.mean);

		// eta = sqrt(SS_between / SS_total)
		let ssTotal = 0;
		let ssBetween = 0;
		for (const it of rated) ssTotal += (it.rating - overallMean) ** 2;
		for (const [, rs] of byVal) ssBetween += rs.length * (mean(rs) - overallMean) ** 2;
		const eta = ssTotal > 0 ? Math.sqrt(ssBetween / ssTotal) : 0;

		out.push({ key, overallMean, eta, n: rated.length, categories });
	}
	return out.sort((a, b) => b.eta - a.eta);
}

// ── Rating trend over the sequence of ratings ────────────────────────────────

function byCreatedAsc(a: RatingScoreItem, b: RatingScoreItem): number {
	return a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0;
}

export interface SequencePoint {
	index: number; // 1-based position in chronological rating order
	score: number;
	title: string;
	date: string;
}

/** Your scores in the order you rated them (equidistant on the x-axis, not by
 * calendar date) — the substrate for a moving-average trend line. */
export function ratingSequence(items: RatingScoreItem[]): SequencePoint[] {
	return [...items]
		.sort(byCreatedAsc)
		.map((it, i) => ({ index: i + 1, score: it.rating, title: it.media_title, date: it.created_at }));
}

/** Trailing simple moving average. Window is clamped to [1, values.length]; the
 * first window−1 points average over what's available so the line has no gap. */
export function movingAverage(values: number[], window: number): number[] {
	if (!values.length) return [];
	const w = Math.max(1, Math.min(Math.round(window), values.length));
	const out: number[] = [];
	for (let i = 0; i < values.length; i++) {
		const start = Math.max(0, i - w + 1);
		const slice = values.slice(start, i + 1);
		out.push(slice.reduce((a, b) => a + b, 0) / slice.length);
	}
	return out;
}

// ── Cumulative watch time over (rating) time ─────────────────────────────────

export interface CumulativePoint {
	date: string; // the rating's created_at
	seconds: number; // cumulative completed watch time up to and including this point
}

/** Cumulative completed watch time plotted against when you rated each title.
 * The slope is your watch pace — steep early (back-cataloguing), then settling
 * to your ongoing rate. `sinceISO` clips the x-axis to a recent window while
 * keeping the y-values absolute, so the recent slope stays truthful. */
export function cumulativeWatchTime(items: RatingScoreItem[], sinceISO?: string): CumulativePoint[] {
	const sorted = items.filter((it) => it.watch_status === 'completed').sort(byCreatedAsc);
	let cum = 0;
	const pts = sorted.map((it) => {
		cum += it.total_watch_time ?? 0;
		return { date: it.created_at, seconds: cum };
	});
	return sinceISO ? pts.filter((p) => p.date >= sinceISO) : pts;
}

// ── Watch time ───────────────────────────────────────────────────────────────

/** Total completed watch time in seconds. Counts only completed ratings (an
 * on-hold/dropped series wasn't fully watched); uses the catalog
 * total_watch_time (episodes × duration) as the per-media estimate. The
 * over-time view is the cumulative chart below. */
export function totalWatchTime(items: RatingScoreItem[]): number {
	return items.reduce((a, it) => (it.watch_status === 'completed' ? a + (it.total_watch_time ?? 0) : a), 0);
}

