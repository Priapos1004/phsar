import { api } from '$lib/api';
import { WATCH_STATUS_OPTIONS, type AnimeSearchResult, type FilterOptions, type MediaSearchResult } from '$lib/types/api';
import {
	formatDecimalDigits,
	formatDurationCompact,
	formatNumber,
	formatRelationType,
	formatMonthDay,
	formatScoreWithStep,
	watchStatusLabel,
} from '$lib/utils/formatString';

export type ViewType = 'anime' | 'media';
export type SearchType = 'title' | 'description' | 'rating_notes';
export type MatchMode = 'any' | 'all';
/** An Any/All toggle's options: the sheet's lists and genre groups. */
export const MATCH_MODES = [{ value: 'any' as const, label: 'Any' }, { value: 'all' as const, label: 'All' }];
export type RatedState = 'none' | 'in_progress' | 'on_hold' | 'dropped' | 'main' | 'all' | 'completed';
export type SortKey =
	| 'relevance' | 'top_rated' | 'score' | 'popularity' | 'added' | 'release' | 'aired' | 'title' | 'random'
	| 'your_rating' | 'announced';
export type SortDir = 'asc' | 'desc';

/** `GenreGroup` in media_filter_schema.py. */
export interface GenreGroup {
	mode: MatchMode;
	include: string[];
	exclude_mode: MatchMode;
	exclude: string[];
}

/** Genre groups joined by `mode` (`GenreFilter` in media_filter_schema.py, which says why
 * one level of groups is enough). */
export interface GenreFilter {
	mode: MatchMode;
	groups: GenreGroup[];
}

/** The backend's cap on groups. One line, because
 * `test_the_sheet_offers_the_genre_groups_the_search_takes` reads it. */
export const MAX_GENRE_GROUPS = 3;

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
	studio_name?: string[] | null;
	original_source?: string[] | null;
	studio_mode?: MatchMode;
	genres?: GenreFilter | null;

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

/** The top-N% steps the filter sheet offers. One line, because
 * `test_the_top_steps_are_the_search_sheets` reads it. */
export const TOP_PRESETS = [5, 10, 20, 50, 75];

/** How many results a search shows. One more is requested, so a full page can say "50+"
 * rather than a count that would be a guess. */
export const SEARCH_LIMIT = 50;

/** The most a search returns, and so what a search's see-all asks for. One line, because
 * `test_a_search_see_all_asks_for_the_whole_search` reads it against `MAX_SEARCH_LIMIT`. */
export const SEE_ALL_LIMIT = 1000;

/** What each search mode is called, wherever the user sees it. */
export const SEARCH_MODE_LABELS: Record<SearchType, string> = {
	title: 'Title', description: 'Description', rating_notes: 'My notes',
};

/** Which grain a result is: only an anime result carries the aggregate score. */
export function isAnimeResult(row: AnimeSearchResult | MediaSearchResult): row is AnimeSearchResult {
	return 'avg_score' in row;
}

const LIST_FILTER_KEYS = [
	'airing_status', 'anime_season', 'studio_name', 'original_source',
	'media_type', 'relation_type', 'age_rating',
] as const;
export type ListFilterKey = (typeof LIST_FILTER_KEYS)[number];
type ModeKey = 'studio_mode';

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
	studio_name: { label: 'Studios', mode: 'studio_mode' },
	original_source: { label: 'Source' },
	media_type: { label: 'Media type' },
	relation_type: { label: 'Relation type', mediaOnly: true, format: formatRelationType },
	age_rating: { label: 'Age rating' },
};

// Every non-empty value goes out as a query param, a list as repeated keys and an object
// (the genre groups) as JSON. Null and absent stay out, so a verified token's unset fields
// fall back to the endpoint's defaults; `watchlisted=false` is a value and goes.
function buildSearchParams(params: MediaSearchFilters, limit?: number): URLSearchParams {
	const searchParams = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value === null || value === undefined || value === '') continue;
		for (const v of Array.isArray(value) ? value : [value]) {
			searchParams.append(key, typeof v === 'object' ? JSON.stringify(v) : String(v));
		}
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
		value: 'announced', label: 'Newest announcement', hint: 'When its latest announcement was added',
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

/** The one season a search is pinned to, which a browse row names in a pill. */
export function pinnedSeason(params: MediaSearchFilters): string | null {
	return params.anime_season?.length === 1 ? params.anime_season[0] : null;
}

/** A poster tile's one line: what its list is ordered by, where the tile has no other
 * place for it. `sort` is the order the results are actually in (`effectiveSort`). */
