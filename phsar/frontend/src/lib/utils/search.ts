import { api } from '$lib/api';
import { WATCH_STATUS_OPTIONS, type AnimeSearchResult, type MediaSearchResult } from '$lib/types/api';
import {
	formatDecimalDigits,
	formatDurationCompact,
	formatNumber,
	formatRelationType,
	watchStatusLabel,
} from '$lib/utils/formatString';

export type ViewType = 'anime' | 'media';
export type SearchType = 'title' | 'description' | 'rating_notes';
export type MatchMode = 'any' | 'all';
export type RatedState = 'none' | 'in_progress' | 'on_hold' | 'dropped' | 'main' | 'all' | 'completed';
export type SortKey =
	| 'relevance' | 'top_rated' | 'score' | 'popularity' | 'added' | 'release' | 'aired' | 'title' | 'random'
	| 'your_rating';
export type SortDir = 'asc' | 'desc';

/** The search's parameters, as the token carries them. A token verifies to every field,
 * unset ones as null or their default, so an optional field may be null as well as absent. */
export interface MediaSearchFilters {
	query: string;
	search_type: SearchType;
	view_type?: ViewType;

	// List filters
	relation_type?: string[] | null;
	media_type?: string[] | null;
	age_rating?: string[] | null;
	airing_status?: string[] | null;
	anime_season?: string[] | null;
	genre_name?: string[] | null;
	studio_name?: string[] | null;
	original_source?: string[] | null;
	genre_mode?: MatchMode;
	studio_mode?: MatchMode;

	// Range filters
	score_min?: number | null;
	score_max?: number | null;
	scored_by_min?: number | null;
	scored_by_max?: number | null;
	episodes_min?: number | null;
	episodes_max?: number | null;
	duration_per_episode_min?: number | null;
	duration_per_episode_max?: number | null;
	total_watch_time_min?: number | null;
	total_watch_time_max?: number | null;

	top_percent?: number | null;
	upcoming_main?: boolean;
	// The caller's own: a union of states, and listed or not.
	rated?: RatedState[] | null;
	watchlisted?: boolean | null;

	// Unset = the endpoint's own: relevance, and each key's default direction.
	sort?: SortKey | null;
	sort_dir?: SortDir | null;
}

/** How many results a search shows. One more is requested, so a full page can say "50+"
 * rather than a count that would be a guess. */
export const SEARCH_LIMIT = 50;

const LIST_FILTER_KEYS = [
	'airing_status', 'anime_season', 'genre_name', 'studio_name', 'original_source',
	'media_type', 'relation_type', 'age_rating',
] as const;
export type ListFilterKey = (typeof LIST_FILTER_KEYS)[number];
type ModeKey = 'genre_mode' | 'studio_mode';

export interface ListFilter {
	label: string;
	/** A list with an any/all toggle names its mode param; every other list matches any of its values. */
	mode?: ModeKey;
	mediaOnly?: boolean;
	/** Display label for a raw value, which stays what the backend receives. */
	format?: (value: string) => string;
}

/** Every list filter, once: the sheet and the chips both read it, so a list's name, its
 * match mode and how its values display can't differ between them. */
export const LIST_FILTERS: Record<ListFilterKey, ListFilter> = {
	airing_status: { label: 'Airing status' },
	anime_season: { label: 'Season' },
	genre_name: { label: 'Genres', mode: 'genre_mode' },
	studio_name: { label: 'Studios', mode: 'studio_mode' },
	original_source: { label: 'Source' },
	media_type: { label: 'Media type' },
	relation_type: { label: 'Relation type', mediaOnly: true, format: formatRelationType },
	age_rating: { label: 'Age rating' },
};

/** The backend's default match mode per list. */
export const DEFAULT_MODE = { genre_mode: 'all', studio_mode: 'any' } as const satisfies Record<ModeKey, MatchMode>;

// Every non-empty value goes out as a query param, a list as repeated keys. Null and
// absent stay out, so a verified token's unset fields fall back to the endpoint's
// defaults; `watchlisted=false` is a value and goes.
function buildSearchParams(params: MediaSearchFilters, limit?: number): URLSearchParams {
	const searchParams = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value === null || value === undefined || value === '') continue;
		for (const v of Array.isArray(value) ? value : [value]) searchParams.append(key, String(v));
	}
	if (limit !== undefined) searchParams.set('limit', String(limit));
	return searchParams;
}

