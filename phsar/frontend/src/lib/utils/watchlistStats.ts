// Pure helpers for the /watchlist overview list tab. Watchlist entries are per-media,
// but the overview can show them at MEDIA grain (one card per entry) or ANIME grain (one
// card per anime, aggregating its watchlisted media — gradient bookmark when it spans
// tags). Both grains normalize to a `WatchlistRow` so one grid/card/table serves both.
import { buildDetailHref } from '$lib/utils/navigation';
import { formatDurationCompact, formatRelationType, resolveTitle } from '$lib/utils/formatString';
import { priorityLabel, watchtimeTint } from '$lib/utils/watchlist';
import { MAIN_RELATIONS, mainSideLabel } from '$lib/utils/relations';
import { SEASON_ORDER } from '$lib/utils/getSeason';
import { isAvailable, isReady, matchesFilter, statusByAnime, type ReadyFilterKey, type ReadyStatus } from '$lib/utils/watchlistReady';
import type { WatchlistItem } from '$lib/types/api';

export type WatchlistView = 'grid' | 'table';
export type WatchlistGrain = 'anime' | 'media';
export type WatchlistSortKey = 'title' | 'priority' | 'date' | 'note' | 'time';
export type NameLanguage = 'english' | 'japanese' | 'romaji';

/** Every list-tab control, in one object. It lives here rather than with the store that
 *  holds it because `buildWatchlistView` takes it and the store already draws its field
 *  types from this module — the other direction would be a cycle, and the store is
 *  reachable from the root layout, so it must not pull this module into every entry chunk. */
export interface WatchlistFilterState {
	view: WatchlistView;
	grain: WatchlistGrain; // anime (default, aggregated) vs media (one card per entry)
	tagUuids: string[]; // multi-select union — [] = all tags
	priorities: number[]; // multi-select union of priority bands — [] = all
	readiness: ReadyFilterKey[]; // multi-select union of readiness verdicts — [] = all
	watchtime: WatchtimeKey[]; // multi-select union of size bands — [] = all
	sort: WatchlistSortKey; // table column sort
	sortDir: 'asc' | 'desc';
}

/** The three size bands a row falls into, ascending. */
export type WatchtimeKey = 'short' | 'medium' | 'long';

/** The two band boundaries, in seconds. 5h is one 12-episode cour at ~25 min — the point a
 *  season stops being a single evening — and 10h is two. The chip labels spell the same
 *  numbers as prose, so a test pins the two spellings together rather than a comment asking
 *  for it. */
export const WATCHTIME_CUTS: Record<'short' | 'medium', number> = {
	short: 5 * 3600,
	medium: 10 * 3600,
};

/** Which band a row's runtime falls in, or null when it is unknown.
 *
 *  Null is not a fourth band and not "zero": an open-ended show has no episode count, so
 *  `total_watch_time` is null and any bucket would be a guess. Returning null keeps such a
 *  row out of every chip, the same way readiness lets a null runtime never clear its
 *  threshold. */
export function watchtimeBucket(seconds: number | null): WatchtimeKey | null {
	if (seconds === null || seconds <= 0) return null;
	// Asymmetric on purpose: "> 10h" shown on a 10-hour title is a bug, so the upper cut is
	// inclusive where the lower one is not.
	if (seconds < WATCHTIME_CUTS.short) return 'short';
	if (seconds <= WATCHTIME_CUTS.medium) return 'medium';
	return 'long';
}