export function sortLine(
	sort: SortKey, row: AnimeSearchResult | MediaSearchResult, ratingStep: number,
): string | null {
	const [score, votes] = isAnimeResult(row) ? [row.avg_score, row.avg_scored_by] : [row.score, row.scored_by];
	switch (sort) {
		case 'top_rated':
			return row.score_top_percent != null ? `Top ${row.score_top_percent}%` : null;
		case 'score':
			// The number only: the tile draws its own star in front.
			return score != null ? `${score}` : null;
		case 'popularity':
			return `${formatNumber(votes)} votes`;
		case 'added':
			return `Added ${formatMonthDay(row.added_at)}`;
		case 'announced':
			return row.announced_at ? `Announced ${formatMonthDay(row.announced_at)}` : null;
		case 'release':
		case 'aired':
			return row.sort_season ?? null;
		case 'your_rating':
			return row.your_rating != null ? `You: ${formatScoreWithStep(row.your_rating, ratingStep)}` : null;
		default:
			return null;
	}
}

/** The announced entry's type, when another type outnumbers it in the rest of the main story —
 * a movie for a TV show — and so is worth naming on the tile; a tie names nothing. The
 * announcement is in `main_story_types` itself, so it is left out, or it would tie a
 * one-season TV. */
export function unusualAnnouncedType(row: AnimeSearchResult): string | null {
	const announced = row.announced_type;
	if (!announced) return null;
	const types = row.main_story_types;
	const rest = (types.find((t) => t.media_type === announced)?.count ?? 1) - 1;
	return types.some((t) => t.media_type !== announced && t.count > rest) ? announced : null;
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

/** How a list matches: its any/all param, else any — the backend's default, and how
 * lists without a toggle match. */
export function listMode(params: MediaSearchFilters, key: ListFilterKey): MatchMode {
	const modeKey = LIST_FILTERS[key].mode;
	return (modeKey && params[modeKey]) || 'any';
}

/** Names as a chip reads them. */
const joinNames = (names: readonly string[], mode: MatchMode) => names.join(mode === 'all' ? ' & ' : ' or ');

const coversAll = (chosen: readonly string[] | null | undefined, all: readonly string[] = []) =>
	all.length > 0 && all.every((option) => chosen?.includes(option));

/** A selection of everything filters nothing, so it goes out as no filter: every rated
 * state — which also keeps the anime grain's list under the token's list cap
 * (`MAX_ITEMS`) — or every option a list offers, when the list matches any of them. A
 * list matched by "all" still filters: "has every studio" is a real ask. The mode stays,
 * as the user's choice for the next selection. A genre group with nothing picked goes,
 * and nothing else of the genres (why: `GenreFilterField`). */
export function normalizeFilters(
	params: MediaSearchFilters, view: ViewType, offered: Partial<Pick<FilterOptions, ListFilterKey>>,
): MediaSearchFilters {
	const out = { ...params };
	if (coversAll(out.rated, RATED_STATES[view].map((s) => s.value))) out.rated = undefined;
	for (const key of LIST_FILTER_KEYS) {
		if (listMode(out, key) === 'any' && coversAll(out[key], offered[key])) out[key] = undefined;
	}
	const groups = out.genres ? filledGroups(out.genres) : [];
	out.genres = groups.length ? { ...out.genres!, groups } : undefined;
	return out;
}

// ---------------------------------------------------------------------------
// Genre groups
// ---------------------------------------------------------------------------

export const isEmptyGroup = (group: GenreGroup) => !group.include.length && !group.exclude.length;
const filledGroups = (genres: GenreFilter) => genres.groups.filter((g) => !isEmptyGroup(g));

type Has = (genre: string) => boolean;

/** Whether a row carries any or all of `names` — none carries any of an empty list. */
const carries = (names: string[], mode: MatchMode, has: Has) =>
	names.length > 0 && (mode === 'all' ? names.every(has) : names.some(has));

const groupPasses = (g: GenreGroup, has: Has) =>
	(!g.include.length || carries(g.include, g.mode, has)) && !carries(g.exclude, g.exclude_mode, has);

const joined = (mode: MatchMode, groups: GenreGroup[], has: Has) =>
	mode === 'all' ? groups.every((g) => groupPasses(g, has)) : groups.some((g) => groupPasses(g, has));

/** Whether a row carrying the genres `has` passes — the backend's `_genre_match`, row by row. */
export const matchesGenres = (genres: GenreFilter, has: Has) => joined(genres.mode, genres.groups, has);

// Past this many genres named both ways a check would try over 65k settings, so it is
// skipped. No check reaches it at the group and list caps; it guards a raised cap, where
// a warning would then be missing but never wrong.
const MAX_TRIED = 16;

/** Whether some set of genres makes `holds` true. It is exact because `holds` is built
 * from groups, which only ever gain from a genre they include and lose from one they
 * exclude: the genres in `rising` alone are best carried, those in `falling` alone best
 * not, and only the genres in both need each setting tried. */
function satisfiable(holds: (has: Has) => boolean, rising: Set<string>, falling: Set<string>): boolean {
	const mixed = [...rising].filter((genre) => falling.has(genre));
	if (mixed.length > MAX_TRIED) return true;
	const bit = new Map(mixed.map((genre, at) => [genre, 1 << at]));
	for (let bits = 0; bits < 2 ** mixed.length; bits++) {
		const has = (genre: string) => {
			const flag = bit.get(genre);
			return flag === undefined ? rising.has(genre) : (bits & flag) !== 0;
		};
		if (holds(has)) return true;
	}
	return false;
}

const included = (groups: GenreGroup[]) => new Set(groups.flatMap((g) => g.include));
const excluded = (groups: GenreGroup[]) => new Set(groups.flatMap((g) => g.exclude));
const union = (a: Set<string>, b: Set<string>) => new Set([...a, ...b]);

/** What the user built but may not mean, as opposed to a combination no anime happens to
 * carry yet, which may come:
 * - the whole can never match (a contradiction: "Drama" and "without Drama"), or always
 *   does (a tautology: "Drama" or "without Drama");
 * - else the groups that change nothing (`idle`, indexes into `genres.groups`): the search
 *   matches the same anime without them. Taken in order, each against the groups not
 *   already idle, so of two identical groups only the first is, and all of them can go
 *   together. */
export function checkGenres(genres: GenreFilter): { warning: string | null; idle: number[] } {
	const groups = filledGroups(genres);
	if (!groups.length) return { warning: null, idle: [] };
	const up = included(groups);
	const down = excluded(groups);
	if (!satisfiable((has) => joined(genres.mode, groups, has), up, down)) {
		return { warning: 'No anime can match this: a genre is both required and excluded.', idle: [] };
	}
	if (!satisfiable((has) => !joined(genres.mode, groups, has), down, up)) {
		return { warning: 'Every anime matches this, so it filters nothing.', idle: [] };
	}

	let kept = groups;
	const idle: number[] = [];
	for (const group of groups) {
		const others = kept.filter((g) => g !== group);
		if (!others.length) continue;
		// Under all, a group changes nothing when it matches all the others do; under any,
		// when the others match all it does.
		const [narrow, wide] = genres.mode === 'all' ? [others, [group]] : [[group], others];
		const escapes = satisfiable(
			(has) => joined('all', narrow, has) && !joined(genres.mode, wide, has),
			union(included(narrow), excluded(wide)),
			union(excluded(narrow), included(wide)),
		);
		if (!escapes) {
			kept = others;
			idle.push(genres.groups.indexOf(group));
		}
	}
	if (!idle.length) return { warning: null, idle };
	const names = idle.map((at) => at + 1).join(' and ');
	const warning = idle.length === 1
		? `Group ${names} changes nothing: the search matches the same anime without it.`
		: `Groups ${names} change nothing: the search matches the same anime without them.`;
	return { warning, idle };
}

/** A piece of a chip's text (`ExpressionText`); `keyword` marks the words a genre
 * expression is built from. */
export interface Term {
	text: string;
	keyword?: boolean;
}

/** The groups in words, in the shape of the sheet's cards: "Fantasy or Isekai, without
 * Drama"; several groups each in parentheses, joined by "AND" or "OR" in capitals as the
 * divider between the cards is, so the join between groups stands apart from the "or" and
 * "&" inside one. Never rewritten into alternatives: that would no longer match the cards,
 * and it multiplies — three groups of five, joined by AND, are 125 alternatives. Empty
 * groups say nothing. One part per group, every one after the first led by its joiner, for
 * `ExpressionText`, which the chips and the Reads line render through. */
export function describeGenreTerms(genres: GenreFilter): Term[][] {
	const groups = filledGroups(genres);
	return groups.map((g, at) => {
		const terms: Term[] = [];
		if (at) terms.push({ text: genres.mode === 'all' ? 'AND' : 'OR', keyword: true }, { text: ' ' });
		const parenthesised = groups.length > 1 && g.include.length + g.exclude.length > 1;
		if (parenthesised) terms.push({ text: '(' });
		if (g.include.length) terms.push({ text: joinNames(g.include, g.mode) });
		if (g.exclude.length) {
			const together = g.exclude_mode === 'all' && g.exclude.length > 1;
			if (g.include.length) terms.push({ text: ', ' });
			terms.push({ text: 'without', keyword: true }, { text: ` ${joinNames(g.exclude, g.exclude_mode)}` });
			if (together) terms.push({ text: ' ' }, { text: 'together', keyword: true });
		}
		if (parenthesised) terms.push({ text: ')' });
		return terms;
	});
}

const textOf = (parts: Term[][]) => parts.map((part) => part.map((term) => term.text).join('')).join(' ');

export const describeGenres = (genres: GenreFilter) => textOf(describeGenreTerms(genres));

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
	/** The group, shown bold; absent where the value names itself ("Top 20%"). */
	name?: string;
	/** The value in groups and terms, as `ExpressionText` renders it — one run but for genres. */
	parts: Term[][];
	/** Both as one line: the remove button's accessible name, and what tests compare. */
	label: string;
	/** What removing the chip clears. */
	keys: (keyof MediaSearchFilters)[];
	/** Why the filter may not do what it reads as (`checkGenres`). */
	warning?: string;
}

