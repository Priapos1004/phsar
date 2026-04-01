import { goto } from '$app/navigation';
import type { MediaSearchFilters } from '$lib/utils/search';
import { api } from '$lib/api';

export async function navigateToSearch(params: MediaSearchFilters) {
    const data = await api.post<{ token: string }>('/filters/create-token', params);
    goto(`/search?q=${encodeURIComponent(data.token)}`);
}