export interface WatchlistRow {
	key: string;
	/** The uuid this row's detail page is keyed by, for the scroll-back anchor
	 *  (`utils/scrollFocus`). Not `key`, which at media grain is the watchlist
	 *  ENTRY uuid and appears in no detail URL. */
	detailUuid: string;
	href: string;
	coverImage: string | null;
	/** media grain → SpoilerGuard the cover by this uuid; anime grain → null (anime
	 *  covers are never spoiler-protected). */
	spoilerMediaUuid: string | null;
	title: string;
	subtitle: string | null; // anime title (media grain); null for anime grain (uses mainSide instead)
	/** "X main · Y side" story breakdown — anime grain only (media grain: null). Kept
	 *  separate from subtitle so the table/card render it like the ratings bracket/pill. */
	mainSide: string | null;
	relationLabel: string | null; // media grain: this media's relation type; anime grain: null
	colors: string[]; // distinct tag colors: 1 = solid, several = gradient
	tagLabel: string; // tag name (media) or "N lists" (anime) — the color tooltip
	priority: number; // media priority, or the anime's most-urgent (min) media priority
	note: string | null; // the note text — media grain only
	/** Notes of the anime's watchlisted media, in the anime-page media-table order
	 *  (chronological). Anime grain only (media grain: []) — the hover tooltip on the
	 *  grid card + table Note column shows these instead of a bare count. */
	noteTexts: string[];
	/** Count of watchlisted media carrying a note in this row's scope: 0/1 for a media
	 *  row, the anime's tally for an anime row. Drives the table's Note column. */
	noteCount: number;
	mediaCount: number;
	/** The anime's readiness verdict, or null at media grain — the verdict is about a
	 *  franchise, so repeating it on each of its entries would say nothing per card.
	 *  Raw state, not a label: `utils/watchlist.READY_BADGE` renders it, the same split
	 *  as `priority` and `PRIORITY_ACCENT`. */
	readyStatus: ReadyStatus | null;
	/** Summed runtime of the entries this row aggregates, or null when none of them has a
	 *  known length. SUMMED — not the per-media maximum `watchlistReady.STANDALONE_SECONDS`
	 *  takes. The two ask different questions: that one asks whether a single entry is a
	 *  commitment on its own, this one asks how long the thing you listed is. */
	watchSeconds: number | null;
	/** Some of the row's entries have a known length and some do not, so `watchSeconds` is
	 *  a lower bound and renders as `8h 40m+`. Always false at media grain — a single media
	 *  is either known or not. */
	watchPartial: boolean;
	createdAt: string;
}

export interface PriorityBand {
	priority: number;
	label: string;
	rows: WatchlistRow[];
}

/** Keep only entries whose tag is in the selected set. Empty selection = all (the tag
 *  filter is a union — "show me these lists combined"). */
export function filterByTags(items: WatchlistItem[], tagUuids: string[]): WatchlistItem[] {
	if (tagUuids.length === 0) return items;
	const set = new Set(tagUuids);
	return items.filter((i) => set.has(i.tag_uuid));
}

/**
 * Keep entries whose anime falls under one of the selected readiness chips. Empty
 * selection = all, the same union convention as the tag and priority filters.
 *
 * `statuses` must come from `statusByAnime` over the SAME entries passed here — the
 * tag-filtered set, per `buildWatchlistView`. A map built over a wider set would admit
 * entries on a verdict their own list doesn't support.
 *
 * `grain` is a parameter because the media grain narrows a ready anime further; the
 * feature doc has the rule.
 */
export function filterByReadiness(
	items: WatchlistItem[],
	statuses: Map<string, ReadyStatus>,
	selected: ReadyFilterKey[],
	grain: WatchlistGrain,
	now: Date = new Date(),
): WatchlistItem[] {
	if (selected.length === 0) return items;
	return items.filter((i) => {
		const status = statuses.get(i.anime_uuid);
		if (!status || !matchesFilter(status, selected)) return false;
		return grain === 'anime' || !isReady(status) || isAvailable(i, now);
	});
}

