import { api } from '$lib/api';
import type {
	AnimeSearchResult, BrowseCarousel, BrowsePageKey, DiscoverToday, DiscoverMoods, MediaSearchResult,
} from '$lib/types/api';
import {
	effectiveSort, fetchAnimeSearchResults, fetchSearchResults, readsOwnData, type MediaSearchFilters, type ViewType,
} from '$lib/utils/search';
import {
	isSetActive, NO_REFINEMENT, refinedSearch, WIDEN_BELOW, widened, type Refinement, type Step,
} from './browseRefinements';
import { catalogueChanged, onBump } from './jobs';

/**
 * Session cache for what Browse fetched or worked out today.
 *
 * Opening a tile and coming back would otherwise refetch every row the user had
 * scrolled past, skeletons and all. Browse's entries follow the section rule
 * (`utils/filterLifecycle`): a detail page is a detour and keeps them, leaving Browse
 * drops them, so a later visit sees today's rows. Home's outlive any navigation, since it
 * is the page users keep returning to and its rows change only with the catalogue. So does
 * a count that widened (`carouselResults`): the pool it counted changes with the catalogue
 * or the viewer's own data, not by leaving Browse. A catalogue change (`catalogueChanged`)
 * drops every entry, and every entry ends with its UTC day, when the daily shuffle moves on.
 *
 * A row over the caller's own ratings or watchlist goes stale on a write to either,
 * so the post-write hooks — `invalidateRatingScores` and `refreshWatchlist` — drop
 * those rows. The rest stay: a write can't change them, and
 * their coverage band and bookmark already follow the write through their own stores.
 * PER-USER, so `clearPerUserStores` clears it.
 *
 * The search pages keep their latest search here too, under the same drops, so a detail
 * page and back renders the list at once rather than re-verifying the token and
 * refetching. A see-all opened on the search page's token reads its verify and its rows
 * (`settledSearch`), so its first step needs no request. A media search is always
 * personal: each hit carries the caller's own `is_rated`, which no store follows. They
 * are search's section, not Browse's: leaving search drops them, and they outlive
 * Browse's own clear, which runs as a search page arrives from Browse.
 */
// One entry per slot, holding the request it was last asked: a see-all keeps a slot per
// carousel, so switching its toggles replaces its list rather than piling one up per
// combination until Browse is left.
// `value` is set once `pending` settles, so a reader can take what is already in hand
// without waiting a tick (`settledResults`).
type Entry = { id: string; pending: Promise<unknown>; value?: unknown; personal: boolean; lasting: boolean };
const cache = new Map<string, Entry>();

const dayId = (id: string) => `${new Date().toISOString().slice(0, 10)} ${id}`;

// `lasting` outlives leaving Browse.
type Lifetime = { personal?: boolean; lasting?: boolean };

// A failure drops its own entry — only while it is still the cached one, as in
// `ratingScores` — so a retry re-requests.
function put(slot: string, id: string, pending: Promise<unknown>, { personal = false, lasting = false }: Lifetime = {}) {
	const entry: Entry = { id: dayId(id), pending, personal, lasting };
	cache.set(slot, entry);
	pending.then(
		(value) => (entry.value = value),
		() => {
			if (cache.get(slot) === entry) cache.delete(slot);
		},
	);
}

// The entry `slot` holds for `id`, while it is today's.
function held(slot: string, id: string): Entry | undefined {
	const hit = cache.get(slot);
	return hit?.id === dayId(id) ? hit : undefined;
}

// Concurrent callers share one request.
function cached<T>(slot: string, id: string, load: () => Promise<T>, lifetime: Lifetime = {}): Promise<T> {
	const hit = held(slot, id);
	if (hit) return hit.pending as Promise<T>;
	const pending = load();
	put(slot, id, pending, lifetime);
	return pending;
}

export function browsePage(page: BrowsePageKey): Promise<BrowseCarousel[]> {
	const key = `page:${page}`;
	return cached(key, key, () => api.get<BrowseCarousel[]>(`/browse/${page}`), { lasting: page === 'home' });
}

