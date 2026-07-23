// Pure helpers for the /watchlist overview list tab. Watchlist entries are per-media,
// but the overview can show them at MEDIA grain (one card per entry) or ANIME grain (one
// card per anime, aggregating its watchlisted media — gradient bookmark when it spans
// tags). Both grains normalize to a `WatchlistRow` so one grid/card/table serves both.
import { buildDetailHref } from '$lib/utils/navigation';
import { formatRelationType, resolveTitle } from '$lib/utils/formatString';
import { priorityLabel } from '$lib/utils/watchlist';
import { MAIN_RELATIONS, mainSideLabel } from '$lib/utils/relations';
import { SEASON_ORDER } from '$lib/utils/getSeason';
import type { WatchlistItem } from '$lib/types/api';

export type WatchlistView = 'grid' | 'table';
export type WatchlistGrain = 'anime' | 'media';
export type WatchlistSortKey = 'title' | 'priority' | 'date' | 'note';
export type NameLanguage = 'english' | 'japanese' | 'romaji';

export interface WatchlistRow {
	key: string;
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

/** One row per media entry. */
export function toMediaRows(items: WatchlistItem[], lang: NameLanguage): WatchlistRow[] {
	return items.map((i) => ({
		key: i.uuid,
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
		createdAt: i.created_at,
	}));
}

/** One row per anime, aggregating its watchlisted media: most-urgent (min) priority,
 *  distinct tag colors (→ gradient when >1), and the media count. */
export function toAnimeRows(items: WatchlistItem[], lang: NameLanguage): WatchlistRow[] {
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
		earliest: string;
	}
	const byAnime = new Map<string, Acc>();
	for (const i of items) {
		let a = byAnime.get(i.anime_uuid);
		if (!a) {
			a = { item: i, priority: i.priority, colors: [], seenTags: new Set(), count: 0, main: 0, side: 0, noted: [], earliest: i.created_at };
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
		if (i.note) a.noted.push({ note: i.note, year: i.anime_season_year, season: i.anime_season_name, mal_id: i.mal_id });
		if (i.created_at < a.earliest) a.earliest = i.created_at;
	}
	return [...byAnime.values()].map(({ item: i, priority, colors, count, main, side, noted, earliest }) => ({
		key: i.anime_uuid,
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
		// Direction applies to the primary key only; the title tiebreak stays ascending so
		// rows that tie on the primary keep a stable order when the direction flips (mirrors
		// the ratings table's un-signed tiebreak).
		if (cmp !== 0) return sign * cmp;
		return byTitle(a, b);
	});
}
