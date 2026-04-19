/** TypeScript types mirroring backend Pydantic schemas */
import type { ThemeKey } from '$lib/themes';

// Auth
export interface TokenResponse {
	access_token: string;
	token_type: string;
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

// Media detail
export interface MediaSibling {
	uuid: string;
	title: string;
	name_eng: string | null;
	name_jap: string | null;
	cover_image: string | null;
	media_type: string;
	relation_type: string;
	episodes: number | null;
	airing_status: string;
	anime_season_name: string | null;
	anime_season_year: number | null;
}

export interface MediaDetail extends MediaConnected {
	sibling_media: MediaSibling[];
}

// Rating attribute enums
export type Pace = 'slow' | 'normal' | 'fast';
export type AnimationQuality = 'bad' | 'normal' | 'good' | 'outstanding';
export type ThreeDAnimation = 'none' | 'partial' | 'full';
export type WatchedFormat = 'sub' | 'dub' | 'both';
export type FanService = 'none' | 'rare' | 'normal' | 'heavy';
export type DialogueQuality = 'flat' | 'normal' | 'deep';
export type CharacterDepth = 'flat' | 'normal' | 'complex';
export type EndingType = 'open' | 'closed' | 'cliffhanger';
export type EndingQuality = 'unsatisfying' | 'satisfying' | 'exceptional' | 'not_applicable';
export type StoryQuality = 'weak' | 'average' | 'good' | 'outstanding';
export type Originality = 'conventional' | 'unique' | 'experimental';

// Ratings
export interface RatingOut {
	uuid: string;
	rating: number;
	dropped: boolean;
	episodes_watched: number | null;
	note: string | null;
	media_uuid: string;
	media_title: string;
	media_cover_image: string | null;
	anime_uuid: string;
	anime_title: string;
	pace: Pace | null;
	animation_quality: AnimationQuality | null;
	has_3d_animation: ThreeDAnimation | null;
	watched_format: WatchedFormat | null;
	fan_service: FanService | null;
	dialogue_quality: DialogueQuality | null;
	character_depth: CharacterDepth | null;
	ending_type: EndingType | null;
	ending_quality: EndingQuality | null;
	story_quality: StoryQuality | null;
	originality: Originality | null;
	created_at: string;
	modified_at: string;
}

export interface RatingCreate {
	rating: number;
	dropped?: boolean;
	episodes_watched?: number | null;
	note?: string | null;
	pace?: Pace | null;
	animation_quality?: AnimationQuality | null;
	has_3d_animation?: ThreeDAnimation | null;
	watched_format?: WatchedFormat | null;
	fan_service?: FanService | null;
	dialogue_quality?: DialogueQuality | null;
	character_depth?: CharacterDepth | null;
	ending_type?: EndingType | null;
	ending_quality?: EndingQuality | null;
	story_quality?: StoryQuality | null;
	originality?: Originality | null;
}

/** Read a dynamic attribute key from a rating object (needed because attribute keys are iterated at runtime). */
export function getRatingAttr(obj: RatingOut | RatingCreate, key: string): string | null {
	return (obj as unknown as Record<string, string | null>)[key] ?? null;
}

/** Maps each rating attribute to its display label and possible values. */
export const RATING_ATTRIBUTE_OPTIONS: Record<string, { label: string; options: { value: string; label: string }[] }> = {
	pace: { label: 'Pace', options: [{ value: 'slow', label: 'Slow' }, { value: 'normal', label: 'Normal' }, { value: 'fast', label: 'Fast' }] },
	animation_quality: { label: 'Animation Quality', options: [{ value: 'bad', label: 'Bad' }, { value: 'normal', label: 'Normal' }, { value: 'good', label: 'Good' }, { value: 'outstanding', label: 'Outstanding' }] },
	has_3d_animation: { label: '3D Animation', options: [{ value: 'none', label: 'None' }, { value: 'partial', label: 'Partial' }, { value: 'full', label: 'Full' }] },
	watched_format: { label: 'Watched Format', options: [{ value: 'sub', label: 'Sub' }, { value: 'dub', label: 'Dub' }, { value: 'both', label: 'Both' }] },
	fan_service: { label: 'Fan Service', options: [{ value: 'none', label: 'None' }, { value: 'rare', label: 'Rare' }, { value: 'normal', label: 'Normal' }, { value: 'heavy', label: 'Heavy' }] },
	dialogue_quality: { label: 'Dialogue Quality', options: [{ value: 'flat', label: 'Flat' }, { value: 'normal', label: 'Normal' }, { value: 'deep', label: 'Deep' }] },
	character_depth: { label: 'Character Depth', options: [{ value: 'flat', label: 'Flat' }, { value: 'normal', label: 'Normal' }, { value: 'complex', label: 'Complex' }] },
	ending_type: { label: 'Ending Type', options: [{ value: 'open', label: 'Open' }, { value: 'closed', label: 'Closed' }, { value: 'cliffhanger', label: 'Cliffhanger' }] },
	ending_quality: { label: 'Ending Quality', options: [{ value: 'unsatisfying', label: 'Unsatisfying' }, { value: 'satisfying', label: 'Satisfying' }, { value: 'exceptional', label: 'Exceptional' }, { value: 'not_applicable', label: 'Not Applicable' }] },
	story_quality: { label: 'Story Quality', options: [{ value: 'weak', label: 'Weak' }, { value: 'average', label: 'Average' }, { value: 'good', label: 'Good' }, { value: 'outstanding', label: 'Outstanding' }] },
	originality: { label: 'Originality', options: [{ value: 'conventional', label: 'Conventional' }, { value: 'unique', label: 'Unique' }, { value: 'experimental', label: 'Experimental' }] },
};

// Anime search result (aggregated)
export interface RelationTypeSummary {
	relation_type: string;
	count: number;
}

export interface MediaTypeSummary {
	media_type: string;
	count: number;
}

/** Shared aggregated fields for anime search results and detail views. */
export interface AnimeAggregatedBase {
	uuid: string;
	title: string;
	name_eng: string | null;
	name_jap: string | null;
	cover_image: string | null;
	avg_score: number | null;
	avg_scored_by: number;
	total_episodes: number | null;
	total_watch_time: number | null;
	media_count: number;
	relation_types: RelationTypeSummary[];
	media_types: MediaTypeSummary[];
	genres: string[];
	studios: string[];
	season_start: string | null;
	season_end: string | null;
	airing_status: string;
	has_upcoming: boolean;
	age_rating_numeric: number | null;
}

export interface AnimeSearchResult extends AnimeAggregatedBase {}

// Anime detail
export interface AnimeMediaItem {
	uuid: string;
	title: string;
	name_eng: string | null;
	name_jap: string | null;
	cover_image: string | null;
	media_type: string;
	relation_type: string;
	score: number | null;
	scored_by: number;
	episodes: number | null;
	airing_status: string;
	anime_season_name: string | null;
	anime_season_year: number | null;
	total_watch_time: number | null;
	age_rating_numeric: number | null;
	genres: string[];
	studios: string[];
}

export interface AnimeDetail extends AnimeAggregatedBase {
	other_names: string[];
	description: string | null;
	media: AnimeMediaItem[];
}

// Search token (POST /filters/create-token)
export interface SearchTokenResponse {
	token: string;
}

// User Settings
export interface UserSettings {
	theme: ThemeKey;
	name_language: 'english' | 'japanese' | 'romaji';
	default_search_view: 'anime' | 'media';
	rating_step: '0.5' | '0.25' | '0.1' | '0.01';
	spoiler_level: 'off' | 'blur' | 'hide';
}

export type UserSettingsUpdate = Partial<UserSettings>;

// Spoiler visibility
export interface SpoilerVisibility {
	visible_media_uuids: string[];
}

// Admin — Registration tokens
export interface RegistrationTokenListItem {
	uuid: string;
	token: string;
	role: string;
	status: 'active' | 'used' | 'expired';
	created_by: string;
	created_at: string;
	expires_on: string;
	used_by: string | null;
	used_at: string | null;
}

// Admin — Backups
export type BackupIntegrity = 'ok' | 'corrupt' | 'unknown';
export type BackupSource = 'manual' | 'cron' | 'pre_restore' | 'upload';

export interface BackupMetadata {
	filename: string;
	size_bytes: number;
	created_at: string;
	integrity: BackupIntegrity;
	source: BackupSource;
}