/** One row per media entry. */
export function toMediaRows(items: WatchlistItem[], lang: NameLanguage): WatchlistRow[] {
	return items.map((i) => ({
		key: i.uuid,
		detailUuid: i.media_uuid,
		href: buildDetailHref('media', i.media_uuid, { from: 'watchlist' }),
		coverImage: i.media_cover_image,
		spoilerMediaUuid: i.media_uuid,
		title: resolveTitle(i.media_title, i.media_name_eng, i.media_name_jap, lang),
		subtitle: resolveTitle(i.anime_title, i.anime_name_eng, i.anime_name_jap, lang),
		mainSide: null,
		relationLabel: formatRelationType(i.relation_type),
		colors: [i.tag_color],
		tagLabel: i.tag_name,
		priority: i.priority,
		note: i.note,
		noteTexts: [], // media grain uses `note`; noteTexts is the anime-grain aggregate
		noteCount: i.note ? 1 : 0,
		mediaCount: 1,
		readyStatus: null,
		watchSeconds: i.total_watch_time,
		watchPartial: false, // one media: its length is known or it is not
		createdAt: i.created_at,
	}));
}

/** One row per anime, aggregating its watchlisted media: most-urgent (min) priority,
 *  distinct tag colors (→ gradient when >1), the media count, and the readiness badge.
 *
 *  `statuses` is passed in rather than derived from `items` so it is the same map
 *  `filterByReadiness` judged on, computed once — deriving it here would re-judge the
 *  set that filter already narrowed, and a chip could then change its own input. An
 *  anime missing from the map simply gets no badge. */
export function toAnimeRows(
	items: WatchlistItem[],
	lang: NameLanguage,
	statuses: Map<string, ReadyStatus>,
): WatchlistRow[] {
	// A noted media, carrying the fields the anime-page media table sorts by so the
	// tooltip lists notes in the same (chronological) order the user sees them there.
	interface NotedMedia {
		note: string;
		year: number | null;
		season: string | null;
		mal_id: number;
	}
	interface Acc {
		item: WatchlistItem;
		priority: number;
		colors: string[];
		seenTags: Set<string>;
		count: number;
		main: number;
		side: number;
		noted: NotedMedia[];
		seconds: number; // Σ of the KNOWN runtimes only
		unknown: number; // entries whose runtime is null
		earliest: string;
	}
	const byAnime = new Map<string, Acc>();
	for (const i of items) {
		let a = byAnime.get(i.anime_uuid);
		if (!a) {
			a = { item: i, priority: i.priority, colors: [], seenTags: new Set(), count: 0, main: 0, side: 0, noted: [], seconds: 0, unknown: 0, earliest: i.created_at };
			byAnime.set(i.anime_uuid, a);
		}
		a.priority = Math.min(a.priority, i.priority);
		if (!a.seenTags.has(i.tag_uuid)) {
			a.seenTags.add(i.tag_uuid);
			a.colors.push(i.tag_color);
		}
		a.count++;
		if (MAIN_RELATIONS.has(i.relation_type)) a.main++;
		else a.side++;
		// Split rather than `?? 0`: a partial sum has to stay distinguishable from a
		// complete one, which is what earns the row its `+`.
		if (i.total_watch_time === null) a.unknown++;
		else a.seconds += i.total_watch_time;
		if (i.note) a.noted.push({ note: i.note, year: i.anime_season_year, season: i.anime_season_name, mal_id: i.mal_id });
		if (i.created_at < a.earliest) a.earliest = i.created_at;
	}
	return [...byAnime.values()].map(({ item: i, priority, colors, count, main, side, noted, seconds, unknown, earliest }) => ({
		key: i.anime_uuid,
		detailUuid: i.anime_uuid,
		href: buildDetailHref('anime', i.anime_uuid, { from: 'watchlist' }),
		coverImage: i.anime_cover_image,
		spoilerMediaUuid: null,
		title: resolveTitle(i.anime_title, i.anime_name_eng, i.anime_name_jap, lang),
		subtitle: null,
		mainSide: mainSideLabel(main, side),
		relationLabel: null,
		colors,
		// colors.length === distinct tag count (one color pushed per new tag_uuid).
		tagLabel: colors.length === 1 ? i.tag_name : `${colors.length} lists`,
		priority,
		note: null,
		noteTexts: noted.slice().sort(byChronoKey).map((n) => n.note),
		noteCount: noted.length,
		mediaCount: count,
		readyStatus: statuses.get(i.anime_uuid) ?? null,
		// A known runtime is always > 0 (the backend maps MAL's 0 episodes/duration to
		// NULL), so `seconds > 0` is exactly "at least one entry's length is known".
		watchSeconds: seconds > 0 ? seconds : null,
		watchPartial: unknown > 0 && seconds > 0,
		createdAt: earliest,
	}));
}

