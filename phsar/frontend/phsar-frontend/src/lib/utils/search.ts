import { API_URL } from '$lib/config';

export interface MediaSearchFilters {
	query: string;

	// List filters
	relation_type?: string[];
	media_type?: string[];
	age_rating?: string[];
	airing_status?: string[];
	anime_season?: string[];
	genre_name?: string[];
	studio_name?: string[];

	// Range filters
	score_min?: number;
	score_max?: number;
	scored_by_min?: number;
	scored_by_max?: number;
	episodes_min?: number;
	episodes_max?: number;

	// Time filters
	duration_per_episode_min?: number;
	duration_per_episode_max?: number;
	total_watch_time_min?: number;
	total_watch_time_max?: number;
}

export async function fetchSearchResults(params: MediaSearchFilters, token: string | null) {
	const searchParams = new URLSearchParams();

	// Base query
	if (params.query) searchParams.append('query', params.query);

	// List filters
	const listKeys: (keyof MediaSearchFilters)[] = [
		'genre_name',
		'anime_season',
		'studio_name',
		'airing_status',
		'relation_type',
		'media_type',
		'age_rating'
	];

	for (const key of listKeys) {
		const values = params[key];
		if (Array.isArray(values)) {
			values.forEach((v) => searchParams.append(key, v));
		}
	}

	// Number filters
	const numberKeys: (keyof MediaSearchFilters)[] = [
		'score_min',
		'score_max',
		'scored_by_min',
        'scored_by_max',
		'episodes_min',
		'episodes_max',
        'duration_per_episode_min',
		'duration_per_episode_max',
		'total_watch_time_min',
		'total_watch_time_max'
	];

	for (const key of numberKeys) {
		const value = params[key];
		if (typeof value === 'number') {
			searchParams.append(key, value.toString());
		}
	}

	const res = await fetch(`${API_URL}/search/media?${searchParams.toString()}`, {
		headers: { Authorization: `Bearer ${token}` }
	});

	if (!res.ok) {
		throw new Error('Failed to fetch search results');
	}

	return res.json();
}
