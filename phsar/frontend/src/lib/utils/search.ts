import { api } from '$lib/api';

export interface MediaSearchFilters {
	query: string;
	search_type: string;

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

export async function fetchSearchResults(params: MediaSearchFilters): Promise<unknown[]> {
	const searchParams = new URLSearchParams();

	if (params.query) searchParams.append('query', params.query);
	if (params.search_type) searchParams.append('search_type', params.search_type);

	const listKeys: (keyof MediaSearchFilters)[] = [
		'genre_name', 'anime_season', 'studio_name', 'airing_status',
		'relation_type', 'media_type', 'age_rating',
	];

	for (const key of listKeys) {
		const values = params[key];
		if (Array.isArray(values)) {
			values.forEach((v) => searchParams.append(key, v));
		}
	}

	const numberKeys: (keyof MediaSearchFilters)[] = [
		'score_min', 'score_max', 'scored_by_min', 'scored_by_max',
		'episodes_min', 'episodes_max', 'duration_per_episode_min',
		'duration_per_episode_max', 'total_watch_time_min', 'total_watch_time_max',
	];

	for (const key of numberKeys) {
		const value = params[key];
		if (typeof value === 'number') {
			searchParams.append(key, value.toString());
		}
	}

	return api.get<unknown[]>('/search/media', { params: searchParams });
}
