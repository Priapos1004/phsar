import { goto } from '$app/navigation';
import type { MediaSearchFilters } from '$lib/utils/search';
import { api, ApiError } from '$lib/api';
import type { SearchTokenResponse } from '$lib/types/api';
import { token } from '$lib/stores/auth';
import { captureReturnTarget } from '$lib/utils/resumeSession';
import { FOCUS_PARAM } from '$lib/utils/scrollFocus';

/** Whole-row click → navigate, shared by the ratings + watchlist tables. Preserves
 * native new-tab (modifier / middle click) and lets a real `<a>` inside the row handle
 * its own clicks (keyboard focus + open-in-new-tab). */
export function rowClickNavigate(e: MouseEvent, href: string): void {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
    if ((e.target as HTMLElement).closest('a')) return;
    goto(href);
}

/** Closed set of non-search origin markers that detail pages handle.
 * Extend this union (and BackLink.svelte's `target` switch) when a new
 * entry point needs a labeled back button — and, for one carrying an id the
 * way `job` does, `DetailHrefOptions`, `buildDetailHref` and `detailOrigin`. */
export type DetailOrigin =
    | 'library' | 'job' | 'completion' | 'curation' | 'ratings' | 'ratings-stats' | 'watchlist' | 'browse'
    | 'carousel' | 'search-all';

export interface DetailHrefOptions {
    /** Search token to propagate so the detail page renders "Back to search". */
    q?: string | null;
    /** Origin marker for non-search entry points. The detail page reads
     * this to render a labeled back button like "Back to library". */
    from?: DetailOrigin | null;
    /** Job uuid carried alongside `from: 'job'` so the back button can link
     * to that specific `/admin/jobs/[uuid]` row (the admin came from a sweep
     * audit). Propagated on anime↔media jumps like `q`/`from`. */
    job?: string | null;
    /** Carousel key carried alongside `from: 'carousel'`, so the back button can link
     * to that carousel's see-all page. Propagated like `job`. */
    carousel?: string | null;
    /** Uuid of the list item this detour started from, so the back button can
     * scroll it into view — see `utils/scrollFocus`. Propagated on anime↔media
     * jumps like `q`/`from`. */
    focus?: string | null;
}

/** The two detail grains, and therefore the two top-level detail routes
 * (`/anime`, `/media`). Exported so `utils/filterLifecycle` derives its
 * detour set from here instead of restating the pair — adding a third grain
 * or renaming one otherwise needs two edits with nothing linking them, and
 * the miss is silent. */
export const DETAIL_TYPES = ['anime', 'media'] as const;
export type DetailType = (typeof DETAIL_TYPES)[number];

export function buildDetailHref(
    type: DetailType,
    uuid: string,
    opts?: DetailHrefOptions,
): string {
    const params = new URLSearchParams({ uuid });
    if (opts?.q) params.set('q', opts.q);
    if (opts?.from) params.set('from', opts.from);
    if (opts?.job) params.set('job', opts.job);
    if (opts?.carousel) params.set('carousel', opts.carousel);
    if (opts?.focus) params.set(FOCUS_PARAM, opts.focus);
    return `/${type}?${params.toString()}`;
}

/**
 * The origin a detail page arrived with — the bag every anime↔media hop forwards whole.
 *
 * This page IS the item that was clicked, so its own uuid is the focus unless a deeper
 * hop already named one — see `utils/scrollFocus`.
 */
export function detailOrigin(url: URL): DetailHrefOptions {
    const p = url.searchParams;
    return {
        q: p.get('q'),
        from: p.get('from') as DetailOrigin | null,
        job: p.get('job'),
        carousel: p.get('carousel'),
        focus: p.get(FOCUS_PARAM) ?? p.get('uuid'),
    };
}

/**
 * The absolute, shareable form of a detail link — what goes to a share sheet.
 *
 * Deliberately **bare**: it carries none of the params recording how the *sharer*
 * arrived, which mean nothing to a recipient, and the search token alone is ~1400
 * characters of noise in a chat. Built from the uuid for that reason rather than
 * read off the address bar, which is carrying all of them.
 */
export function absoluteDetailUrl(type: DetailType, uuid: string, origin: string): string {
    return `${origin}${buildDetailHref(type, uuid)}`;
}

/** Jump to an anime-view search filtered to a single studio ("other anime from this
 * studio"). Shared by the detail pages and the stats charts so the filter shape can't
 * drift between them. */
export function searchByStudio(studio: string): void {
	void navigateToSearch({ query: '', search_type: 'title', view_type: 'anime', studio_name: [studio] });
}

/** The same jump for an original source ("other anime adapted from light novels"). */
export function searchBySource(source: string): void {
	void navigateToSearch({ query: '', search_type: 'title', view_type: 'anime', original_source: [source] });
}

/** Create a search token from the filters and navigate to `path` with it — /search, or
 * a search's see-all page. Best-effort and
 * fire-and-forget: a 401 redirects to login; any other failure is logged, not thrown,
 * so any caller can invoke it without a `.catch` and never trip an unhandled promise
 * rejection. */
export async function navigateToSearch(params: MediaSearchFilters, path: '/search' | '/search/all' = '/search') {
    try {
        const data = await api.post<SearchTokenResponse>('/filters/create-token', params);
        goto(`${path}?q=${encodeURIComponent(data.token)}`);
    } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
            // Captured before the clear, as captureReturnTarget requires — the
            // caller may well be the ratings page's own chart, whose filters are
            // worth coming back to.
            const target = captureReturnTarget(new URL(window.location.href));
            token.set(null);
            window.location.href = target;
        } else {
            console.error('Search navigation failed:', err);
        }
    }
}