/** Order noted media the way the anime-page media table does: (year, season, mal_id) —
 *  the client mirror of the backend `chronological_media_key`. */
function byChronoKey(
	a: { year: number | null; season: string | null; mal_id: number },
	b: { year: number | null; season: string | null; mal_id: number }
): number {
	const ay = a.year ?? 9999,
		by = b.year ?? 9999;
	if (ay !== by) return ay - by;
	const as = SEASON_ORDER[a.season ?? ''] ?? 0,
		bs = SEASON_ORDER[b.season ?? ''] ?? 0;
	if (as !== bs) return as - bs;
	return a.mal_id - b.mal_id;
}

/** Keep only rows whose priority band is in the selected set. Empty = all (a union,
 *  mirroring the list filter). Applied AFTER row normalization so it matches the band
 *  each row displays in — the anime grain filters on the anime's most-urgent priority. */
export function filterByPriority(rows: WatchlistRow[], priorities: number[]): WatchlistRow[] {
	if (priorities.length === 0) return rows;
	const set = new Set(priorities);
	return rows.filter((r) => set.has(r.priority));
}

/**
 * How a row's runtime renders — label, both tints, and the explanation it needs (or null
 * when the number speaks for itself). Single-sourced so the grid card and the table cannot
 * word it or punctuate it differently; each then takes the tint its surface calls for.
 *
 * `+` marks a lower bound. The copy names the runtime rather than either factor behind it,
 * because a null means the episode count OR the average episode length is missing, and
 * naming one sends people looking for a number that is often already there.
 */
export function watchtimeDisplay(
	seconds: number | null,
	partial: boolean,
): { label: string; hint: string | null; fill: string; text: string } {
	const tint = watchtimeTint(watchtimeBucket(seconds));
	if (seconds === null) {
		return { label: 'N/A', hint: 'No watchtime yet — the episode count or episode length is still unknown', ...tint };
	}
	return {
		label: formatDurationCompact(seconds) + (partial ? '+' : ''),
		hint: partial ? 'At least this long — some listed entries have no watchtime yet' : null,
		...tint,
	};
}

/**
 * Keep only rows whose size band is in the selected set. Empty = all, the same union as
 * every other watchlist chip group.
 *
 * Applied AFTER row normalization, like `filterByPriority` and unlike `filterByReadiness`,
 * because it reads the row's aggregated runtime. That is also what scopes it to the
 * selected lists: the rows come from the already tag-filtered entries, so an anime's time
 * covers exactly the entries its media count and main/side split cover.
 */
export function filterByWatchtime(rows: WatchlistRow[], selected: WatchtimeKey[]): WatchlistRow[] {
	if (selected.length === 0) return rows;
	const set = new Set(selected);
	return rows.filter((r) => {
		const bucket = watchtimeBucket(r.watchSeconds);
		return bucket !== null && set.has(bucket);
	});
}

/** Within-band order + the stable, direction-independent sort tiebreak: rows by title ascending. */
const byTitle = (a: WatchlistRow, b: WatchlistRow) => a.title.localeCompare(b.title);

/** Group rows into High/Medium/Low bands. `dir` flips which sits on top: 'desc' (default)
 *  = High first (most urgent), 'asc' = Low first. Within a band, rows are title-ordered. */
