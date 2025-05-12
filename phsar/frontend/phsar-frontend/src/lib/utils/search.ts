import { API_URL } from '$lib/config';

export interface SearchParams {
    query: string;
    genre_name: string[];
    anime_season: string[];
}

export async function fetchSearchResults(params: SearchParams, token: string | null) {
    console.log(params);
    const { query, genre_name, anime_season } = params;

    const searchParams = new URLSearchParams();
    if (query) searchParams.append('query', query);
    genre_name.forEach(g => searchParams.append('genre_name', g));
    anime_season.forEach(s => searchParams.append('anime_season', s));

    const res = await fetch(`${API_URL}/search/media?${searchParams.toString()}`, {
        headers: { Authorization: `Bearer ${token}` }
    });

    if (!res.ok) {
        throw new Error('Failed to fetch search results');
    }

    return res.json();
}
