import { API_URL } from '$lib/config';

export interface SearchParams {
    query: string;
    genre: string[];
    season: string[];
}

export async function fetchSearchResults(params: SearchParams, token: string | null) {
    console.log(params);
    const { query, genre, season } = params;

    const searchParams = new URLSearchParams();
    if (query) searchParams.append('query', query);
    genre.forEach(g => searchParams.append('genre_name', g));
    season.forEach(s => searchParams.append('anime_season', s));

    const res = await fetch(`${API_URL}/search/media?${searchParams.toString()}`, {
        headers: { Authorization: `Bearer ${token}` }
    });

    if (!res.ok) {
        throw new Error('Failed to fetch search results');
    }

    return res.json();
}