/** One carousel resolved with its filter sets switched — a see-all's search. */
export function browseCarousel(key: string, on: string[], off: string[]): Promise<BrowseCarousel> {
	const params = new URLSearchParams();
	for (const k of on) params.append('on', k);
	for (const k of off) params.append('off', k);
	return cached(`carousel:${key}`, `${params}`, () =>
		api.get<BrowseCarousel>(`/browse/carousels/${encodeURIComponent(key)}`, { params }),
	);
}

/** A row's results, keyed by the search itself, which names everything that changes them —
 *  under `slot` when given, which keeps only the latest search. `page` decides only how long
 *  the entry lives: Home's outlive leaving Browse. */
export function browseRow(
	params: MediaSearchFilters, limit: number, { slot, page }: { slot?: string; page?: BrowsePageKey | null } = {},
): Promise<AnimeSearchResult[]> {
	const id = rowId(params, limit);
	return cached(
		slot ? `see-all:${slot}` : rowSlot(id),
		id,
		() => fetchAnimeSearchResults(params, limit),
		{ personal: readsOwnData(params), lasting: page === 'home' },
	);
}

const rowId = (params: MediaSearchFilters, limit: number) => JSON.stringify([params, limit]);
const rowSlot = (id: string) => `row:${id}`;

type SearchPage = 'search' | 'search-all';
type SearchRow = AnimeSearchResult | MediaSearchResult;

const rowsSlot = (page: SearchPage) => `search:${page}:rows`;
const searchId = (params: MediaSearchFilters, grain: ViewType, limit: number) => JSON.stringify([params, grain, limit]);

/** A search token's filters: a token always decodes to the same ones, so it is one slot
 *  whichever page asks. */
export function verifiedToken(token: string): Promise<MediaSearchFilters> {
	return cached('search:token', token, () => api.post<MediaSearchFilters>('/filters/verify-token', { token }), {
		lasting: true,
	});
}

/** A search page's results — one slot per page, holding its latest search. */
export function searchRows(page: SearchPage, params: MediaSearchFilters, grain: ViewType, limit: number): Promise<SearchRow[]> {
	return cached<SearchRow[]>(
		rowsSlot(page),
		searchId(params, grain, limit),
		() => (grain === 'anime' ? fetchAnimeSearchResults(params, limit) : fetchSearchResults(params, limit)),
		{ personal: readsOwnData(params) || grain === 'media', lasting: true },
	);
}

/** A search page's results if already in hand: what `searchRows` would return, without
 *  running anything. */
export function settledSearch(page: SearchPage, params: MediaSearchFilters, grain: ViewType, limit: number): SearchRow[] | undefined {
	return held(rowsSlot(page), searchId(params, grain, limit))?.value as SearchRow[] | undefined;
}

/** Discover's wheel and today's mood. `spun` says whether this viewer has seen the wheel
 *  land today: a user once their spin is counted, a guest — whose mood the day draws —
 *  once it has spun in this visit. */
export interface DiscoverState extends DiscoverMoods {
	spun: boolean;
}

export function discoverMoods(isGuest: boolean): Promise<DiscoverState> {
	return cached('moods', 'moods', async () => {
		const moods = await api.get<DiscoverMoods>('/browse/moods');
		return { ...moods, spun: moods.today !== null && !isGuest };
	});
}

/** Spin the wheel: Discover with today's mood, kept so a detail page and back lands on it
 *  rather than on the wheel. A guest can't spin (read-only), so its spin lands on the mood
 *  it was given. */
export async function spinMood(isGuest: boolean): Promise<DiscoverState> {
	const state = await discoverMoods(isGuest);
	const today = isGuest && state.today ? state.today : await api.post<DiscoverToday>('/browse/moods/spin');
	const spun = { ...state, today, spun: true };
	put('moods', 'moods', Promise.resolve(spun));
	return spun;
}

/** Discover with `key`'s mood in today's place. Not kept, unlike a spin: Discover goes on
 *  showing today's draw. */
export async function previewMood(key: string, isGuest: boolean): Promise<DiscoverState> {
	const state = await discoverMoods(isGuest);
	const today = await api.get<DiscoverToday>(`/browse/moods/${encodeURIComponent(key)}`);
	return { ...state, today, spun: true };
}

/**
 * A carousel's list under `refinement`, widened where `widened` says
 * (docs/features/browse.md#a-thin-row-widens), with the carousel and refinement it ran. It
 * asks for enough to tell, unless an earlier count today already told, and remembers a
 * count that widened.
 */
