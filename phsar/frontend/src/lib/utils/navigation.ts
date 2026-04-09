import { goto } from '$app/navigation';
import type { MediaSearchFilters } from '$lib/utils/search';
import { api, ApiError } from '$lib/api';
import type { SearchTokenResponse } from '$lib/types/api';
import { token } from '$lib/stores/auth';

export function buildDetailHref(type: 'anime' | 'media', uuid: string, searchToken: string | null): string {
    const base = `/${type}?uuid=${uuid}`;
    return searchToken ? `${base}&q=${encodeURIComponent(searchToken)}` : base;
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
