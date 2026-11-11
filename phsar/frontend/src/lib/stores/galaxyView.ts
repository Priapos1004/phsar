import type { GalaxyColour } from '$lib/utils/galaxy';
import {
	LIST_FILTERS,
	MAX_GENRE_GROUPS,
	RANGE_FILTERS,
	RATED_STATES,
	defaultSearch,
	rangeParams,
	type GenreGroup,
	type ListFilterKey,
	type MediaSearchFilters,
	type ModeKey,
	type RangeKey,
	type RangeParam,
	type RatedState
} from '$lib/utils/search';
import { MATCH_MODE_KEYS, createPersistedFilter, pickKey, pickStrings } from './persistedFilter';

/** The galaxy map's colouring, the filters lighting it up, and whether it names its groups. */
interface GalaxyView {
	colour: GalaxyColour;
	filters: MediaSearchFilters;
	names: boolean;
}

export const NO_FILTERS = defaultSearch('anime');
const DEFAULT_GALAXY_VIEW: GalaxyView = { colour: 'sector', filters: NO_FILTERS, names: true };

const COLOURS: Record<GalaxyColour, true> = { sector: true, score: true, mine: true, own: true };
const STATES = Object.fromEntries(RATED_STATES.anime.map((s) => [s.value, true])) as Record<RatedState, true>;

const number = (raw: unknown) => (typeof raw === 'number' && Number.isFinite(raw) ? raw : undefined);

// Every field the sanitizer reads, or leaves out on purpose: a new filter fails to compile
// here until it joins one or the other, rather than vanishing on the next reload.
type Read = ListFilterKey | ModeKey | RangeParam | 'top_percent' | 'upcoming_main' | 'rated' | 'watchlisted' | 'genres'
	| 'your_score_min' | 'your_score_max' | 'your_top_percent';
type LeftOut = 'query' | 'search_type' | 'view_type' | 'sort' | 'sort_dir';
const EVERY_FIELD: Exclude<keyof MediaSearchFilters, Read | LeftOut> extends never ? true : never = true;

/**
 * Filters read back from storage, whitelisted field by field, so what an older build left
 * there never reaches the sheet or the request. Filters only: the map has no query, and
 * no order to keep.
 */
export function sanitizeFilters(raw: unknown): MediaSearchFilters {
	const r = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
	const out: MediaSearchFilters = { ...NO_FILTERS };
	for (const key of Object.keys(LIST_FILTERS) as ListFilterKey[]) {
		const values = pickStrings(r[key]);
		if (values.length) out[key] = values;
		const mode = LIST_FILTERS[key].mode;
		if (mode && r[mode] != null) out[mode] = pickKey(r[mode], MATCH_MODE_KEYS, 'any');
	}
	const ranges = [...(Object.keys(RANGE_FILTERS) as RangeKey[]).flatMap(rangeParams), 'your_score_min', 'your_score_max'] as const;
	for (const param of ranges) {
		const value = number(r[param]);
		if (value != null) out[param] = value;
	}
	for (const key of ['top_percent', 'your_top_percent'] as const) {
		const value = number(r[key]);
		if (value != null && value >= 1 && value <= 100) out[key] = value;
	}
	if (r.upcoming_main === true) out.upcoming_main = true;
	const rated = pickStrings(r.rated).filter((s): s is RatedState => Object.hasOwn(STATES, s));
	if (rated.length) out.rated = rated;
	if (typeof r.watchlisted === 'boolean') out.watchlisted = r.watchlisted;
	const genres = r.genres as { mode?: unknown; groups?: unknown } | null | undefined;
	if (genres && Array.isArray(genres.groups)) {
		const groups = genres.groups.slice(0, MAX_GENRE_GROUPS).map(
			(g: Record<string, unknown>): GenreGroup => ({
				mode: pickKey(g?.mode, MATCH_MODE_KEYS, 'any'),
				include: pickStrings(g?.include),
				exclude_mode: pickKey(g?.exclude_mode, MATCH_MODE_KEYS, 'any'),
				exclude: pickStrings(g?.exclude)
			})
		);
		if (groups.length) out.genres = { mode: pickKey(genres.mode, MATCH_MODE_KEYS, 'any'), groups };
	}
	return out;
}

/** Kept across a reload and a detail detour, reset on leaving Browse
 *  (`utils/filterLifecycle`). */
export const galaxyView = createPersistedFilter<GalaxyView>({
	key: 'phsar.filter.galaxy',
	version: 1,
	defaults: DEFAULT_GALAXY_VIEW,
	sanitize: (raw) => ({
		colour: pickKey(raw.colour, COLOURS, DEFAULT_GALAXY_VIEW.colour),
		filters: sanitizeFilters(raw.filters),
		names: raw.names !== false
	})
});

export function clearGalaxyView(): void {
	galaxyView.set(DEFAULT_GALAXY_VIEW);
}
