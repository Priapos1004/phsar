import { goto } from '$app/navigation';
import type { MediaSearchFilters } from '$lib/utils/search';
import { api, ApiError } from '$lib/api';
import type { SearchTokenResponse } from '$lib/types/api';
import { token } from '$lib/stores/auth';

/** Closed set of non-search origin markers that detail pages handle.
 * Extend this union (and BackLink.svelte's `target` switch) when a new
 * entry point needs a labeled back button. */
export type DetailOrigin = 'library' | 'job' | 'completion' | 'curation' | 'ratings' | 'ratings-stats';

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
}

export function buildDetailHref(
    type: 'anime' | 'media',
    uuid: string,
    opts?: DetailHrefOptions,
): string {
    const params = new URLSearchParams({ uuid });
    if (opts?.q) params.set('q', opts.q);
    if (opts?.from) params.set('from', opts.from);
    if (opts?.job) params.set('job', opts.job);
    return `/${type}?${params.toString()}`;
}

export async function navigateToSearch(params: MediaSearchFilters) {
    try {
        const data = await api.post<SearchTokenResponse>('/filters/create-token', params);
        goto(`/search?q=${encodeURIComponent(data.token)}`);
    } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
            token.set(null);
            window.location.href = '/login';
        } else {
            throw err;
        }
    }
}