const chip = (
	id: string, name: string | undefined, value: string | Term[][], keys: FilterChip['keys'],
): FilterChip => {
	const parts = typeof value === 'string' ? [[{ text: value }]] : value;
	const text = textOf(parts);
	return { id, name, parts, label: name ? `${name} ${text}` : text, keys };
};

/** One chip per applied filter group. A group set to its default (a mode alone,
 * `upcoming_main=false`) is no chip. */
export function filterChips(params: MediaSearchFilters, view: ViewType): FilterChip[] {
	const chips: FilterChip[] = [];

	if (params.rated?.length) {
		const labels = RATED_STATES[view].filter((s) => params.rated!.includes(s.value)).map((s) => s.label);
		chips.push(chip('rated', 'Rated:', labels.join(' or '), ['rated']));
	}
	if (params.watchlisted != null) {
		chips.push(chip('watchlisted', undefined, params.watchlisted ? 'In watchlist' : 'Not in watchlist', ['watchlisted']));
	}
	if (params.upcoming_main) chips.push(chip('upcoming_main', undefined, 'Upcoming main story', ['upcoming_main']));
	if (params.top_percent != null) {
		chips.push(chip('top_percent', undefined, `Top ${params.top_percent}%`, ['top_percent']));
	}

	const genreParts = params.genres ? describeGenreTerms(params.genres) : [];
	if (genreParts.length) {
		const { warning } = checkGenres(params.genres!);
		chips.push({ ...chip('genres', 'Genres:', genreParts, ['genres']), ...(warning && { warning }) });
	}

	for (const key of LIST_FILTER_KEYS) {
		const values = params[key];
		if (!values?.length) continue;
		const { label, mode: modeKey, format } = LIST_FILTERS[key];
		const shown = format ? values.map(format) : values;
		chips.push(chip(key, `${label}:`, joinNames(shown, listMode(params, key)), modeKey ? [key, modeKey] : [key]));
	}

	for (const [key, range] of Object.entries(RANGE_FILTERS) as [RangeKey, RangeFilter][]) {
		const [minKey, maxKey] = rangeParams(key);
		const min = params[minKey];
		const max = params[maxKey];
		if (min == null && max == null) continue;
		const text = min != null && max != null
			? `${range.format(min)}–${range.format(max)}`
			: min != null ? `≥ ${range.format(min)}` : `≤ ${range.format(max!)}`;
		chips.push(chip(key, range.label, text, [minKey, maxKey]));
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
	anime_season: 'carry', studio_name: 'carry', original_source: 'carry',
	studio_mode: 'carry', genres: 'carry',
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

/** What a guest is told when `stripForGuest` dropped something from their link. */
export const GUEST_STRIPPED_NOTICE =
	"This link used ratings, notes or the watchlist, which guest accounts don't have, so it opened without them — a notes search runs on titles instead.";

/** Whether a search, or a filter set's part of one, reads the caller's own ratings, notes
 * or watchlist — what a guest is refused (docs/features/search.md, Personal filters and sort). */
export function readsOwnData(params: Partial<MediaSearchFilters>): boolean {
	return !!params.rated?.length || params.watchlisted != null || params.sort === 'your_rating'
		|| params.search_type === 'rating_notes';
}

/** The search as a guest would get it: with no ratings or watchlist, a guest passes a filter
 * on that empty side for every anime, so it goes. Anything over their data that is left
 * still `readsOwnData`. */
export function forGuest(params: MediaSearchFilters): MediaSearchFilters {
	const passesAll: (keyof MediaSearchFilters)[] = [];
	if (params.rated?.includes('none')) passesAll.push('rated');
	if (params.watchlisted === false) passesAll.push('watchlisted');
	return omitKeys(params, passesAll);
}

/** A shared link opened by a guest: drop what `readsOwnData` names, and say whether anything
 * went, so the page can tell them. Notes fall back to a title search. */
export function stripForGuest(params: MediaSearchFilters): { params: MediaSearchFilters; stripped: boolean } {
	const byRating = params.sort === 'your_rating';
	const notes = params.search_type === 'rating_notes';
	const stripped = readsOwnData(params);
	if (!stripped) return { params, stripped };
	const kept = omitKeys(params, byRating ? ['rated', 'watchlisted', 'sort', 'sort_dir'] : ['rated', 'watchlisted']);
	return { params: notes ? { ...kept, search_type: 'title' } : kept, stripped };
}
