import { goto } from '$app/navigation';
import type { SearchParams } from '$lib/utils/search';
import { API_URL } from '$lib/config';

export async function navigateToSearch(params: SearchParams) {
    const token = localStorage.getItem('token');

    const res = await fetch(`${API_URL}/filters/create-token`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`
        },
        body: JSON.stringify(params)
    });

    if (!res.ok) {
        throw new Error('Failed to create search token');
    }

    const { token: searchToken } = await res.json();

    const searchUrl = `/search?q=${encodeURIComponent(searchToken)}`;
    console.debug('Navigating to:', searchUrl);
    goto(searchUrl);
}
