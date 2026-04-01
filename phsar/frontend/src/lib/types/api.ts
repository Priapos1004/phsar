/** TypeScript types mirroring backend Pydantic schemas */

// Auth
export interface TokenResponse {
	access_token: string;
	token_type: string;
}

export interface TokenValidationResponse {
	is_valid: boolean;
}

// Media
export interface MediaConnected {
	mal_id: number;
	mal_url: string;
	title: string;
	name_eng: string | null;
	name_jap: string | null;
	other_names: string[];
	media_type: string;
	relation_type: string;
	age_rating: string | null;
	description: string | null;
	original_source: string | null;
	cover_image: string | null;
	score: number | null;
	scored_by: number;
	episodes: number | null;
	anime_season_name: string | null;
	anime_season_year: number | null;
	airing_status: string;
	aired_from: string | null;
	aired_to: string | null;
	duration: string | null;
	duration_seconds: number | null;
	genres: string[];
	studio: string[];
	anime_uuid: string;
	anime_title: string;
	anime_name_eng: string | null;
	anime_name_jap: string | null;
	anime_other_names: string[];
	uuid: string;
	total_watch_time: number | null;
	age_rating_numeric: number | null;
}

// Filter options (GET /filters/options)
export interface FilterOptions {
	relation_type: string[];
	media_type: string[];
	age_rating: string[];
	airing_status: string[];
	anime_season: string[];
	genre_name: string[];
	studio_name: string[];
	score_min: number | null;
	score_max: number | null;
	scored_by_min: number | null;
	scored_by_max: number | null;
	episodes_min: number | null;
	episodes_max: number | null;
	duration_per_episode_min: number | null;
	duration_per_episode_max: number | null;
	total_watch_time_min: number | null;
	total_watch_time_max: number | null;
}

// Search token (POST /filters/create-token)
export interface SearchTokenResponse {
	token: string;
}