export async function fetchSearchResults(params: MediaSearchFilters, limit?: number): Promise<MediaSearchResult[]> {
	return api.get<MediaSearchResult[]>('/search/media', { params: buildSearchParams(params, limit) });
}

export async function fetchAnimeSearchResults(params: MediaSearchFilters, limit?: number): Promise<AnimeSearchResult[]> {
	return api.get<AnimeSearchResult[]>('/search/anime', { params: buildSearchParams(params, limit) });
}

// ---------------------------------------------------------------------------
// Sort
// ---------------------------------------------------------------------------

export interface SortOption {
	value: SortKey;
	label: string;
	/** What the key orders by, shown under it in the menu. */
	hint: string;
	/** What each direction reads as. A key whose reverse means nothing has none: the
	 * query's own order, or a shuffle, which reversed is just another shuffle. */
	dir?: Record<SortDir, string>;
}

/** Every sort the search knows, in menu order. */
export const SORT_OPTIONS: SortOption[] = [
	{ value: 'relevance', label: 'Best match', hint: 'How closely it matches your query' },
	{
		value: 'top_rated', label: 'Top rated', hint: 'MAL score weighted by how many voted',
		dir: { desc: 'Highest first', asc: 'Lowest first' },
	},
	{ value: 'score', label: 'Score', hint: 'The MAL score alone', dir: { desc: 'Highest first', asc: 'Lowest first' } },
	{
		value: 'popularity', label: 'Popularity', hint: 'How many people voted on MAL',
		dir: { desc: 'Most votes first', asc: 'Fewest votes first' },
	},
	{
		value: 'added', label: 'Newest added', hint: 'When it joined the library',
		dir: { desc: 'Newest first', asc: 'Oldest first' },
	},
	{
		value: 'release', label: 'Release date', hint: 'Next announced, else last aired season',
		dir: { asc: 'Oldest first', desc: 'Newest first' },
	},
	{
		value: 'aired', label: 'Latest aired', hint: 'Last finished, else airing or next season',
		dir: { desc: 'Newest first', asc: 'Oldest first' },
	},
	{ value: 'title', label: 'Title A–Z', hint: 'In your name language', dir: { asc: 'A to Z', desc: 'Z to A' } },
	{ value: 'random', label: 'Random (daily)', hint: 'Same shuffle for everyone today' },
	{
		value: 'your_rating', label: 'Your rating', hint: 'Your mean rating, unrated last',
		dir: { desc: 'Highest first', asc: 'Lowest first' },
	},
];

// The keys the backend ascends unless told otherwise; the rest descend. One line, because
// a backend test reads it against `search_filters.ASCENDING_SORTS`.
export const ASCENDING_SORTS: SortKey[] = ['title', 'release'];

/** The sorts the menu offers: Best match only with a query to match. */
export function offeredSorts(params: MediaSearchFilters): SortOption[] {
	return SORT_OPTIONS.filter((o) => o.value !== 'relevance' || params.query?.trim());
}

/** The order the results are actually in: relevance read as the backend reads it
 * (docs/features/search.md, Sorting), shown rather than hidden. */
export function effectiveSort(params: MediaSearchFilters): { sort: SortKey; option: SortOption; dir: SortDir | null } {
	const requested = params.sort ?? 'relevance';
	const sort = requested === 'relevance' && !params.query?.trim() ? 'top_rated' : requested;
	const option = SORT_OPTIONS.find((o) => o.value === sort)!;
	if (!option.dir) return { sort, option, dir: null };
	const dir = requested === 'relevance' ? undefined : params.sort_dir;
	return { sort, option, dir: dir ?? (ASCENDING_SORTS.includes(sort) ? 'asc' : 'desc') };
}

/** The applied search with a new query and mode. A different query starts from Best match:
 * a sort chosen for the last query would bury the new one's intended hit. A mode switch
 * keeps the sort. */