export async function carouselResults(
	carousel: BrowseCarousel, refinement: Refinement, isGuest: boolean, limit: number,
	where: { slot?: string; page?: BrowsePageKey | null } = {},
): Promise<Step & { results: AnimeSearchResult[] }> {
	const run = (at: Step, n: number) => browseRow(refinedSearch(at.carousel, at.refinement, isGuest), n, where);
	const known = knownStep(carousel, refinement);
	if (known) return { ...known, results: await run(known, limit) };
	const asked = { carousel, refinement };
	const narrow = await run(asked, Math.max(limit, WIDEN_BELOW));
	if (narrow.length >= WIDEN_BELOW) return { ...asked, results: narrow.slice(0, limit) };
	put(widenedSlot(carousel, refinement), 'widened', Promise.resolve(true), {
		personal: readsOwnData(refinedSearch(carousel, refinement, isGuest)), lasting: true,
	});
	const wide = widened(carousel, refinement)!; // unknown means it can widen
	return { ...wide, results: await run(wide, limit) };
}

// A count stands for the toggles it ran under: a see-all's toggle narrowing the pool must
// not widen the row. Only toggles outside the Top group can be on here (`widened`).
const widenedSlot = (carousel: BrowseCarousel, refinement: Refinement) =>
	`widened:${carousel.key}:${[...refinement.on].sort()}|${[...refinement.off].sort()}`;

const isWidened = (carousel: BrowseCarousel, refinement: Refinement) =>
	held(widenedSlot(carousel, refinement), 'widened') !== undefined;

/** The step `refinement` lists at, where it is known before running it: as asked when it
 *  can't widen, widened when today's count already said so — or null, still to be counted. */
export function knownStep(carousel: BrowseCarousel, refinement: Refinement): Step | null {
	const wide = widened(carousel, refinement);
	if (!wide) return { carousel, refinement };
	return isWidened(carousel, refinement) ? wide : null;
}

/** A row's list under `refinement` if it is already in hand: the lookup `carouselResults`
 *  makes, without running anything. */
export function settledResults(
	carousel: BrowseCarousel, refinement: Refinement, isGuest: boolean, limit: number,
): AnimeSearchResult[] | undefined {
	const peek = (at: Step, n: number) => {
		const id = rowId(refinedSearch(at.carousel, at.refinement, isGuest), n);
		return held(rowSlot(id), id)?.value as AnimeSearchResult[] | undefined;
	};
	const known = knownStep(carousel, refinement);
	if (known) return peek(known, limit);
	const narrow = peek({ carousel, refinement }, Math.max(limit, WIDEN_BELOW));
	return narrow && narrow.length >= WIDEN_BELOW ? narrow.slice(0, limit) : undefined;
}

/** Whether a see-all showing `shown` lists other than its defaults — what Reset returns to,
 *  widened where the row is: a set lit or dark against them, or another order. Compared by
 *  effect rather than by what was stored, so a choice undone by hand reads as none. */
export function refinedFromDefaults(carousel: BrowseCarousel, shown: Refinement): boolean {
	const defaults = knownStep(carousel, NO_REFINEMENT)?.refinement ?? NO_REFINEMENT;
	if (carousel.filter_sets.some((s) => isSetActive(s, shown) !== isSetActive(s, defaults))) return true;
	const sortOf = (r: Refinement) => effectiveSort(refinedSearch(carousel, r, false));
	const [now, base] = [sortOf(shown), sortOf(NO_REFINEMENT)];
	return now.sort !== base.sort || now.dir !== base.dir;
}

/** After a rating or watchlist write: drop the rows that read them. */
export function dropPersonalRows(): void {
	for (const [key, entry] of cache) if (entry.personal) cache.delete(key);
}

/** Leaving Browse: drop its entries, and keep the lasting ones. */
export function clearSectionRows(): void {
	for (const [key, entry] of cache) if (!entry.lasting) cache.delete(key);
}

/** Leaving search: drop its pages' searches. */
export function clearSearchRows(): void {
	for (const key of cache.keys()) if (key.startsWith('search:')) cache.delete(key);
}

export function clearBrowseRows(): void {
	cache.clear();
}

onBump(catalogueChanged, clearBrowseRows);