export function toPriorityBands(rows: WatchlistRow[], dir: 'asc' | 'desc'): PriorityBand[] {
	const byPriority = new Map<number, WatchlistRow[]>();
	for (const r of rows) {
		const bucket = byPriority.get(r.priority);
		if (bucket) bucket.push(r);
		else byPriority.set(r.priority, [r]);
	}
	const order = dir === 'desc' ? [1, 2, 3] : [3, 2, 1];
	return order
		.filter((p) => byPriority.has(p))
		.map((p) => ({
			priority: p,
			label: priorityLabel(p),
			rows: byPriority.get(p)!.slice().sort(byTitle),
		}));
}

/** Flat sort for the table view. */
export function sortRows(rows: WatchlistRow[], key: WatchlistSortKey, dir: 'asc' | 'desc'): WatchlistRow[] {
	const sign = dir === 'asc' ? 1 : -1;
	return rows.slice().sort((a, b) => {
		let cmp = 0;
		if (key === 'title') cmp = byTitle(a, b);
		else if (key === 'priority') cmp = a.priority - b.priority;
		else if (key === 'date') cmp = a.createdAt.localeCompare(b.createdAt);
		else if (key === 'note') cmp = a.noteCount - b.noteCount;
		else if (key === 'time') {
			// An unknown runtime is missing data, not a short show, so it sorts last in BOTH
			// directions — returning here bypasses the `sign *` below, which would otherwise
			// parade every N/A row to the top the moment the direction flips.
			if (a.watchSeconds === null || b.watchSeconds === null) {
				if (a.watchSeconds === b.watchSeconds) return byTitle(a, b);
				return a.watchSeconds === null ? 1 : -1;
			}
			// `8h+` is strictly more than `8h`, so on an exact tie the partial flag is part
			// of the magnitude and flips with the direction — unlike the title tiebreak.
			cmp = a.watchSeconds - b.watchSeconds || Number(a.watchPartial) - Number(b.watchPartial);
		}
		// Direction applies to the primary key only; the title tiebreak stays ascending so
		// rows that tie on the primary keep a stable order when the direction flips (mirrors
		// the ratings table's un-signed tiebreak).
		if (cmp !== 0) return sign * cmp;
		return byTitle(a, b);
	});
}

/**
 * The list tab's pipeline, from the raw `/watchlist/items` fetch to what the grid and the
 * table render. A function rather than a `$derived` chain in the component because **the
 * order is the design** — which chips reach a readiness verdict is decided by the sequence
 * below and nothing else — and an order expressed in a component is reachable by no test.
 * `readiness.md` states the rule; this function's suite guards it.
 *
 * `now` is required, not defaulted: the verdict and the media-grain narrowing must agree on
 * what "next season" is, so the caller captures one clock.
 */
export function buildWatchlistView(
	items: WatchlistItem[],
	filter: WatchlistFilterState,
	lang: NameLanguage,
	now: Date,
): { rows: WatchlistRow[]; tableRows: WatchlistRow[] } {
	const tagged = filterByTags(items, filter.tagUuids);
	const statuses = statusByAnime(tagged, now);
	const filtered = filterByReadiness(tagged, statuses, filter.readiness, filter.grain, now);
	const allRows =
		filter.grain === 'anime' ? toAnimeRows(filtered, lang, statuses) : toMediaRows(filtered, lang);
	const rows = filterByWatchtime(filterByPriority(allRows, filter.priorities), filter.watchtime);
	return {
		rows,
		// A getter, so the grid never pays for a sort it discards — it bands `rows` itself,
		// and a flat sort would override the within-band title order it renders.
		get tableRows() {
			return sortRows(rows, filter.sort, filter.sortDir);
		},
	};
}

// ── Statistics subtab (v0.15.1) ──────────────────────────────────────────────
// Pure summary derived from the wide /watchlist/items fetch + the /ratings/scores
// fetch, mirroring the ratings-page "one fetch, all math client-side" pattern.