export function withQuery(params: MediaSearchFilters, query: string, mode: SearchType): MediaSearchFilters {
	const next = { ...params, query, search_type: mode };
	return query.trim() === (params.query ?? '').trim() ? next : omitKeys(next, ['sort', 'sort_dir']);
}

// ---------------------------------------------------------------------------
// Rated states, per grain — a state of the other grain is refused (docs/features/search.md).
// ---------------------------------------------------------------------------

// The states a watch status names take its label, so a chip reads like the rating's badge.
export const RATED_STATES: Record<ViewType, { value: RatedState; label: string }[]> = {
	anime: [
		{ value: 'none', label: 'Unrated' },
		{ value: 'in_progress', label: 'In Progress' },
		{ value: 'on_hold', label: watchStatusLabel('on_hold') },
		{ value: 'dropped', label: watchStatusLabel('dropped') },
		{ value: 'main', label: 'Main Done' },
		{ value: 'all', label: 'All Done' },
	],
	media: [{ value: 'none', label: 'Unrated' }, ...WATCH_STATUS_OPTIONS],
};

/** Every state chosen filters nothing, so it goes out as no filter — which also keeps the
 * anime grain's list under the token's list cap (`MAX_ITEMS`). */
export function normalizeRated(params: MediaSearchFilters, view: ViewType): MediaSearchFilters {
	const rated = params.rated ?? [];
	return rated.length && RATED_STATES[view].every((s) => rated.includes(s.value))
		? { ...params, rated: undefined }
		: params;
}

// ---------------------------------------------------------------------------
// Range filters
// ---------------------------------------------------------------------------

export type RangeKey = 'score' | 'scored_by' | 'episodes' | 'duration_per_episode' | 'total_watch_time';
type RangeParam = `${RangeKey}_${'min' | 'max'}`;

export interface RangeFilter {
	label: string;
	step: number;
	/** Log scale, for the ranges whose values span orders of magnitude. */
	log?: boolean;
	mediaOnly?: boolean;
	format: (value: number) => string;
}

export const RANGE_FILTERS: Record<RangeKey, RangeFilter> = {
	score: { label: 'Score', step: 0.01, format: (v) => formatDecimalDigits(v, 2) },
	scored_by: { label: 'Scored by', step: 0.1, log: true, format: formatNumber },
	episodes: { label: 'Episodes', step: 0.1, log: true, format: formatNumber },
	duration_per_episode: { label: 'Duration per episode', step: 60, mediaOnly: true, format: formatDurationCompact },
	total_watch_time: { label: 'Total watch time', step: 0.1, log: true, format: formatDurationCompact },
};

export const rangeParams = (key: RangeKey): [RangeParam, RangeParam] => [`${key}_min`, `${key}_max`];

// ---------------------------------------------------------------------------
// Applied-filter chips
// ---------------------------------------------------------------------------

export interface FilterChip {
	id: string;
	label: string;
	/** What removing the chip clears. */
	keys: (keyof MediaSearchFilters)[];
}

/** One chip per applied filter group. A group set to its default (a mode alone,
 * `upcoming_main=false`) is no chip. */
export function filterChips(params: MediaSearchFilters, view: ViewType): FilterChip[] {
	const chips: FilterChip[] = [];

	if (params.rated?.length) {
		const labels = RATED_STATES[view].filter((s) => params.rated!.includes(s.value)).map((s) => s.label);
		chips.push({ id: 'rated', label: labels.join(' or '), keys: ['rated'] });
	}
	if (params.watchlisted != null) {
		chips.push({
			id: 'watchlisted', label: params.watchlisted ? 'In watchlist' : 'Not in watchlist', keys: ['watchlisted'],
		});
	}
	if (params.upcoming_main) chips.push({ id: 'upcoming_main', label: 'Upcoming main story', keys: ['upcoming_main'] });
	if (params.top_percent != null) {
		chips.push({ id: 'top_percent', label: `Top ${params.top_percent}%`, keys: ['top_percent'] });
	}

	for (const key of LIST_FILTER_KEYS) {
		const values = params[key];
		if (!values?.length) continue;
		const { label, mode: modeKey, format } = LIST_FILTERS[key];
		const mode = modeKey ? (params[modeKey] ?? DEFAULT_MODE[modeKey]) : 'any';
		const shown = format ? values.map(format) : values;
		chips.push({
			id: key,
			label: `${label}: ${shown.join(mode === 'all' ? ' & ' : ' or ')}`,
			keys: modeKey ? [key, modeKey] : [key],
		});
	}

	for (const [key, range] of Object.entries(RANGE_FILTERS) as [RangeKey, RangeFilter][]) {
		const [minKey, maxKey] = rangeParams(key);
		const min = params[minKey];
		const max = params[maxKey];
		if (min == null && max == null) continue;
		const text = min != null && max != null
			? `${range.format(min)}–${range.format(max)}`
			: min != null ? `≥ ${range.format(min)}` : `≤ ${range.format(max!)}`;
		chips.push({ id: key, label: `${range.label} ${text}`, keys: [minKey, maxKey] });
	}

	return chips;
}

export function omitKeys(params: MediaSearchFilters, keys: (keyof MediaSearchFilters)[]): MediaSearchFilters {
	const rest = { ...params };
	for (const key of keys) delete rest[key];
	return rest;
}

// ---------------------------------------------------------------------------
// The anime <-> media toggle
// ---------------------------------------------------------------------------

/** What survives a switch between the grains. `carry` means the same thing at both;
 * `drop` doesn't translate — relation type exists only per media, and the ranges other
 * than the 0–10 score sit on scales that differ between one media and an aggregate;
 * `common` keeps the rated states both grains have. Every field is classified, so a new
 * one fails to compile until someone decides. */
const ACROSS_VIEWS = {
	query: 'carry', search_type: 'carry', view_type: 'drop',
	relation_type: 'drop', media_type: 'carry', age_rating: 'carry', airing_status: 'carry',
	anime_season: 'carry', genre_name: 'carry', studio_name: 'carry', original_source: 'carry',
	genre_mode: 'carry', studio_mode: 'carry',
	score_min: 'carry', score_max: 'carry',
	scored_by_min: 'drop', scored_by_max: 'drop', episodes_min: 'drop', episodes_max: 'drop',
	duration_per_episode_min: 'drop', duration_per_episode_max: 'drop',
	total_watch_time_min: 'drop', total_watch_time_max: 'drop',
	top_percent: 'carry', upcoming_main: 'carry', rated: 'common', watchlisted: 'carry',
	sort: 'carry', sort_dir: 'carry',
} as const satisfies Record<keyof Required<MediaSearchFilters>, 'carry' | 'drop' | 'common'>;

const COMMON_RATED = RATED_STATES.anime
	.map((s) => s.value)
	.filter((state) => RATED_STATES.media.some((s) => s.value === state));

export function carryAcrossView(params: MediaSearchFilters, view: ViewType): MediaSearchFilters {
	const carried: Record<string, unknown> = { view_type: view };
	for (const [key, rule] of Object.entries(ACROSS_VIEWS)) {
		const value = params[key as keyof MediaSearchFilters];
		if (value == null || rule === 'drop') continue;
		if (rule === 'carry') carried[key] = value;
		else {
			const kept = (value as RatedState[]).filter((s) => COMMON_RATED.includes(s));
			if (kept.length) carried[key] = kept;
		}
	}
	return carried as unknown as MediaSearchFilters;
}

// ---------------------------------------------------------------------------
// Guests
// ---------------------------------------------------------------------------

/** A shared link opened by a guest: drop what reads the caller's own ratings, notes and
 * watchlist, which a guest is refused (docs/features/search.md, Personal filters and sort), and
 * say whether anything went, so the page can tell them. Notes fall back to a title search. */
export function stripForGuest(params: MediaSearchFilters): { params: MediaSearchFilters; stripped: boolean } {
	const byRating = params.sort === 'your_rating';
	const notes = params.search_type === 'rating_notes';
	const stripped = !!params.rated?.length || params.watchlisted != null || byRating || notes;
	if (!stripped) return { params, stripped };
	const kept = omitKeys(params, byRating ? ['rated', 'watchlisted', 'sort', 'sort_dir'] : ['rated', 'watchlisted']);
	return { params: notes ? { ...kept, search_type: 'title' } : kept, stripped };
}