export interface TagCount {
	name: string;
	count: number; // distinct watchlisted anime carrying this genre/studio (the bar metric)
	main: number; // watchlisted MAIN media in this genre/studio (for the bar hover)
	side: number; // watchlisted SIDE media
	seconds: number; // queued runtime (Σ total_watch_time) of this tag's media
}

/** Full queued runtime of a watchlist media — the backend Media.total_watch_time hybrid
 *  (episodes × per-episode duration), null when either factor is unknown. Watchlist media
 *  are unwatched with no partial-watch status, so the full runtime IS the queued time. */
function queuedSeconds(it: WatchlistItem): number {
	return it.total_watch_time ?? 0;
}

export interface WatchlistSummary {
	totalAnime: number; // distinct anime on the watchlist
	totalMedia: number; // watchlist entries (one per media)
	totalQueuedSeconds: number; // Σ full runtime of watchlist media (time queued up)
	alreadyRated: number; // watchlist media you've already rated
	continuations: number; // UNRATED watchlist media whose anime has another rated media
	topGenres: TagCount[];
	topStudios: TagCount[];
}

/** Minimal shape needed from a rating for the summary (media + its anime). */
export type RatedRef = { media_uuid: string; anime_uuid: string };

/** Count distinct watchlisted anime per tag value (genre/studio) — anime-level so a
 *  multi-season franchise isn't over-counted — top `limit`, ties broken by name. Also
 *  tallies the watchlisted main/side MEDIA per tag (the bar's hover breakdown). */
function topTags(items: WatchlistItem[], dim: 'genres' | 'studios', limit: number): TagCount[] {
	const byTag = new Map<string, { anime: Set<string>; main: number; side: number; seconds: number }>();
	for (const it of items) {
		const isMain = MAIN_RELATIONS.has(it.relation_type);
		const secs = queuedSeconds(it);
		for (const name of it[dim]) {
			let acc = byTag.get(name);
			if (!acc) {
				acc = { anime: new Set(), main: 0, side: 0, seconds: 0 };
				byTag.set(name, acc);
			}
			acc.anime.add(it.anime_uuid);
			if (isMain) acc.main++;
			else acc.side++;
			acc.seconds += secs;
		}
	}
	return [...byTag.entries()]
		.map(([name, acc]) => ({ name, count: acc.anime.size, main: acc.main, side: acc.side, seconds: acc.seconds }))
		.sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
		.slice(0, limit);
}

export function watchlistSummary(
	items: WatchlistItem[],
	rated: RatedRef[],
	opts: { genreLimit?: number; studioLimit?: number } = {},
): WatchlistSummary {
	const { genreLimit = 5, studioLimit = 3 } = opts;

	const ratedMedia = new Set(rated.map((r) => r.media_uuid));
	const ratedByAnime = new Map<string, Set<string>>();
	for (const r of rated) {
		let s = ratedByAnime.get(r.anime_uuid);
		if (!s) {
			s = new Set();
			ratedByAnime.set(r.anime_uuid, s);
		}
		s.add(r.media_uuid);
	}

	let alreadyRated = 0;
	let continuations = 0;
	for (const it of items) {
		if (ratedMedia.has(it.media_uuid)) {
			alreadyRated++;
			// This entry is itself rated → it's a rewatch, not a continuation. Skip it.
			continue;
		}
		// A "continuation": this (unrated) entry's anime has some OTHER rated media — you've
		// started the franchise but not this entry yet.
		const animeRated = ratedByAnime.get(it.anime_uuid);
		if (animeRated && animeRated.size > 0) continuations++;
	}

	return {
		totalAnime: new Set(items.map((i) => i.anime_uuid)).size,
		totalMedia: items.length,
		totalQueuedSeconds: items.reduce((sum, it) => sum + queuedSeconds(it), 0),
		alreadyRated,
		continuations,
		topGenres: topTags(items, 'genres', genreLimit),
		topStudios: topTags(items, 'studios', studioLimit),
	};
}
